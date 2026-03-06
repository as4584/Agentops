#!/usr/bin/env python3
"""
Kling AI Image-to-Video Pipeline
=================================
Takes 8 storyboard images → animates via Kling (fal.ai) → stitches to
a 15-second short-form video with voiceover and captions.

Modes:
  --kling   Use Kling AI via fal.ai (requires FAL_KEY in .env)
  --free    ffmpeg ken-burns zoom on all 8 frames (free, looks great
            for Reddit commentary / Coffeezilla style)

Usage:
  # Drop your 8 images into output/frames/betrayal/ named frame_1.png ... frame_8.png
  python scripts/make_kling_video.py --job edfc9dfe4585 --frames output/frames/betrayal/
  python scripts/make_kling_video.py --job edfc9dfe4585 --frames output/frames/betrayal/ --kling
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

OUTPUT_DIR = ROOT / "output" / "videos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = ROOT / "output" / "_kling_tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Script for job edfc9dfe4585 — trimmed to ~140 words for TTS
VOICEOVER_SCRIPT = """
Why is Bungie turning Marathon into a cash machine?
Marathon players have been bleeding out since the LUX launch.
Top players are leaving. Win rates are collapsing.
And nobody inside Bungie seems to care.
Because here's the truth they won't say out loud:
LUX was never about the game.
ARC Raiders just proved you can compete without gouging your playerbase.
Bungie looked at those numbers and panicked.
So instead of fixing the game — they opened a store.
Players are being charged twenty dollars for content that ARC Raiders gives away free.
The community rewards program is a ghost.
The gap between what Bungie promises and what they deliver keeps widening.
But here's what Bungie forgot.
We built this community. We can rebuild it without them.
Make LUX a relic of the past.
Drop a comment. Share this. Join the #LUXBetrayal movement.
The community always wins in the end.
"""

# 3 hero frames for Kling (5s each = 15s) — Hook, Conflict, Payoff
KLING_HERO_FRAMES = [1, 3, 8]  # frame numbers

# Kling prompts per hero frame (subtle motion to match each beat)
KLING_FRAME_PROMPTS = {
    1: "slow push-in zoom on Reddit post, text glows slightly, cold blue ambient light, documentary",
    3: "subtle screen flicker, text notification popups fading in, corporate blue glow, tense atmosphere",
    8: "slow zoom out from trending hashtag, comment cards fading in from bottom, resolution energy",
}

# Duration per clip (seconds)
KLING_CLIP_DURATION = 5  # min on Kling API
FREE_FRAME_DURATION = 1.875  # 8 frames × 1.875s = 15s total


def run(cmd: list[str], check=True, capture=False) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


# ── TTS Voiceover ──────────────────────────────────────────────────────────────

def generate_voiceover(job_id: str) -> Path:
    audio_path = TEMP_DIR / f"{job_id}_vo.wav"
    if audio_path.exists():
        print(f"  Voiceover already exists: {audio_path}")
        return audio_path

    print("\n[1/4] Generating voiceover with espeak-ng...")
    script_path = TEMP_DIR / f"{job_id}_script.txt"
    script_path.write_text(VOICEOVER_SCRIPT.strip())

    run([
        "espeak-ng",
        "-f", str(script_path),
        "-w", str(audio_path),
        "-s", "150",   # words per minute — slower = more weight
        "-p", "40",    # pitch — lower = more authoritative
        "-a", "180",   # amplitude
        "--ipa",
    ], check=False)

    # Fallback if --ipa caused issues
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        run([
            "espeak-ng",
            "-f", str(script_path),
            "-w", str(audio_path),
            "-s", "150",
            "-p", "40",
        ])

    print(f"  Voiceover: {audio_path} ({audio_path.stat().st_size / 1024:.1f}KB)")
    return audio_path


# ── Mode A: Kling image-to-video via fal.ai ───────────────────────────────────

async def run_kling(frames_dir: Path, job_id: str) -> list[Path]:
    """Animate 3 hero frames via Kling AI (fal.ai). Returns list of clip paths."""
    try:
        import fal_client
    except ImportError:
        print("  Installing fal-client...")
        subprocess.run([sys.executable, "-m", "pip", "install", "fal-client", "-q"], check=True)
        import fal_client

    fal_key = os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")
    if not fal_key:
        raise ValueError(
            "FAL_KEY not found in .env. "
            "Get one free at https://fal.ai → sign up → Settings → API Keys. "
            "Then add FAL_KEY=your_key to .env"
        )
    os.environ["FAL_KEY"] = fal_key

    clips: list[Path] = []
    total_frames = len(KLING_HERO_FRAMES)

    for i, frame_num in enumerate(KLING_HERO_FRAMES, 1):
        img_path = _find_frame(frames_dir, frame_num)
        clip_out = TEMP_DIR / f"{job_id}_kling_clip_{frame_num}.mp4"

        if clip_out.exists() and clip_out.stat().st_size > 50000:
            print(f"  Frame {frame_num}: cached ✓")
            clips.append(clip_out)
            continue

        print(f"\n[{i}/{total_frames}] Kling: animating frame {frame_num}...")
        print(f"  Image: {img_path}")
        prompt = KLING_FRAME_PROMPTS.get(frame_num, "slow cinematic push-in, documentary, cold blue light")

        # Upload image to fal storage
        print("  Uploading image...")
        image_url = await fal_client.upload_file_async(str(img_path))
        print(f"  Uploaded: {image_url}")

        # Submit and wait for Kling image-to-video job
        print(f"  Submitting to kling-video/v1.6/standard/image-to-video (duration={KLING_CLIP_DURATION}s)...")
        start = time.time()

        def _on_queue_update(update):
            elapsed = time.time() - start
            kind = type(update).__name__
            if hasattr(update, "logs") and update.logs:
                for log in update.logs[-1:]:
                    print(f"  [{elapsed:.0f}s] {log.get('message', '')}", end="\r")
            else:
                print(f"  [{elapsed:.0f}s] {kind}...", end="\r")

        result = await fal_client.subscribe_async(
            "fal-ai/kling-video/v1.6/standard/image-to-video",
            arguments={
                "image_url": image_url,
                "prompt": prompt,
                "duration": str(KLING_CLIP_DURATION),
                "aspect_ratio": "9:16",
            },
            on_queue_update=_on_queue_update,
        )

        elapsed = time.time() - start
        video_url = result["video"]["url"] if isinstance(result, dict) else result.video.url
        print(f"\n  Done ({elapsed:.0f}s) → {video_url[:60]}...")

        # Download clip
        import urllib.request
        urllib.request.urlretrieve(video_url, clip_out)
        print(f"  Saved: {clip_out} ({clip_out.stat().st_size / 1024 / 1024:.1f}MB)")
        clips.append(clip_out)

    return clips


def _find_frame(frames_dir: Path, num: int) -> Path:
    """Find frame_N.png/jpg/webp in frames directory."""
    for ext in ["png", "jpg", "jpeg", "webp"]:
        p = frames_dir / f"frame_{num}.{ext}"
        if p.exists():
            return p
    # also try 0-padded
    for ext in ["png", "jpg", "jpeg", "webp"]:
        p = frames_dir / f"frame_{num:02d}.{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Frame {num} not found in {frames_dir}. "
        f"Expected: frame_{num}.png (or .jpg/.webp)"
    )


# ── Mode B: Free ken-burns zoom via ffmpeg ─────────────────────────────────────

def run_free_kenburns(frames_dir: Path, job_id: str) -> list[Path]:
    """Apply slow zoom/pan to all 8 images. Free, looks clean for doc style."""
    clips: list[Path] = []

    # Ken Burns presets — matched to arc beat energy
    # zoompan variables: zoom (current), on (output frame number 0-indexed)
    zoom_presets = [
        "zoompan=z='min(zoom+0.0015,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",            # 1 HOOK - slow zoom in center
        "zoompan=z='1.1':x='iw/2-(iw/zoom/2)+on*1.5':y='ih/2-(ih/zoom/2)'",                       # 2 RISING - drift right
        "zoompan=z='min(zoom+0.0020,1.25)':x='iw/2-(iw/zoom/2)':y='max(ih/2-(ih/zoom/2)-on,0)'",  # 3 CONFLICT - zoom + up
        "zoompan=z='max(zoom-0.001,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",              # 4 COMEBACK - zoom out
        "zoompan=z='min(zoom+0.0015,1.2)':x='max(iw/2-(iw/zoom/2)-on*1.5,0)':y='ih/2-(ih/zoom/2)'", # 5 SECOND RISING - drift left
        "zoompan=z='min(zoom+0.002,1.3)':x='iw-(iw/zoom)':y='ih-(ih/zoom)'",                      # 6 SECOND CONFLICT - corner anchor
        "zoompan=z='max(zoom-0.0015,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",             # 7 FINAL COMEBACK - release
        "zoompan=z='min(zoom+0.001,1.1)':x='iw/2-(iw/zoom/2)':y='ih-(ih/zoom)'",                  # 8 PAYOFF - settle bottom
    ]

    fps = 25
    total_frames_ffmpeg = int(FREE_FRAME_DURATION * fps)

    print(f"\n[2/4] Generating {8} ken-burns clips ({FREE_FRAME_DURATION}s each)...")

    for i in range(1, 9):
        img_path = _find_frame(frames_dir, i)
        clip_out = TEMP_DIR / f"{job_id}_free_clip_{i}.mp4"

        if clip_out.exists() and clip_out.stat().st_size > 10000:
            print(f"  Frame {i}: cached ✓")
            clips.append(clip_out)
            continue

        zoom = zoom_presets[i - 1]
        # Scale to 1080x1920 first, then apply ken-burns, output 1080x1920
        vf = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"{zoom}:d={total_frames_ffmpeg}:s=1080x1920:fps={fps},"
            f"scale=1080:1920"
        )

        run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(img_path),
            "-vf", vf,
            "-t", str(FREE_FRAME_DURATION),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            str(clip_out),
        ])

        size = clip_out.stat().st_size / 1024
        print(f"  Frame {i}/8: {clip_out.name} ({size:.0f}KB)")
        clips.append(clip_out)

    return clips


# ── Stitch Clips ──────────────────────────────────────────────────────────────

def stitch_clips(clips: list[Path], audio: Path, job_id: str, mode: str) -> Path:
    print(f"\n[3/4] Stitching {len(clips)} clips...")
    concat_list = TEMP_DIR / f"{job_id}_concat.txt"
    concat_list.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))

    stitched = TEMP_DIR / f"{job_id}_stitched.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(stitched),
    ])

    print(f"\n[4/4] Adding voiceover + desaturated grade...")
    final = OUTPUT_DIR / f"betrayal_lux_{mode}_{job_id[:8]}.mp4"

    # Get video duration to loop/trim audio
    run([
        "ffmpeg", "-y",
        "-i", str(stitched),
        "-i", str(audio),
        # Desaturated documentary color grade
        "-vf", "eq=saturation=0.3:contrast=1.05:brightness=-0.02,vignette=PI/6",
        "-af", "aresample=44100,volume=1.5",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        str(final),
    ])

    size_mb = final.stat().st_size / 1024 / 1024
    print(f"\n  Final: {final}")
    print(f"  Size:  {size_mb:.1f}MB")
    return final


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Kling AI / free video pipeline")
    parser.add_argument("--job", default="edfc9dfe4585", help="Job ID")
    parser.add_argument("--frames", required=True, help="Directory with frame_1.png ... frame_8.png")
    parser.add_argument("--kling", action="store_true", help="Use Kling AI (requires FAL_KEY)")
    parser.add_argument("--free", action="store_true", help="Free ffmpeg ken-burns mode (default)")
    args = parser.parse_args()

    frames_dir = Path(args.frames)
    if not frames_dir.exists():
        print(f"ERROR: frames directory not found: {frames_dir}")
        print("Create it and place your 8 images there: frame_1.png ... frame_8.png")
        sys.exit(1)

    # Check images exist
    found = sorted(frames_dir.glob("frame_*.*"))
    print(f"\nFound {len(found)} frames in {frames_dir}")
    for f in found:
        print(f"  {f.name}")

    if len(found) == 0:
        print(
            "\nERROR: No frames found.\n"
            "Place your 8 generated images in the folder as:\n"
            "  frame_1.png  (HOOK)\n"
            "  frame_2.png  (RISING ACTION)\n"
            "  frame_3.png  (CONFLICT)\n"
            "  frame_4.png  (COMEBACK 1)\n"
            "  frame_5.png  (SECOND RISING)\n"
            "  frame_6.png  (SECOND CONFLICT)\n"
            "  frame_7.png  (FINAL COMEBACK)\n"
            "  frame_8.png  (PAYOFF)\n"
        )
        sys.exit(1)

    use_kling = args.kling or (os.getenv("FAL_KEY") and not args.free)
    mode = "kling" if use_kling else "free"

    print(f"\n{'='*55}")
    print(f"  BETRAYAL OF ARC RAIDERS — 15 sec vertical video")
    print(f"  Mode: {'Kling AI via fal.ai' if use_kling else 'Free ffmpeg ken-burns'}")
    print(f"  Job:  {args.job}")
    print(f"{'='*55}")

    # Generate voiceover
    audio = generate_voiceover(args.job)

    # Generate video clips
    if use_kling:
        print("\n[2/4] Running Kling AI image-to-video (3 hero frames × 5s)...")
        print("  Cost estimate: ~$0.05/sec × 15sec = ~$0.75")
        clips = await run_kling(frames_dir, args.job)
    else:
        clips = run_free_kenburns(frames_dir, args.job)

    # Stitch and mix
    final = stitch_clips(clips, audio, args.job, mode)

    print(f"\n{'='*55}")
    print(f"  ✅ VIDEO COMPLETE")
    print(f"  {final}")
    print(f"{'='*55}")

    # Update job record
    try:
        sys.path.insert(0, str(ROOT))
        from backend.content.job_store import job_store
        job = job_store.load(args.job)
        if job:
            job.avatar_video_path = str(final)
            job_store.save(job)
            print(f"  Job {args.job} updated with video path.")
    except Exception as e:
        print(f"  (Job store update skipped: {e})")


if __name__ == "__main__":
    asyncio.run(main())
