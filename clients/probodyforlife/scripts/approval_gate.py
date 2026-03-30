#!/usr/bin/env python3
"""
approval_gate.py
=================
Layer 4 — Human Approval Gate

READ SYSTEM_POLICY.md BEFORE EDITING THIS FILE.

Pipeline:
  1. Read all PNGs in frames/[campaign]/pending/
  2. Open each in VS Code, print scene info to terminal
  3. User decision: [A]pprove / [R]eject + note / [S]kip
  4. Approved → frames/[campaign]/approved/
  5. Rejected → logged to frames/[campaign]/rejections.json + frame deleted
  6. frame_generator.py reads rejections.json on next run and auto-injects notes

USAGE:
  python scripts/approval_gate.py --campaign xpel_ad
  python scripts/approval_gate.py --campaign xpel_ad --scene scene_04

SYSTEM RULES (see SYSTEM_POLICY.md):
  - No animation runs until ALL frames for a campaign are in approved/
  - Every decision is logged with timestamp to approval_log.json
  - Rejection notes are injected as correction prompts on next generate run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent

# `code` opens image in VS Code preview tab — best for this environment
IMAGE_VIEWERS = ["code", "eog", "feh", "eom", "display", "xdg-open", "open"]


def open_image(path: Path) -> None:
    """Open image in best available viewer. Always prints absolute path."""
    abs_path = path.resolve()
    print(f"  [IMAGE]  {abs_path}")
    for viewer in IMAGE_VIEWERS:
        found = shutil.which(viewer)
        if found:
            subprocess.Popen(
                [found, str(abs_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
    print(f"  [VIEWER] No viewer found — open the path above manually")


def load_scene(campaign: str, scene_id: str) -> dict | None:
    path = PROJ_ROOT / "scenes" / campaign / f"{scene_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def load_rejections(campaign: str) -> dict:
    path = PROJ_ROOT / "frames" / campaign / "rejections.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_rejections(campaign: str, data: dict) -> None:
    path = PROJ_ROOT / "frames" / campaign / "rejections.json"
    path.write_text(json.dumps(data, indent=2))


def load_log(campaign: str) -> list:
    path = PROJ_ROOT / "frames" / campaign / "approval_log.json"
    return json.loads(path.read_text()) if path.exists() else []


def save_log(campaign: str, log: list) -> None:
    path = PROJ_ROOT / "frames" / campaign / "approval_log.json"
    path.write_text(json.dumps(log, indent=2))


def print_scene_card(scene: dict) -> None:
    chars = scene["frame"]["characters_present"]
    char  = scene["dialogue"]["character"]
    line  = scene["dialogue"]["line"]
    print(f"\n  {'─'*56}")
    print(f"  Characters: {', '.join(chars)}")
    print(f"  {char} says: \"{line}\"")
    print()
    for c in chars:
        pose = scene["frame"].get(f"{c}_pose", "")
        expr = scene["frame"].get(f"{c}_expression", "")
        if pose:
            print(f"  {c} pose:  {pose}")
        if expr:
            print(f"  {c} expr:  {expr}")
    cam = scene["frame"].get("camera_angle", "")
    if cam:
        print(f"  Camera:  {cam}")
    print(f"  {'─'*56}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN GATE LOOP
# ══════════════════════════════════════════════════════════════════════════════

def run_gate(campaign: str, scene_filter: str | None = None) -> None:
    pending_dir  = PROJ_ROOT / "frames" / campaign / "pending"
    approved_dir = PROJ_ROOT / "frames" / campaign / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)

    if not pending_dir.exists() or not any(pending_dir.glob("*.png")):
        approved = list(approved_dir.glob("*.png"))
        print(f"\n  No pending frames for '{campaign}'.")
        if approved:
            print(f"  {len(approved)} frames already approved. Ready for animation:")
            print(f"    python scripts/animation_engine.py --campaign {campaign}")
        return

    frames = sorted(pending_dir.glob("*.png"))
    if scene_filter:
        frames = [f for f in frames if scene_filter in f.stem]
    if not frames:
        print(f"  No pending frames matching '{scene_filter}'.")
        return

    rejections = load_rejections(campaign)
    log        = load_log(campaign)
    approved_count = rejected_count = skipped_count = 0

    print(f"\n{'═'*60}")
    print(f" APPROVAL GATE — {campaign.upper()}  ({len(frames)} frames)")
    print(f"{'═'*60}")
    print("  [A] Approve   [R] Reject (you'll type what's wrong)   [S] Skip\n")

    for frame_path in frames:
        scene_id = frame_path.stem
        scene    = load_scene(campaign, scene_id)

        print(f"\n  Frame: {frame_path.name}")
        if scene:
            print_scene_card(scene)
        else:
            print(f"  [WARN] No scene blueprint found for {scene_id}")

        open_image(frame_path)

        while True:
            try:
                resp = input("\n  Decision [A/R/S]: ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                print("\n  Interrupted — progress saved.")
                save_rejections(campaign, rejections)
                save_log(campaign, log)
                sys.exit(0)

            if resp == "A":
                dest = approved_dir / frame_path.name
                shutil.move(str(frame_path), str(dest))
                if scene_id in rejections:
                    del rejections[scene_id]
                    save_rejections(campaign, rejections)
                log.append({"scene_id": scene_id, "status": "approved",
                            "timestamp": datetime.now().isoformat(), "path": str(dest)})
                save_log(campaign, log)
                print(f"  ✅ APPROVED → approved/{frame_path.name}")
                approved_count += 1
                break

            elif resp == "R":
                try:
                    note = input("  What's wrong? (rejection note): ").strip()
                except (EOFError, KeyboardInterrupt):
                    note = ""
                if not note:
                    note = "rejected — no note provided"
                rejections[scene_id] = {"note": note, "timestamp": datetime.now().isoformat()}
                save_rejections(campaign, rejections)
                frame_path.unlink()
                log.append({"scene_id": scene_id, "status": "rejected", "note": note,
                            "timestamp": datetime.now().isoformat()})
                save_log(campaign, log)
                print(f"  ❌ REJECTED — \"{note}\"")
                print(f"     Retry: python scripts/frame_generator.py --scene scenes/{campaign}/{scene_id}.json")
                rejected_count += 1
                break

            elif resp == "S":
                print(f"  ⏭  SKIPPED")
                skipped_count += 1
                break
            else:
                print("  Type A, R, or S")

    print(f"\n{'═'*60}")
    print(f" DONE — ✅ {approved_count} approved  ❌ {rejected_count} rejected  ⏭ {skipped_count} skipped")
    print(f"{'═'*60}")

    if rejected_count > 0:
        print(f"\n  Regenerate rejected frames:")
        for sid, info in rejections.items():
            print(f'    python scripts/frame_generator.py --scene scenes/{campaign}/{sid}.json \\')
            print(f'        --rejection-note "{info["note"]}"')

    all_approved = list(approved_dir.glob("*.png"))
    still_pending = list(pending_dir.glob("*.png"))
    if not still_pending and all_approved:
        print(f"\n  All clear — {len(all_approved)} approved. Ready:")
        print(f"    python scripts/animation_engine.py --campaign {campaign}")
    elif still_pending:
        print(f"\n  {len(still_pending)} still pending:")
        print(f"    python scripts/approval_gate.py --campaign {campaign}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ProBodyForLife — Frame Approval Gate")
    parser.add_argument("--campaign", required=True, type=str)
    parser.add_argument("--scene",    type=str, default=None)
    args = parser.parse_args()
    run_gate(args.campaign, args.scene)


if __name__ == "__main__":
    main()
