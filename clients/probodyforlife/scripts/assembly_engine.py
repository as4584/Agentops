#!/usr/bin/env python3
"""
assembly_engine.py
==================
Full pipeline: frame → Ken Burns → ElevenLabs voice → sync-lipsync → ffmpeg assembly

Usage:
    python scripts/assembly_engine.py --campaign xpel_ad
    python scripts/assembly_engine.py --campaign xpel_ad --scene 01   # single scene
    python scripts/assembly_engine.py --campaign xpel_ad --assemble-only  # skip generation

Output:
    clips/xpel_ad/scene_01.mp4 ... scene_07.mp4
    clips/xpel_ad/xpel_ad_final.mp4

Ken Burns approach: scale filter with eval=frame + crop — NO zoompan (has internal-state shake bug)
"""

from __future__ import annotations
import argparse, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Load env ───────────────────────────────────────────────────────────────────
_root = Path(__file__).resolve().parent
for _ in range(8):
    if (_root / ".env").exists():
        break
    _root = _root.parent
from dotenv import load_dotenv
load_dotenv(_root / ".env")

import fal_client
import requests

PROJ        = Path(__file__).resolve().parents[1]
FRAMES_DIR  = PROJ / "frames"  / "xpel_ad"
SCENES_DIR  = PROJ / "scenes"  / "xpel_ad"
CLIPS_DIR   = PROJ / "clips"   / "xpel_ad"
AUDIO_DIR   = PROJ / "audio"   / "xpel_ad"
VOICES_DIR  = PROJ / "VideoGenerator" / "voices"

CLIPS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

W, H = 1024, 1536   # output frame dimensions

# ── Per-scene Ken Burns motion ─────────────────────────────────────────────────
# scale_start / scale_end: fraction of W×H (1.0 = exact, 1.06 = 6% bigger)
# x_drift, y_drift: total pixel drift over clip duration (+ = right/down)
SCENE_MOTION: dict[str, dict] = {
    "scene_01": dict(scale_start=1.00, scale_end=1.06, x_drift=0,   y_drift=0),   # slow push in
    "scene_02": dict(scale_start=1.06, scale_end=1.00, x_drift=0,   y_drift=0),   # slow pull out (reveal)
    "scene_03": dict(scale_start=1.00, scale_end=1.07, x_drift=6,   y_drift=0),   # push in + slight right
    "scene_04": dict(scale_start=1.06, scale_end=1.06, x_drift=55,  y_drift=0),   # pan right (Xpel→MrWilly)
    "scene_05": dict(scale_start=1.00, scale_end=1.09, x_drift=0,   y_drift=0),   # strong push in (tension)
    "scene_06": dict(scale_start=1.04, scale_end=1.04, x_drift=-28, y_drift=8),   # drift toward Xpel (left)
    "scene_07": dict(scale_start=1.00, scale_end=1.10, x_drift=0,   y_drift=-6),  # hero push in + upward tilt
}


# ── Ken Burns: scale with eval=frame + crop (zero shake) ──────────────────────
def build_ken_burns(scene_id: str, frame_png: Path, duration_s: float, out_mp4: Path) -> None:
    m       = SCENE_MOTION[scene_id]
    fps     = 25
    nf      = max(round(duration_s * fps), 2)
    s0, s1  = m["scale_start"], m["scale_end"]
    xd, yd  = m["x_drift"], m["y_drift"]
    denom   = max(nf - 1, 1)

    # scale: per-frame evaluation — w/h interpolate from s0→s1 over nf frames
    scale_vf = (
        f"scale="
        f"w='trunc(({W}*({s0}+({s1}-{s0})*n/{denom}))/2)*2':"
        f"h='trunc(({H}*({s0}+({s1}-{s0})*n/{denom}))/2)*2':"
        f"eval=frame"
    )
    # crop: output always W×H, position drifts linearly
    crop_vf = (
        f"crop={W}:{H}:"
        f"'(iw-{W})/2+{xd}*n/{denom}':"
        f"'(ih-{H})/2+{yd}*n/{denom}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps),
        "-i", str(frame_png),
        "-vf", f"{scale_vf},{crop_vf}",
        "-frames:v", str(nf),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg KB failed [{scene_id}]:\n{r.stderr[-1000:]}")
    print(f"    KB  → {out_mp4.name}  ({nf}f, {duration_s:.1f}s)")


# ── ElevenLabs TTS ─────────────────────────────────────────────────────────────
def generate_voice(scene_id: str, scene_data: dict, out_mp3: Path) -> float:
    if out_mp3.exists():
        dur = probe_duration(out_mp3)
        print(f"    Voice cached → {out_mp3.name}  ({dur:.1f}s)")
        return dur

    char    = scene_data["dialogue"]["character"]
    line    = scene_data["dialogue"]["line"].strip()
    vpath   = PROJ / scene_data["dialogue"]["voice"]
    vcfg    = json.loads(vpath.read_text())

    r = requests.post(
        f"{ELEVENLABS_BASE}/{vcfg['voice_id']}",
        headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
        json={
            "text": line,
            "model_id": vcfg["settings"]["model"],
            "voice_settings": {
                "stability":         vcfg["settings"]["stability"],
                "similarity_boost":  vcfg["settings"]["similarity_boost"],
                "style":             vcfg["settings"].get("style", 0.0),
                "use_speaker_boost": vcfg["settings"].get("use_speaker_boost", True),
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    out_mp3.write_bytes(r.content)
    dur = probe_duration(out_mp3)
    print(f"    Voice → {out_mp3.name}  ({char}, {dur:.1f}s, {len(r.content)//1024}KB)")
    return dur


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip() or "5")


# ── FAL sync-lipsync ───────────────────────────────────────────────────────────
def run_lipsync(scene_id: str, base_mp4: Path, voice_mp3: Path, out_mp4: Path) -> None:
    if out_mp4.exists():
        print(f"    Lipsync cached → {out_mp4.name}")
        return

    vid_url = fal_client.upload_file(str(base_mp4))
    aud_url = fal_client.upload_file(str(voice_mp3))
    print(f"    Lipsync [{scene_id}] running…")

    result = fal_client.subscribe(
        "fal-ai/sync-lipsync",
        arguments={
            "video_url":     vid_url,
            "audio_url":     aud_url,
            "model":         "lipsync-1.9.0-beta",
            "sync_mode":     "bounce",
            "output_format": "mp4",
        },
        with_logs=False,
    )
    out_url = result.get("video", {}).get("url") or result.get("url")
    if not out_url:
        raise RuntimeError(f"No URL from lipsync [{scene_id}]: {result}")

    data = requests.get(out_url, timeout=60).content
    out_mp4.write_bytes(data)
    print(f"    Lipsync done  → {out_mp4.name}  ({len(data)//1024}KB)")


# ── Single scene pipeline ──────────────────────────────────────────────────────
def process_scene(scene_id: str) -> Path:
    print(f"\n── {scene_id} ────────────────────────────────────────")
    scene_data = json.loads((SCENES_DIR / f"{scene_id}.json").read_text())

    frame_num = int(scene_id.split("_")[1])
    approved  = FRAMES_DIR / "approved" / f"scene_{frame_num:02d}.png"
    seed      = FRAMES_DIR / f"frame_{frame_num}.png"
    frame_png = approved if approved.exists() else seed
    if not frame_png.exists():
        raise FileNotFoundError(f"No frame for {scene_id}: checked {approved}, {seed}")

    base_mp4  = CLIPS_DIR / f"base_{scene_id}.mp4"
    voice_mp3 = AUDIO_DIR / f"{scene_id}_voice.mp3"
    out_mp4   = CLIPS_DIR / f"{scene_id}.mp4"

    # 1. Voice → determines clip duration
    voice_dur = generate_voice(scene_id, scene_data, voice_mp3)
    clip_dur  = max(voice_dur + 0.6, 5.0)

    # 2. Ken Burns base clip
    if not base_mp4.exists():
        build_ken_burns(scene_id, frame_png, clip_dur, base_mp4)
    else:
        print(f"    KB  cached  → {base_mp4.name}")

    # 3. Lipsync
    run_lipsync(scene_id, base_mp4, voice_mp3, out_mp4)
    return out_mp4


# ── ffmpeg assembly with xfade dissolves ──────────────────────────────────────
def assemble(scene_ids: list[str], out_mp4: Path) -> None:
    print(f"\n── Assembly ─────────────────────────────────────────")
    clips = [CLIPS_DIR / f"{sid}.mp4" for sid in scene_ids]
    missing = [c for c in clips if not c.exists()]
    if missing:
        sys.exit("Missing clips:\n" + "\n".join(str(m) for m in missing))

    durations = [probe_duration(c) for c in clips]
    xfade_dur = 0.4
    n = len(clips)

    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]

    # Build xfade + acrossfade filter chain
    filter_parts = []
    offset = durations[0] - xfade_dur
    prev_v, prev_a = "[0:v]", "[0:a]"

    for i in range(1, n):
        is_last = (i == n - 1)
        lv = "[vout]" if is_last else f"[vx{i}]"
        la = "[aout]" if is_last else f"[ax{i}]"
        filter_parts.append(
            f"{prev_v}[{i}:v] xfade=transition=fade:duration={xfade_dur}:offset={offset:.4f} {lv}"
        )
        filter_parts.append(
            f"{prev_a}[{i}:a] acrossfade=d={xfade_dur} {la}"
        )
        offset += durations[i] - xfade_dur
        prev_v = lv if not is_last else "[vout]"
        prev_a = la if not is_last else "[aout]"

    fc = "; ".join(filter_parts)
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", fc,
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k",
           str(out_mp4)]
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg assembly failed:\n{r.stderr[-2000:]}")

    mb = out_mp4.stat().st_size / 1_000_000
    print(f"  Final → {out_mp4.name}  ({mb:.1f}MB)")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="xpel_ad")
    ap.add_argument("--scene", help="Single scene number e.g. 01")
    ap.add_argument("--assemble-only", action="store_true")
    ap.add_argument("--workers", type=int, default=2, help="Parallel lipsync workers")
    args = ap.parse_args()

    all_ids = [f"scene_{i:02d}" for i in range(1, 8)]

    if args.scene:
        process_scene(f"scene_{int(args.scene):02d}")
        return

    if args.assemble_only:
        assemble(all_ids, CLIPS_DIR / f"{args.campaign}_final.mp4")
        return

    print(f"XPEL Ad Assembly Engine — {len(all_ids)} scenes, {args.workers} workers")

    # Phase 1: all voices (fast, ElevenLabs only)
    print("\n── Phase 1: Voices ──────────────────────────────────")
    for sid in all_ids:
        scene_data = json.loads((SCENES_DIR / f"{sid}.json").read_text())
        generate_voice(sid, scene_data, AUDIO_DIR / f"{sid}_voice.mp3")

    # Phase 2: Ken Burns + lipsync (parallel)
    print(f"\n── Phase 2: Ken Burns + Lipsync ─────────────────────")
    results: dict[str, Path | None] = {}

    def _run(sid):
        try:
            return sid, process_scene(sid), None
        except Exception as e:
            return sid, None, e

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run, sid): sid for sid in all_ids}
        for fut in as_completed(futures):
            sid, clip, err = fut.result()
            if err:
                print(f"  ERROR {sid}: {err}")
                results[sid] = None
            else:
                results[sid] = clip

    # Phase 3: assemble
    ready = [sid for sid in all_ids if results.get(sid) and results[sid].exists()]
    if not ready:
        sys.exit("No clips ready to assemble.")
    if len(ready) < len(all_ids):
        failed = [s for s in all_ids if s not in ready]
        print(f"\nWARNING: {len(failed)} failed: {failed} — assembling {len(ready)} clips")

    out = CLIPS_DIR / f"{args.campaign}_final.mp4"
    assemble(ready, out)
    print(f"\nDONE → {out}")


if __name__ == "__main__":
    main()
