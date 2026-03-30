#!/usr/bin/env python3
"""
Xpel Ad Campaign Video Generator
==================================
Orchestrates the full pipeline for the xpel_ad campaign:

  1. Create / verify Soul IDs for Xpel and MrWilly
  2. Generate one video per scene (7 scenes)
  3. Optionally poll each job until complete
  4. Write results to output/xpel_ad/results.json

Prerequisites
-------------
  Higgsfield MCP server must be running:
    cd /root/studio/testing/Agentop
    python -m backend.mcp.higgsfield_playwright_server

  Authenticated session must be restored first:
    curl -s -X POST http://127.0.0.1:8812/tools/hf_login | python3 -m json.tool

Usage
-----
  # Full pipeline (creates Soul IDs + generates all 7 scenes)
  python scripts/generate_xpel_ad.py

  # Skip Soul ID creation (if they already exist in the DB)
  python scripts/generate_xpel_ad.py --skip-soul-ids

  # Generate specific scenes only
  python scripts/generate_xpel_ad.py --scenes 1,3,5

  # Create Soul IDs only (no video generation)
  python scripts/generate_xpel_ad.py --soul-ids-only

  # Poll all submitted jobs until complete (run after generation)
  python scripts/generate_xpel_ad.py --poll-only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MCP_BASE = "http://127.0.0.1:8812"
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients/probodyforlife"
SCENES_DIR = CLIENT_DIR / "scenes/xpel_ad"
VG_DIR = CLIENT_DIR / "VideoGenerator"
RESULTS_FILE = PROJECT_ROOT / "output/xpel_ad/results.json"

# Character configs. Xpel uses ONLY approved_poses/ — diuretic/front.png is
# excluded because it contains the wrong reference image.
CHARACTERS: dict[str, dict[str, str]] = {
    "char_xpel": {
        "name": "Xpel",
        "image_folder": "clients/probodyforlife/VideoGenerator/characters/Xpel/diuretic/approved_poses",
        "profile": str(VG_DIR / "characters/Xpel/diuretic/profile.json"),
    },
    "char_mrwilly": {
        "name": "MrWilly",
        "image_folder": "clients/probodyforlife/VideoGenerator/characters/MrWilly/approved_poses",
        "profile": str(VG_DIR / "characters/MrWilly/profile.json"),
    },
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str, timeout: int = 30) -> dict:
    resp = requests.get(f"{MCP_BASE}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict, timeout: int = 300) -> dict:
    resp = requests.post(f"{MCP_BASE}{path}", json=payload, timeout=timeout)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} from {MCP_BASE}{path}: {resp.text[:400]}")
    return resp.json()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / "clients/probodyforlife" / str(path)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def build_prompt(scene: dict, char_profiles: dict[str, dict]) -> str:
    """
    Build a Higgsfield-compatible text prompt from a scene blueprint JSON.
    Combines:  art style + background + each character's generation prefix,
               pose, expression + camera motion.
    """
    frame = scene.get("frame", {})

    # Background
    bg_json = _load_json(frame.get("background", ""))
    bg_prompt = bg_json.get(
        "generation_prompt",
        "pharmaceutical laboratory corridor, blue neon supplement shelves, "
        "clean white walls and floor, white table in foreground",
    )

    parts: list[str] = [
        "Pixar 3D animated feature film render, The Incredibles art style",
        bg_prompt,
    ]

    # Per-character descriptions
    char_motion = scene.get("character_motion", {})
    for char in frame.get("characters_present", []):
        profile = char_profiles.get(char, {})
        gen = profile.get("generation", {})
        prefix = gen.get("positive_prefix", "")

        if char == "Xpel":
            pose = frame.get("Xpel_pose", "")
            expr = frame.get("Xpel_expression", "")
            motion = char_motion.get("Xpel", "")
            desc = f"{prefix}, standing on white table in foreground"
            if pose:
                desc += f", {pose}"
            if expr:
                desc += f", expression: {expr}"
            if motion:
                desc += f", {motion}"
            parts.append(desc)

        elif char == "MrWilly":
            pose = frame.get("MrWilly_pose", "")
            expr = frame.get("MrWilly_expression", "")
            motion = char_motion.get("MrWilly", "")
            desc = prefix
            if pose:
                desc += f", {pose}"
            if expr:
                desc += f", expression: {expr}"
            if motion:
                desc += f", {motion}"
            parts.append(desc)

    # Camera
    cam = scene.get("camera_motion", {})
    cam_angle = frame.get("camera_angle", "")
    cam_move = cam.get("movement", "")
    cam_speed = cam.get("speed", "")
    cam_desc = " — ".join(p for p in [cam_angle, cam_move, cam_speed] if p)
    if cam_desc:
        parts.append(cam_desc)

    return ", ".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def check_server() -> dict:
    try:
        return _get("/health")
    except Exception as e:
        print(f"\nERROR: MCP server not reachable at {MCP_BASE}")
        print("  Start it with:")
        print("    cd /root/studio/testing/Agentop")
        print("    python -m backend.mcp.higgsfield_playwright_server")
        sys.exit(1)


def verify_session() -> str:
    result = _post("/tools/hf_login", {})
    session = result.get("session", "unknown")
    print(f"  Session: {session} — {result.get('url', '')}")
    if session not in ("restored", "ok"):
        print("  WARNING: Session may not be authenticated. Run login manually if uploads fail.")
    return session


def create_soul_ids(model_preference: str = "auto") -> dict[str, Any]:
    """Create Soul IDs for both characters. Returns {char_name: result_dict}."""
    outputs: dict[str, Any] = {}
    for char_id, config in CHARACTERS.items():
        name = config["name"]
        print(f"\n  [{name}] uploading from {config['image_folder']} ...")
        try:
            result = _post("/tools/hf_create_soul_id", {
                "character_id": char_id,
                "character_name": name,
                "image_folder": config["image_folder"],
                "model_preference": model_preference,
            })
            outputs[name] = result
            status = result.get("soul_id_status", "?")
            url = result.get("soul_id_url", "n/a")
            imgs = result.get("images_uploaded", "?")
            print(f"    → {status} — {url} ({imgs} images uploaded)")
        except Exception as e:
            outputs[name] = {"error": str(e)}
            print(f"    ERROR: {e}")
            if "403" in str(e) or "subscription" in str(e).lower() or "purchase" in str(e).lower():
                print("    HINT: Soul ID requires a paid Higgsfield plan (Starter $15/mo).")
                print("    If you have free credits, check your account tier at https://higgsfield.ai/pricing")
    return outputs


def generate_scene(scene: dict, char_profiles: dict, scene_id: str) -> dict:
    """Submit a single scene for video generation. Returns the result dict."""
    kling = scene.get("kling_settings", {})
    duration = kling.get("duration", 5)

    # Primary character decides which char_id we attach the job to
    dial_char = scene.get("dialogue", {}).get("character", "MrWilly")
    char_id = "char_mrwilly" if dial_char == "MrWilly" else "char_xpel"

    prompt = build_prompt(scene, char_profiles)
    print(f"    Prompt ({len(prompt)} chars): {prompt[:100]}...")

    return _post("/tools/hf_submit_video", {
        "character_id": char_id,
        "soul_id_url": "",          # server fetches this from DB
        "model": "kling_3_0",
        "prompt": prompt,
        "duration_s": duration,
        "campaign": "xpel_ad",
        "scene_id": scene_id,
    })


def poll_job(job_url: str, timeout_s: int = 600) -> dict:
    return _post("/tools/hf_poll_result", {
        "job_url": job_url,
        "timeout_s": timeout_s,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Xpel Ad campaign videos on Higgsfield")
    parser.add_argument("--skip-soul-ids", action="store_true",
                        help="Skip Soul ID creation (use if already in DB)")
    parser.add_argument("--soul-ids-only", action="store_true",
                        help="Only create Soul IDs — skip video generation")
    parser.add_argument("--poll-only", action="store_true",
                        help="Poll existing submitted jobs from results.json — skip generation")
    parser.add_argument("--scenes", default="",
                        help="Comma-separated scene numbers to generate, e.g. '1,3,5' (default: all)")
    parser.add_argument("--model", default="auto",
                        help="Soul ID model preference: 'soul_2', 'soul_1', 'auto' (default: auto)")
    parser.add_argument("--no-poll", action="store_true",
                        help="Submit jobs but do not wait for them to complete")
    args = parser.parse_args()

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    if RESULTS_FILE.exists():
        try:
            results = json.loads(RESULTS_FILE.read_text())
        except Exception:
            pass

    # -----------------------------------------------------------------------
    print("=== Xpel Ad Campaign Pipeline ===\n")

    # Step 1: Server health
    print("Checking MCP server...")
    health = check_server()
    print(f"  ✓ Server OK (playwright={health.get('playwright_available')}, headless={health.get('headless')})")

    # Step 2: Session
    print("\nVerifying Higgsfield session...")
    verify_session()

    # -----------------------------------------------------------------------
    # Soul ID creation
    # -----------------------------------------------------------------------
    if not args.skip_soul_ids and not args.poll_only:
        print("\n--- Soul ID Creation ---")
        soul_results = create_soul_ids(model_preference=args.model)
        results["soul_ids"] = soul_results
        _save(results)

    if args.soul_ids_only:
        print("\nDone (soul-ids-only mode).")
        _report(results)
        return

    # -----------------------------------------------------------------------
    # Load scenes
    # -----------------------------------------------------------------------
    if not args.poll_only:
        scene_files = sorted(SCENES_DIR.glob("scene_*.json"))
        if not scene_files:
            print(f"\nERROR: No scene files found in {SCENES_DIR}")
            sys.exit(1)

        # Filter by --scenes flag
        if args.scenes:
            wanted = {int(s.strip()) for s in args.scenes.split(",") if s.strip().isdigit()}
            scene_files = [f for f in scene_files
                           if int(f.stem.split("_")[1]) in wanted]

        print(f"\n--- Generating {len(scene_files)} scenes ---")

        # Load character profiles for prompt generation
        char_profiles: dict[str, dict] = {}
        for char_id, config in CHARACTERS.items():
            p = Path(config["profile"])
            if p.exists():
                char_profiles[config["name"]] = json.loads(p.read_text())

        scenes_results: dict[str, Any] = results.setdefault("scenes", {})

        for scene_file in scene_files:
            scene = json.loads(scene_file.read_text())
            sid = scene["id"]
            line = scene.get("dialogue", {}).get("line", "")[:70]
            kling = scene.get("kling_settings", {})
            duration = kling.get("duration", "?")
            aspect = kling.get("aspect_ratio", "9:16")

            print(f"\n  [{sid}] {duration}s {aspect} — \"{line}\"")

            # Skip if already submitted/complete
            existing = scenes_results.get(sid, {})
            if existing.get("status") in ("complete", "submitted"):
                print(f"    → Already {existing['status']} — skipping")
                continue

            try:
                submit_result = generate_scene(scene, char_profiles, sid)
                scenes_results[sid] = {
                    "status": "submitted",
                    "job_url": submit_result.get("job_url"),
                    "run_id": submit_result.get("run_id"),
                    "duration_s": duration,
                    "aspect_ratio": aspect,
                    "dialogue": line,
                }
                print(f"    → Submitted (run_id={submit_result.get('run_id')}, url={submit_result.get('job_url')})")
            except Exception as e:
                scenes_results[sid] = {"status": "error", "error": str(e)[:300]}
                print(f"    ERROR: {e}")

            _save(results)
            time.sleep(2)

    # -----------------------------------------------------------------------
    # Poll jobs
    # -----------------------------------------------------------------------
    if not args.no_poll:
        scenes_results = results.get("scenes", {})
        pending = {sid: d for sid, d in scenes_results.items()
                   if d.get("status") == "submitted" and d.get("job_url")}

        if pending:
            print(f"\n--- Polling {len(pending)} submitted jobs ---")
            for sid, data in sorted(pending.items()):
                job_url = data["job_url"]
                print(f"\n  [{sid}] polling {job_url} ...")
                try:
                    poll = poll_job(job_url, timeout_s=600)
                    final_status = poll.get("status", "unknown")
                    result_url = poll.get("result_url")
                    elapsed = poll.get("elapsed_s", 0)
                    scenes_results[sid].update({
                        "status": final_status,
                        "result_url": result_url,
                        "elapsed_s": elapsed,
                    })
                    icon = "✓" if final_status == "complete" else "✗"
                    print(f"    {icon} {final_status} ({elapsed}s) — {result_url or 'no URL'}")
                except Exception as e:
                    print(f"    ERROR polling: {e}")
                    scenes_results[sid]["poll_error"] = str(e)[:200]
                _save(results)

    # -----------------------------------------------------------------------
    _report(results)


def _save(results: dict) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2))


def _report(results: dict) -> None:
    print("\n=== CAMPAIGN REPORT ===")
    soul_ids = results.get("soul_ids", {})
    if soul_ids:
        print("\nSoul IDs:")
        for name, data in soul_ids.items():
            if "error" in data:
                print(f"  ✗ {name}: {data['error'][:80]}")
            else:
                print(f"  ✓ {name}: {data.get('soul_id_status')} — {data.get('soul_id_url', 'n/a')}")

    scenes = results.get("scenes", {})
    if scenes:
        print("\nScenes:")
        for sid, data in sorted(scenes.items()):
            st = data.get("status", "?")
            icon = "✓" if st == "complete" else ("→" if st == "submitted" else "✗")
            detail = data.get("result_url") or data.get("job_url") or data.get("error") or ""
            print(f"  {icon} {sid}: {st} — {str(detail)[:80]}")

    print(f"\nResults file: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
