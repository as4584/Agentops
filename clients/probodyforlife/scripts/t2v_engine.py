#!/usr/bin/env python3
"""
t2v_engine.py
=============
Approach B — Pure text-to-video via Kling v2.1.

No seed images. No kontext. No frame editing.
7 fully self-describing prompts → 7 unified clips.

Unity is enforced by 3 identical anchors repeated in every prompt:
  WORLD    — same lab, same shelves, same table, same lighting
  MRWILLY  — exact same character description in every scene
  XPEL     — exact same character description in every scene

Usage:
  python scripts/t2v_engine.py --all
  python scripts/t2v_engine.py --scene 1
  python scripts/t2v_engine.py --scene 3 --scene 5
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import fal_client
import requests
from dotenv import load_dotenv

# ── env ───────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_ROOT  = SCRIPT_DIR.parent

def _find_env() -> None:
    d = PROJ_ROOT
    for _ in range(6):
        if (d / ".env").exists():
            load_dotenv(d / ".env")
            return
        d = d.parent
    load_dotenv()

_find_env()

# ── locked anchors ────────────────────────────────────────────────────────────

STYLE = (
    "Pixar 3D animated feature film quality. The Incredibles character art style. "
    "Render farm quality. Subsurface scattering skin. Physically based rendering. "
    "Rich saturated colors. Warm soft key light from upper left. 24fps smooth fluid motion."
)

WORLD = (
    "WORLD: Pharmaceutical laboratory corridor. Long hallway perspective. "
    "Floor to ceiling shelves on both sides lined with colorful supplement bottles glowing "
    "under blue neon strip lights. White polished floor reflecting blue light. "
    "Clean white ceiling with recessed panel lighting. "
    "White low table in foreground left of frame. Warm blue and white color palette throughout."
)

MRWILLY = (
    "MrWilly: Extremely muscular bald Latino male late 40s. "
    "Light-medium warm skin tone. Light beard stubble. Strong jaw. High cheekbones. "
    "Thick arms. Broad stocky chest. "
    "Wearing white MHP basketball jersey number 97 with gold and navy trim. "
    "Navy blue shorts. Blue sneakers."
)

XPEL = (
    "Xpel: MHP XPEL Diuretic supplement box come to life as a Pixar character. "
    "Navy blue box body. Bright yellow XPEL text clearly readable on front face. "
    "MHP logo top left. Big round cartoon eyes. Small cartoon mouth. "
    "Tiny stubby arms with white gloves. Small round cartoon legs and feet. "
    "Standing on the white table left of frame."
)

FORBIDDEN = (
    "FORBIDDEN: No spinning. No golden particles. No light bursts. No glowing aura. "
    "No energy waves. No electricity effects. No random characters appearing. "
    "No face morphing. No background drift. No camera shake. No watermarks. No text overlays."
)

# ── scene definitions ─────────────────────────────────────────────────────────

SCENES = [
    {
        "id": "scene_01",
        "seed": 1001,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "MrWilly alone, curious, pointing toward table",
        "scene_prompt": (
            "CHARACTER: {MRWILLY} "
            "Standing center frame. One arm extended pointing down toward the white table. "
            "Curious expression. One eyebrow raised. Slight smirk. Mouth slightly open. "
            "CAMERA: Starts wide slight low angle looking up at character. "
            "Slow intentional push in. Ends medium shot eye level. Smooth and deliberate. "
            "MOTION: One natural breath cycle, chest rises and falls. "
            "Weight shifts slowly to left foot. Pointing hand lifts 2 inches naturally. "
            "Head tilts 5 degrees left. One natural eye blink. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights, table."
        ),
    },
    {
        "id": "scene_02",
        "seed": 1002,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "MrWilly + Xpel first meeting, both surprised and excited",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing right of frame. "
            "Leaning back slightly. Both arms open wide in amazed gesture. "
            "Big surprised smile. Eyebrows raised high. "
            "{XPEL} "
            "Big round cartoon eyes wide open with excitement. "
            "Small cartoon mouth in huge smile. "
            "Tiny arms stretched wide open. Slight bounce on feet. "
            "CAMERA: Medium two-shot framing both characters. "
            "Very slow barely perceptible zoom out to reveal full scene. "
            "Smooth and cinematic. "
            "MOTION: MrWilly arms open wider gradually. Single natural blink. "
            "Chest breathing visible. "
            "Xpel tiny arms wave side to side enthusiastically. "
            "Slight bounce on feet. Absolutely no spinning. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights."
        ),
    },
    {
        "id": "scene_03",
        "seed": 1003,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "MrWilly skeptical arms crossed, Xpel explaining with raised finger",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing right of frame. "
            "Both arms crossed over chest. Skeptical expression. "
            "One eyebrow raised. Slight smirk. Chin slightly dipped. "
            "Leaning weight back on right foot. "
            "{XPEL} "
            "Big round cartoon eyes animated and expressive. "
            "Small cartoon mouth open mid-explanation. "
            "One tiny arm raised with finger pointing upward in explanation gesture. "
            "Body leaning slightly toward MrWilly. "
            "CAMERA: Slow deliberate push in tightening the two-shot. "
            "Builds conversational tension. Smooth and cinematic. "
            "MOTION: MrWilly arms cross tighter slowly. Chin dips further skeptically. "
            "One natural blink. "
            "Xpel finger points up. Tiny body leans toward MrWilly. "
            "Slight excited bounce while explaining. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights, table."
        ),
    },
    {
        "id": "scene_04",
        "seed": 1004,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "Xpel proud puffed chest, MrWilly impressed wide smile",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing right of frame. "
            "Fully upright. Both arms open wide in impressed wow gesture. "
            "Big genuine smile. Eyebrows raised. Nodding slowly. "
            "{XPEL} "
            "Big round cartoon eyes squinted happily in proud expression. "
            "Small cartoon mouth in confident smile. "
            "One tiny arm pointing back at itself proudly. "
            "Chest puffed out confidently. Small foot shuffle. "
            "CAMERA: Very slow pan left to right from Xpel to MrWilly, "
            "settles centered on both. Smooth and deliberate. "
            "MOTION: MrWilly slow impressed nod. Arms open wider. Visible natural breathing. "
            "Xpel tiny arm gestures enthusiastically. Proud chest stays puffed. "
            "Absolutely zero particles or glow effects. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights."
        ),
    },
    {
        "id": "scene_05",
        "seed": 1005,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "MrWilly leaning forward suspicious, Xpel arms up nervous",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing right of frame. "
            "Leaning forward toward Xpel. Eyes narrowed suspiciously. "
            "One hand moving slowly to chin. Weight shifting forward onto front foot. "
            "{XPEL} "
            "Big round cartoon eyes wide with nervousness. "
            "Small cartoon mouth in anxious expression. "
            "Both tiny arms slowly rising in nervous surrender gesture. "
            "Body shrinking slightly. Small legs shuffling nervously. "
            "CAMERA: Slow deliberate push in toward MrWilly building tension. "
            "Slightly tighter than previous scene. Smooth and cinematic. "
            "MOTION: MrWilly leans forward gradually and slowly. "
            "Hand moves to chin. Eyes narrow. One eyebrow lifts slowly. "
            "Xpel arms rise slowly in nervous surrender. "
            "Body shrinks slightly. Nervous subtle sway. No effects whatsoever. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights, table."
        ),
    },
    {
        "id": "scene_06",
        "seed": 1006,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "Xpel honest arms up, MrWilly slow approving nod",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing right of frame. "
            "Arms crossed. Slow approving nod. "
            "Warm understanding expression. Natural breathing visible. "
            "{XPEL} "
            "Big round cartoon eyes sincere and honest. "
            "Small cartoon mouth in earnest expression. "
            "Both tiny arms raised up in honest open surrender. "
            "Slight nervous sway left to right. "
            "CAMERA: Slow gentle drift toward Xpel centering product in frame. "
            "Warm and intimate feeling. Smooth cinematic movement. "
            "MOTION: MrWilly slow approving nod. Arms stay crossed. "
            "Natural breathing. One blink. "
            "Xpel honest arms stay up. Slight nervous sway left and right slowly. "
            "No glow, no aura, no shimmer, no effects. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights, table."
        ),
    },
    {
        "id": "scene_07",
        "seed": 1007,
        "duration": "5",
        "aspect_ratio": "9:16",
        "cfg_scale": 0.5,
        "description": "Hero shot — MrWilly holds Xpel up to camera triumphantly",
        "scene_prompt": (
            "CHARACTERS: {MRWILLY} Standing center frame facing camera directly. "
            "Big confident warm smile. "
            "One arm raised holding Xpel box up toward camera triumphantly. "
            "Other arm relaxed at side. Chest expanded confidently. "
            "{XPEL} "
            "Navy blue box body. Bright yellow XPEL text facing camera clearly readable. "
            "Big round cartoon eyes looking directly at camera happily. "
            "Small cartoon mouth in big happy smile. "
            "Tiny arms waving at camera. Being held up by MrWilly's hand. "
            "CAMERA: Moderate push in from medium to medium-close with slight upward tilt. "
            "Hero shot. Builds to triumphant finale. Smooth and cinematic. "
            "MOTION: MrWilly confident chest expansion. "
            "One slow proud nod directly at camera. "
            "Arm holding Xpel stays steady and raised. "
            "Xpel tiny arms wave at camera happily. Slight excited wiggle. "
            "No spinning. Pure triumph. "
            "DO NOT MOVE: Background shelves, floor, ceiling lights."
        ),
    },
]

# ── prompt builder ────────────────────────────────────────────────────────────

def build_prompt(scene: dict) -> tuple[str, str]:
    scene_text = scene["scene_prompt"].replace("{MRWILLY}", MRWILLY).replace("{XPEL}", XPEL)
    positive = " ".join([STYLE, WORLD, scene_text])
    negative = FORBIDDEN
    return positive, negative


# ── Kling text-to-video ───────────────────────────────────────────────────────

def generate_clip(scene: dict, out_path: Path) -> Path | None:
    positive, negative = build_prompt(scene)

    print(f"\n{'═'*60}")
    print(f" T2V — {scene['id']}  ({scene['description']})")
    print(f"{'═'*60}")
    print(f"  Seed: {scene['seed']}  Duration: {scene['duration']}s  Ratio: {scene['aspect_ratio']}")
    print(f"  Prompt ({len(positive)} chars): {positive[:180]}...")

    args = {
        "prompt":          positive,
        "negative_prompt": negative,
        "duration":        scene["duration"],
        "aspect_ratio":    scene["aspect_ratio"],
        "cfg_scale":       scene["cfg_scale"],
        "seed":            scene["seed"],
    }

    try:
        print("  [FAL] Submitting to fal-ai/kling-video/v1/standard/text-to-video ...")
        result = fal_client.subscribe(
            "fal-ai/kling-video/v1/standard/text-to-video",
            arguments=args,
            with_logs=False,
        )
    except Exception as e:
        print(f"  [ERROR] Kling t2v failed: {e}")
        return None

    video = result.get("video") or {}
    video_url = video.get("url") if isinstance(video, dict) else video
    if not video_url:
        print(f"  [ERROR] No video URL in response: {result}")
        return None

    print(f"  [FAL] Done → {video_url}")
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    print(f"  [SAVED] {out_path}  ({len(r.content) // 1024} KB)")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate XPEL ad clips via Kling v2.1 text-to-video")
    parser.add_argument("--all",   action="store_true", help="Generate all 7 scenes")
    parser.add_argument("--scene", type=int, action="append", metavar="N", help="Scene number(s) to generate (1-7)")
    args = parser.parse_args()

    if not args.all and not args.scene:
        parser.print_help()
        sys.exit(1)

    scenes_to_run = SCENES if args.all else [s for s in SCENES if int(s["id"].split("_")[1]) in args.scene]

    clips_dir = PROJ_ROOT / "clips" / "xpel_ad" / "t2v"
    results = []

    for scene in scenes_to_run:
        out = clips_dir / f"{scene['id']}.mp4"
        path = generate_clip(scene, out)
        results.append((scene["id"], "✅ done" if path else "❌ failed"))

    print(f"\n{'═'*60}")
    print(f" SUMMARY")
    print(f"{'═'*60}")
    for sid, status in results:
        print(f"  {sid}  {status}")
    print(f"\n  Clips: {clips_dir}")
