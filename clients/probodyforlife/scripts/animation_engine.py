#!/usr/bin/env python3
"""
animation_engine.py
====================
Layer 5 — Animation Engine (Kling Cinematic Director)

WHAT IT DOES:
  - Reads approved frame from frames/[campaign]/approved/scene_XX.png
  - Reads scene blueprint from scenes/[campaign]/scene_XX.json
  - Reads character profiles for motion constraints
  - Reads style.json for Pixar rendering parameters
  - Builds a surgical cinematic Kling prompt (NOT a vague description)
  - Specifies EXACTLY: camera movement, character motion, what does NOT move
  - Sends to fal-ai/kling-video/v2.1 with locked seeds per scene
  - Saves animated clip to clips/[campaign]/animated/scene_XX.mp4

KLING PROMPT STRUCTURE (always this order):
  1. Style prefix (from style.json)
  2. Character description (from character profile)
  3. Background description (from background.json)
  4. CAMERA: exact movement instruction
  5. CHARACTER MOTION: exactly what moves and how
  6. DO NOT MOVE: explicit list of static elements
  7. Technical: motion_bucket_id, cfg_scale, seed, duration

USAGE:
  python scripts/animation_engine.py --scene scenes/xpel_ad/scene_01.json
  python scripts/animation_engine.py --campaign xpel_ad --all

SYSTEM RULES (see SYSTEM_POLICY.md):
  - ALWAYS use locked seed from scene blueprint — reproducible results
  - NEVER use motion_bucket_id > 20 — high values cause chaos
  - ALWAYS include DO NOT MOVE section — prevents background drift
  - NEVER run without an approved frame in frames/[campaign]/approved/
  - Animated clips go to clips/[campaign]/animated/ ONLY — never directly to assembly
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import fal_client
import requests
from dotenv import load_dotenv

# ── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_ROOT  = SCRIPT_DIR.parent          # clients/probodyforlife/

def _find_env() -> None:
    d = PROJ_ROOT
    for _ in range(6):
        if (d / ".env").exists():
            load_dotenv(d / ".env")
            return
        d = d.parent
    load_dotenv()

_find_env()

# ── scene / asset loaders ─────────────────────────────────────────────────────

def load_scene(path: Path) -> dict:
    return json.loads(path.read_text())

def load_background(rel_path: str) -> dict:
    return json.loads((PROJ_ROOT / rel_path).read_text())

# ── Kling prompt builder ──────────────────────────────────────────────────────

# System-level negative — always injected (prevents AI slop)
_SYSTEM_NEGATIVE = (
    "no spinning, no golden particles, no light bursts, no glowing aura, "
    "no energy waves, no electricity, no face morphing, no teleportation, "
    "no lens flare, no flickering, no speed lines, no motion blur artifacts, "
    "no text, no watermarks"
)

def build_kling_prompt(scene: dict, background: dict) -> tuple[str, str]:
    """
    Returns (positive_prompt, negative_prompt) for Kling.
    Follows the KLING PROMPT STRUCTURE from the module docstring.
    """
    cm   = scene["camera_motion"]
    chm  = scene["character_motion"]
    chars = scene["frame"]["characters_present"]

    # 1. Style prefix
    style_prefix = (
        "Pixar 3D animated feature film, The Incredibles art style, "
        "subsurface scattering, physically based rendering, "
        "warm cinematic lighting"
    )

    # 2. Background anchor
    bg_desc = background.get("generation_prompt", "")
    bg_short = bg_desc[:120].split(",")[0] if bg_desc else "pharmaceutical laboratory corridor"

    # 3. Camera movement
    camera = (
        f"CAMERA: {cm['movement']}, starting {cm['start']}, ending {cm['end']}, "
        f"speed {cm['speed']}"
    )

    # 4. Character motion — each character listed explicitly
    char_motions = []
    for char in chars:
        motion = chm.get(char, "subtle idle breathing, no large movement")
        char_motions.append(f"{char}: {motion}")
    character_motion = "CHARACTER MOTION: " + "; ".join(char_motions)

    # 5. Static lock — everything not moving should be explicit
    static_items = ["background walls", "floor", "ceiling lights"]
    if scene["frame"].get("Xpel_present") or "Xpel" in chars:
        static_items.append("XPEL supplement box stays on table, does not float or move away")
    do_not_move = "DO NOT MOVE: " + ", ".join(static_items)

    positive = ". ".join([style_prefix, bg_short, camera, character_motion, do_not_move])

    negative = _SYSTEM_NEGATIVE

    return positive, negative


# ── FAL upload + Kling call ───────────────────────────────────────────────────

def upload_image(image_path: Path) -> str:
    """Upload local image to fal CDN, return URL."""
    print(f"  [FAL] Uploading {image_path.name}...")
    url = fal_client.upload_file(str(image_path))
    print(f"  [FAL] Uploaded → {url}")
    return url


def animate_frame(image_url: str, positive: str, negative: str, kling: dict) -> bytes:
    """Call fal-ai/kling-video/v2.1/standard/image-to-video, return raw mp4 bytes."""
    print("  [FAL] Submitting to Kling v2.1...")
    args = {
        "image_url":       image_url,
        "prompt":          positive,
        "negative_prompt": negative,
        "duration":        str(kling.get("duration", 5)),
        "aspect_ratio":    kling.get("aspect_ratio", "9:16"),
        "cfg_scale":       kling.get("cfg_scale", 0.5),
    }
    if kling.get("seed"):
        args["seed"] = kling["seed"]

    result = fal_client.subscribe(
        "fal-ai/kling-video/v2.1/standard/image-to-video",
        arguments=args,
        with_logs=False,
    )

    video = result.get("video") or {}
    video_url = video.get("url") if isinstance(video, dict) else video
    if not video_url:
        raise RuntimeError(f"No video URL in Kling response: {result}")

    print(f"  [FAL] Done → {video_url}")
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    return r.content


# ── scene processor ───────────────────────────────────────────────────────────

def process_scene(scene_json: Path, use_originals: bool = False) -> Path | None:
    print(f"\n{'═'*60}")
    print(f" ANIMATION ENGINE — {scene_json.stem}")
    print(f"{'═'*60}")

    scene    = load_scene(scene_json)
    campaign = scene["campaign"]
    scene_id = scene["id"]
    kling    = scene.get("kling_settings", {})
    bg       = load_background(scene["frame"]["background"])

    # Resolve source frame
    if use_originals:
        # Use seed_frame (frame_1-7.png) directly, bypassing approved/
        seed_rel = scene["frame"].get("seed_frame")
        if not seed_rel:
            print(f"  [SKIP] No seed_frame in scene, cannot use originals")
            return None
        frame_path = PROJ_ROOT / seed_rel
    else:
        frame_path = PROJ_ROOT / scene["frame"]["file"]

    if not frame_path.exists():
        print(f"  [SKIP] Frame not found: {frame_path}")
        return None

    print(f"  Source : {frame_path.name}  ({'original' if use_originals else 'approved'})")
    print(f"  Seed   : {kling.get('seed')}   Duration: {kling.get('duration')}s")

    # Build prompt
    positive, negative = build_kling_prompt(scene, bg)
    print(f"  [PROMPT] {positive[:200]}...")

    # Output path
    clips_dir = PROJ_ROOT / "clips" / campaign / "animated"
    clips_dir.mkdir(parents=True, exist_ok=True)
    out_path = clips_dir / f"{scene_id}.mp4"

    # Upload + animate
    try:
        image_url = upload_image(frame_path)
        raw = animate_frame(image_url, positive, negative, kling)
    except Exception as e:
        print(f"  [ERROR] Kling failed: {e}")
        return None

    out_path.write_bytes(raw)
    print(f"  [SAVED] {out_path}")
    return out_path


# ── campaign runner ───────────────────────────────────────────────────────────

def process_campaign(campaign: str, use_originals: bool = False) -> None:
    scenes_dir  = PROJ_ROOT / "scenes" / campaign
    scene_files = sorted(scenes_dir.glob("scene_*.json"))
    if not scene_files:
        sys.exit(f"ERROR: No scene JSONs in {scenes_dir}")

    mode = "ORIGINALS (frame_1-7.png)" if use_originals else "APPROVED frames"
    print(f"\n{'═'*60}")
    print(f" CAMPAIGN: {campaign}  ({len(scene_files)} scenes)")
    print(f" Mode: {mode}")
    print(f"{'═'*60}")

    results = []
    for sf in scene_files:
        path = process_scene(sf, use_originals=use_originals)
        results.append((sf.stem, "✅ done" if path else "❌ failed"))

    print(f"\n{'═'*60}")
    print(f" ANIMATION SUMMARY")
    print(f"{'═'*60}")
    for scene_id, status in results:
        print(f"  {scene_id}  {status}")
    print(f"\n  Clips saved to: clients/{campaign}/clips/{campaign}/animated/")
    print(f"  Next: python scripts/assembly_engine.py --campaign {campaign}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Animate approved (or original) frames with Kling v2.1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--campaign", help="Animate all scenes in a campaign")
    group.add_argument("--scene",    help="Animate a single scene JSON path")
    parser.add_argument(
        "--use-originals",
        action="store_true",
        default=False,
        help="Use original frame_1-7.png instead of requiring approved frames",
    )
    args = parser.parse_args()

    if args.campaign:
        process_campaign(args.campaign, use_originals=args.use_originals)
    else:
        process_scene(Path(args.scene), use_originals=args.use_originals)
