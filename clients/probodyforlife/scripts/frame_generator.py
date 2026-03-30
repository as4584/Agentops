#!/usr/bin/env python3
"""
frame_generator.py
===================
Layer 3 — Frame Generator with Multi-Anchor Anti-Drift System

READ SYSTEM_POLICY.md BEFORE EDITING THIS FILE.

Pipeline per scene:
  1. Load character profile, style, background from VideoGenerator/
  2. Select best seed image (closest approved pose or front.png)
  3. Build kontext prompt programmatically — never hardcoded
  4. Call fal-ai/flux-pro/kontext (image-guided generation)
  5. Run drift score against character front.png (SSIM)
  6. Auto-reject if score < drift_threshold
  7. Save passing frames to frames/[campaign]/pending/

USAGE:
  # Generate one scene
  python scripts/frame_generator.py --scene scenes/xpel_ad/scene_01.json

  # Generate all scenes for a campaign
  python scripts/frame_generator.py --campaign xpel_ad

  # Specify a seed pose override
  python scripts/frame_generator.py --scene scenes/xpel_ad/scene_04.json \\
      --seed-pose VideoGenerator/characters/MrWilly/approved_poses/pose_02.png

  # Retry a rejected scene with a note
  python scripts/frame_generator.py --scene scenes/xpel_ad/scene_04.json \\
      --rejection-note "guy is sitting not standing, must be fully upright"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import fal_client
import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image
from skimage.metrics import structural_similarity as ssim

# ── Root paths ────────────────────────────────────────────────────────────────
PROJ_ROOT = Path(__file__).parent.parent          # probodyforlife/
VG        = PROJ_ROOT / "VideoGenerator"

# ── Env — walk up until we find .env ─────────────────────────────────────────
_search = PROJ_ROOT
for _ in range(5):
    if (_search / ".env").exists():
        load_dotenv(_search / ".env")
        break
    _search = _search.parent

FAL_KEY = os.getenv("FAL_KEY", "")
if not FAL_KEY:
    sys.exit("ERROR: FAL_KEY not found in .env")
os.environ["FAL_KEY"] = FAL_KEY


# ══════════════════════════════════════════════════════════════════════════════
#  VAULT LOADERS  (all reads go through here — never open JSON ad-hoc)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_character_dir(name: str) -> Path:
    """
    Resolve the directory that contains a character's profile.json.

    Supports two layouts:
      - Flat:   VideoGenerator/characters/MrWilly/profile.json
      - Nested: VideoGenerator/characters/Xpel/diuretic/profile.json

    For nested characters, the scene JSON uses the top-level name ("Xpel")
    and this function automatically finds the first matching subdirectory.
    """
    # Try flat first
    flat = VG / "characters" / name
    if (flat / "profile.json").exists():
        return flat
    # Try one level deep (product sub-SKU folders like Xpel/diuretic)
    matches = list((VG / "characters" / name).glob("*/profile.json"))
    if matches:
        return matches[0].parent
    sys.exit(f"ERROR: Character profile not found for '{name}' in {VG / 'characters' / name}")


def load_character(name: str) -> dict:
    path = resolve_character_dir(name) / "profile.json"
    return json.loads(path.read_text())


def load_style(style_path: str) -> dict:
    # style_path is relative to PROJ_ROOT e.g. "VideoGenerator/styles/Pixar/style.json"
    path = PROJ_ROOT / style_path
    if not path.exists():
        sys.exit(f"ERROR: Style NOT found: {path}")
    return json.loads(path.read_text())


def load_background(bg_path: str) -> dict:
    path = PROJ_ROOT / bg_path
    if not path.exists():
        sys.exit(f"ERROR: Background NOT found: {path}")
    return json.loads(path.read_text())


def load_scene(scene_json: Path) -> dict:
    if not scene_json.exists():
        sys.exit(f"ERROR: Scene blueprint not found: {scene_json}")
    return json.loads(scene_json.read_text())


# ══════════════════════════════════════════════════════════════════════════════
#  SEED IMAGE SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def select_seed_image(character_name: str, pose_override: str | None = None) -> Path:
    """
    Choose the best seed image for kontext generation.

    Priority:
      1. User-specified --seed-pose override
      2. Most recently added approved pose (richest character data)
      3. Fallback: front.png anchor image

    The seed image is what kontext EDITS. Choosing a pose already
    close to the target reduces how much work kontext has to do,
    which improves character fidelity.
    """
    if pose_override:
        p = Path(pose_override)
        if not p.exists():
            p = PROJ_ROOT / pose_override
        if not p.exists():
            sys.exit(f"ERROR: Seed pose override not found: {pose_override}")
        print(f"  [SEED] Using override: {p.name}")
        return p

    char_dir = resolve_character_dir(character_name)
    poses_dir = char_dir / "approved_poses"
    poses = sorted(
        [f for f in poses_dir.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")
         and not f.name.startswith(".")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ) if poses_dir.exists() else []

    if poses:
        print(f"  [SEED] Using latest approved pose: {poses[0].name}")
        return poses[0]

    # Last resort: front.png
    front = char_dir / "front.png"
    if not front.exists():
        sys.exit(f"ERROR: No seed image. Add front.png to {char_dir}")
    print(f"  [SEED] No approved poses — using front.png")
    return front


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER  (never hardcoded — all text comes from JSON)
# ══════════════════════════════════════════════════════════════════════════════

def build_kontext_prompt(
    scene: dict,
    character: dict,
    style: dict,
    background: dict,
    rejection_note: str | None = None,
) -> tuple[str, str]:
    """
    Build positive and negative prompts for flux-pro/kontext.
    All content derived from JSON — nothing hardcoded.
    Returns: (positive_prompt, negative_prompt)
    """
    frame = scene["frame"]

    # Character generation prefixes
    char_sections = [load_character(n)["generation"]["positive_prefix"]
                     for n in frame["characters_present"]]

    # Pose and expression per character
    pose_lines = []
    for char_name in frame["characters_present"]:
        pose = frame.get(f"{char_name}_pose", "")
        expr = frame.get(f"{char_name}_expression", "")
        if pose:
            pose_lines.append(f"{char_name}: {pose}. Expression: {expr}")

    # Anchor preservation instruction
    chars_str = " and ".join(frame["characters_present"])
    anchor_instruction = (
        f"Keep the identity, face, skin tone, clothing, and overall appearance of "
        f"{chars_str} EXACTLY as shown in the reference image. "
        f"Only change the pose and expression as instructed. "
        f"Do not alter the background, lighting, or rendering style."
    )

    camera = f"Camera: {frame.get('camera_angle', 'medium shot, eye level')}"

    rejection_section = f"\n\nCORRECTION REQUIRED: {rejection_note}" if rejection_note else ""

    positive = (
        f"{style['generation_prefix']}, "
        f"{background['generation_prompt']}, "
        f"{', '.join(char_sections)}, "
        f"{'. '.join(pose_lines)}. "
        f"{anchor_instruction} "
        f"{camera}."
        f"{rejection_section}"
    )

    # Merge negatives from all sources
    negatives = set()
    negatives.update(style["negative"].split(", "))
    for n in frame["characters_present"]:
        negatives.update(load_character(n)["generation"]["negative"].split(", "))
    if "negative" in background:
        negatives.update(background["negative"].split(", "))
    negatives.update([
        "face distortion", "morphing face", "identity change", "different person",
        "face warp", "deformed face", "blurry face", "extra limbs", "body distortion",
        "anatomy change", "wrong clothing", "missing jersey number",
    ])

    return positive, ", ".join(sorted(negatives))


# ══════════════════════════════════════════════════════════════════════════════
#  DRIFT SCORE
# ══════════════════════════════════════════════════════════════════════════════

def drift_score(generated_path: Path, reference_path: Path, target_size: tuple = (256, 256)) -> float:
    """
    Compare generated frame to character front.png via SSIM.
    Returns 0.0–1.0. Score < drift_threshold → auto-reject.

    Uses center crop (50% of image) to focus on character torso/face
    and avoid penalizing intentional background or pose changes.
    """
    def load_gray(p: Path) -> np.ndarray:
        img = Image.open(p).convert("RGB")
        w, h = img.size
        img = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
        img = img.resize(target_size, Image.LANCZOS)
        return np.array(img.convert("L"))

    score, _ = ssim(load_gray(generated_path), load_gray(reference_path), full=True)
    return float(score)


# ══════════════════════════════════════════════════════════════════════════════
#  FULL SCENE PROMPT BUILDER  (for text-to-image — multi-character or no seed)
# ══════════════════════════════════════════════════════════════════════════════

def build_t2i_prompt(scene: dict, style: dict, background: dict) -> tuple[str, str]:
    """
    Build a text-to-image prompt for full scene composition.

    Used when a scene has multiple characters OR no suitable seed image exists.
    Unlike kontext, this creates the ENTIRE composition from a text description:
      - Background + table
      - Every character with exact description + pose + expression
      - Camera angle and framing

    Returns: (positive_prompt, negative_prompt)
    """
    frame = scene["frame"]

    # Build per-character descriptions with exact pose and expression
    char_blocks = []
    for char_name in frame["characters_present"]:
        c = load_character(char_name)
        prefix = c["generation"]["positive_prefix"]
        pose   = frame.get(f"{char_name}_pose", "")
        expr   = frame.get(f"{char_name}_expression", "")
        char_block = prefix
        if pose:
            char_block += f", {pose}"
        if expr:
            char_block += f", facial expression: {expr}"
        char_blocks.append(char_block)

    # Explicit table mention when Xpel is present (Xpel ALWAYS stands on table)
    xpel_table = ""
    if "Xpel" in frame["characters_present"]:
        xpel_table = (
            "XPEL supplement box character is standing upright on the white laboratory table "
            "in the left foreground, the table is clearly visible in the shot, "
            "XPEL character is at approximately waist height relative to MrWilly"
        )

    camera = frame.get("camera_angle", "medium shot, eye level, slight low angle")
    chars_in_shot = " and ".join(frame["characters_present"])

    positive = (
        f"{style['generation_prefix']}, "
        f"{background['generation_prompt']}, "
        f"white laboratory table visible in foreground, "
        f"{'. '.join(char_blocks)}, "
        f"{xpel_table}, "
        f"both {chars_in_shot} visible in the same frame, "
        f"camera: {camera}, "
        f"full scene composition, all characters fully visible, "
        f"no cropping of characters, wideshot showing full environment"
    ).replace(", ,", ",").replace("  ", " ")

    # Merge all negatives
    negatives = set()
    negatives.update(style["negative"].split(", "))
    for char_name in frame["characters_present"]:
        c = load_character(char_name)
        negatives.update(c["generation"]["negative"].split(", "))
    if "negative" in background:
        negatives.update(background["negative"].split(", "))
    negatives.update([
        "missing character", "only one character", "cropped character",
        "floating character", "missing table", "no table",
        "watermark", "text overlay", "logo on screen",
        "face distortion", "body distortion", "extra limbs",
    ])

    return positive, ", ".join(sorted(negatives))


# ══════════════════════════════════════════════════════════════════════════════
#  FAL TEXT-TO-IMAGE GENERATION  (fal-ai/flux-pro full scene composition)
# ══════════════════════════════════════════════════════════════════════════════

def generate_frame_t2i(positive_prompt: str, negative_prompt: str, seed: int | None = None) -> bytes:
    """
    Generate a full scene frame from text description only.
    Uses fal-ai/flux-pro for maximum quality composition.
    9:16 portrait aspect ratio to match Kling video output.
    """
    print("  [FAL] Running flux-pro text-to-image (full scene composition)...")
    args: dict = {
        "prompt":              positive_prompt,
        "negative_prompt":     negative_prompt,
        "image_size":          "portrait_16_9",
        "num_inference_steps": 35,
        "guidance_scale":      3.5,
        "num_images":          1,
        "output_format":       "png",
        "enable_safety_checker": False,
    }
    if seed is not None:
        args["seed"] = seed

    result = fal_client.subscribe("fal-ai/flux-pro", arguments=args, with_logs=False)

    images = result.get("images") or [result.get("image")]
    if not images or not images[0]:
        raise RuntimeError(f"No image in FAL t2i response: {result}")

    img_url = images[0]["url"] if isinstance(images[0], dict) else images[0]
    print(f"  [FAL] Done → {img_url}")
    r = requests.get(img_url, timeout=60)
    r.raise_for_status()
    return r.content


# ══════════════════════════════════════════════════════════════════════════════
#  FAL GENERATION  (kontext — edits an existing image)
# ══════════════════════════════════════════════════════════════════════════════

def generate_frame(seed_image: Path, positive_prompt: str, negative_prompt: str) -> bytes:
    """Call fal-ai/flux-pro/kontext and return raw image bytes."""
    print("  [FAL] Uploading seed image...")
    image_url = fal_client.upload_file(str(seed_image))

    print("  [FAL] Running flux-pro/kontext...")
    result = fal_client.subscribe(
        "fal-ai/flux-pro/kontext",
        arguments={
            "image_url": image_url,
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "guidance_scale": 3.5,
            "num_inference_steps": 30,
            "output_format": "png",
        },
        with_logs=False,
    )

    images = result.get("images") or [result.get("image")]
    if not images or not images[0]:
        raise RuntimeError(f"No image in FAL response: {result}")

    img_url = images[0]["url"] if isinstance(images[0], dict) else images[0]
    print(f"  [FAL] Done → {img_url}")
    r = requests.get(img_url, timeout=60)
    r.raise_for_status()
    return r.content


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN FLOW
# ══════════════════════════════════════════════════════════════════════════════

def process_scene(
    scene_json: Path,
    seed_override: str | None = None,
    rejection_note: str | None = None,
    max_auto_retries: int = 2,
) -> Path | None:
    """Full pipeline for one scene. Returns pending frame path or None."""
    print(f"\n{'═'*60}")
    print(f" FRAME GENERATOR — {scene_json.stem}")
    print(f"{'═'*60}")

    scene          = load_scene(scene_json)
    campaign       = scene["campaign"]
    scene_id       = scene["id"]
    chars_present  = scene["frame"]["characters_present"]
    primary_char   = chars_present[0]
    character      = load_character(primary_char)
    style          = load_style(character["style_ref"])
    background     = load_background(scene["frame"]["background"])
    drift_limit    = character.get("drift_threshold", 0.25)
    kling_seed     = scene.get("kling_settings", {}).get("seed")

    # Auto-route: multi-character scenes use text-to-image (t2i) for full composition.
    # Single-character scenes use kontext to edit a seed pose image.
    use_t2i = len(chars_present) > 1

    print(f"  Characters:  {chars_present}")
    print(f"  Mode:        {'text-to-image (full scene)' if use_t2i else 'kontext (pose edit)'}")
    print(f"  Drift limit: {drift_limit}")

    pending_dir = PROJ_ROOT / "frames" / campaign / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    out_path  = pending_dir / f"{scene_id}.png"
    reference = PROJ_ROOT / character["anchor_images"]["front"]
    attempt   = 0

    if use_t2i:
        # ── TEXT-TO-IMAGE: generate full scene from scratch ────────────────
        positive, negative = build_t2i_prompt(scene, style, background)
        print(f"\n  [PROMPT] {positive[:220]}...")

        while attempt <= max_auto_retries:
            attempt += 1
            if attempt > 1:
                print(f"\n  [AUTO-RETRY {attempt-1}/{max_auto_retries}]")
                if rejection_note:
                    positive = positive.rstrip(".") + f". CORRECTION: {rejection_note}."
            try:
                raw = generate_frame_t2i(positive, negative, seed=kling_seed)
            except Exception as e:
                print(f"  [ERROR] FAL t2i failed: {e}")
                return None
            out_path.write_bytes(raw)
            print(f"  [SAVED] {out_path.name}")
            # t2i generates a full multi-character scene — SSIM vs a single
            # character reference photo is meaningless; skip drift and send
            # straight to manual review.
            print(f"  [DRIFT] Skipping drift check for t2i (full scene composition)")
            break
    else:
        # ── KONTEXT: edit seed image (single character) ────────────────────
        seed_image = select_seed_image(
            primary_char,
            seed_override or scene["frame"].get("seed_frame"),
        )
        positive, negative = build_kontext_prompt(scene, character, style, background, rejection_note)
        print(f"\n  [PROMPT] {positive[:220]}...")

        while attempt <= max_auto_retries:
            attempt += 1
            if attempt > 1:
                print(f"\n  [AUTO-RETRY {attempt-1}/{max_auto_retries}]")
            try:
                raw = generate_frame(seed_image, positive, negative)
            except Exception as e:
                print(f"  [ERROR] FAL kontext failed: {e}")
                return None
            out_path.write_bytes(raw)
            print(f"  [SAVED] {out_path.name}")
            if reference.exists():
                score = drift_score(out_path, reference)
                status = "✅ PASSED" if score >= drift_limit else "❌ FAILED"
                print(f"  [DRIFT] {score:.3f}  {status}  (threshold: {drift_limit})")
                if score >= drift_limit:
                    break
                if attempt > max_auto_retries:
                    print(f"  [DRIFT] Max retries — sending to manual review")
            else:
                print(f"  [DRIFT] Skipping — front.png not found")
                break

    print(f"\n  → {out_path}")
    print(f"  Next: python scripts/approval_gate.py --campaign {campaign}")
    return out_path


def process_campaign(campaign: str, **kwargs) -> None:
    scenes_dir = PROJ_ROOT / "scenes" / campaign
    if not scenes_dir.exists():
        sys.exit(f"ERROR: No scenes dir: {scenes_dir}")

    scene_files = sorted(scenes_dir.glob("scene_*.json"))
    if not scene_files:
        sys.exit(f"ERROR: No scene JSON files in {scenes_dir}")

    # Load any existing rejections so notes are auto-injected
    rejections_path = PROJ_ROOT / "frames" / campaign / "rejections.json"
    rejections = json.loads(rejections_path.read_text()) if rejections_path.exists() else {}

    approved_dir = PROJ_ROOT / "frames" / campaign / "approved"

    print(f"\n{'═'*60}")
    print(f" CAMPAIGN: {campaign}  ({len(scene_files)} scenes)")
    if rejections:
        print(f" Rejections queued: {list(rejections.keys())}")
    print(f"{'═'*60}\n")

    results = []
    for sf in scene_files:
        scene_id = sf.stem

        # Skip if already approved — don't waste API calls
        if (approved_dir / f"{scene_id}.png").exists():
            print(f"  [SKIP] {scene_id} — already in approved/")
            results.append((scene_id, "⏭  already approved"))
            continue

        # Inject rejection note if one exists for this scene
        scene_kwargs = dict(kwargs)
        if scene_id in rejections:
            note = rejections[scene_id]["note"]
            scene_kwargs["rejection_note"] = note
            print(f"  [NOTE] {scene_id} — injecting rejection note: \"{note}\"")

        result = process_scene(sf, **scene_kwargs)
        results.append((sf.stem, "✅ pending" if result else "❌ failed"))

    print(f"\n{'═'*60}")
    print(" CAMPAIGN SUMMARY")
    print(f"{'═'*60}")
    for sid, status in results:
        print(f"  {sid}  {status}")
    print(f"\n  Run: python scripts/approval_gate.py --campaign {campaign}")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ProBodyForLife — Frame Generator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scene",    type=Path, help="Path to scene_XX.json blueprint")
    group.add_argument("--campaign", type=str,  help="Campaign name — generates all scenes")
    parser.add_argument("--seed-pose",      type=str, default=None)
    parser.add_argument("--rejection-note", type=str, default=None)
    parser.add_argument("--max-retries",    type=int, default=2)
    args = parser.parse_args()

    kwargs = dict(
        seed_override=args.seed_pose,
        rejection_note=args.rejection_note,
        max_auto_retries=args.max_retries,
    )

    if args.scene:
        process_scene(args.scene, **kwargs)
    else:
        process_campaign(args.campaign, **kwargs)


if __name__ == "__main__":
    main()
