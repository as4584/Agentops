#!/usr/bin/env python3
"""
MHP Adrenaline Drive Ad Generator
===================================
Pipeline:
  1. Generate voiceover lines with ElevenLabs (guy + product character)
  2. Upload the MHP guy photo to FAL
  3. Lip-sync the guy's photo to his voiceover (fal-ai/latentsync)
  4. Generate animated product character scene (fal-ai/flux/dev)
  5. Stitch all scenes together with ffmpeg

Usage:
    python scripts/mhp_ad_generator.py --image path/to/mhp_guy.jpg
"""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path

import requests
import fal_client

# ── Load env ────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

FAL_KEY        = os.getenv("FAL_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")

if not FAL_KEY:
    sys.exit("ERROR: FAL_KEY not found in .env")
if not ELEVENLABS_KEY:
    sys.exit("ERROR: ELEVENLABS_API_KEY not found in .env")

os.environ["FAL_KEY"] = FAL_KEY

# ── Script ───────────────────────────────────────────────
SCRIPT = [
    {
        "speaker": "guy",
        "text": (
            "Hey Adrenaline Drive — everyone at the gym is talking about you. "
            "What's your deal?"
        ),
    },
    {
        "speaker": "product",
        "text": (
            "Simple! I deliver instant, sustained energy without the crash. "
            "Caffeine, L-Theanine, B-Vitamins — all dialed in for peak performance."
        ),
    },
    {
        "speaker": "guy",
        "text": "That's exactly what MHP athletes need.",
    },
    {
        "speaker": "product",
        "text": (
            "But heads up — if you're sensitive to caffeine, start with half a packet. "
            "And don't take me too close to bedtime!"
        ),
    },
]

# ElevenLabs voice IDs — change to your preferred voices
VOICES = {
    "guy":     "pNInz6obpgDQGcFmaJgB",   # Adam — deep male
    "product": "EXAVITQu4vr4xnSDxMaL",   # Bella — energetic
}


# ── Helpers ──────────────────────────────────────────────

def generate_elevenlabs_audio(text: str, voice_id: str, out_path: Path) -> Path:
    """Call ElevenLabs TTS and save mp3."""
    print(f"  [ElevenLabs] Generating audio for: {text[:50]}...")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    print(f"  [ElevenLabs] Saved → {out_path}")
    return out_path


def image_to_looping_video(image_path: Path, duration: float, out_path: Path) -> Path:
    """Convert a still image to a looping mp4 using ffmpeg (needed by latentsync)."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-t", str(duration),
        "-vf", "scale=640:960:force_original_aspect_ratio=decrease,pad=640:960:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def lipsync_with_fal(image_path: Path, audio_path: Path, work_dir: Path) -> Path:
    """Convert image → looping video, upload both, run latentsync, return local video."""
    # 1 — Get audio duration and create a still video of same length
    duration = get_audio_duration(audio_path)
    loop_video = work_dir / (audio_path.stem + "_loop.mp4")
    print(f"  [ffmpeg] Creating {duration:.1f}s looping video from image...")
    image_to_looping_video(image_path, duration, loop_video)

    # 2 — Convert audio to WAV (latentsync requires WAV)
    wav_path = work_dir / (audio_path.stem + ".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
        check=True, capture_output=True,
    )

    # 3 — Upload both to FAL
    print(f"  [FAL] Uploading video + audio...")
    video_url = fal_client.upload_file(str(loop_video))
    audio_url = fal_client.upload_file(str(wav_path))

    # 4 — Run sync-lipsync (more robust for still-image source)
    print(f"  [FAL] Running sync-lipsync (this takes ~30-60s)...")
    result = fal_client.subscribe(
        "fal-ai/sync-lipsync",
        arguments={
            "video_url": video_url,
            "audio_url": audio_url,
            "model": "lipsync-1.9.0-beta",
            "sync_mode": "bounce",
        },
        with_logs=True,
    )

    video_result_url = result["video"]["url"]
    print(f"  [FAL] Lip-sync done → {video_result_url}")

    # 4 — Download result
    out = work_dir / (audio_path.stem + "_lipsync.mp4")
    r = requests.get(video_result_url, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def generate_product_scene(text: str, out_dir: Path, index: int) -> Path:
    """Generate an animated product character image via FAL flux, then lip-sync."""
    print(f"  [FAL] Generating product character image...")

    # 1 — Generate image of the product character
    img_result = fal_client.subscribe(
        "fal-ai/flux/dev",
        arguments={
            "prompt": (
                "A cute, friendly animated energy drink packet character named "
                "'Adrenaline Drive' by MHP with blue and yellow colors, glowing "
                "with energy, talking, Pixar style 3D render, white background"
            ),
            "image_size": "portrait_4_3",
            "num_inference_steps": 28,
        },
        with_logs=False,
    )
    img_url = img_result["images"][0]["url"]
    print(f"  [FAL] Product image → {img_url}")

    # 2 — Download product image locally
    img_path = out_dir / f"product_{index}.jpg"
    r = requests.get(img_url, timeout=30)
    r.raise_for_status()
    img_path.write_bytes(r.content)

    # 3 — Generate product voice
    audio_path = out_dir / f"product_{index}.mp3"
    generate_elevenlabs_audio(text, VOICES["product"], audio_path)

    # 4 — Lip-sync product image to audio
    video_path = lipsync_with_fal(img_path, audio_path, out_dir)
    return video_path


def concat_videos(video_paths: list[Path], out_path: Path) -> Path:
    """Concatenate mp4 files using ffmpeg concat demuxer."""
    list_file = out_path.parent / "concat_list.txt"
    with open(list_file, "w") as f:
        for p in video_paths:
            f.write(f"file '{p.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    print(f"\n  [ffmpeg] Stitching {len(video_paths)} scenes...")
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  [ffmpeg] Final video → {out_path}")
    return out_path


# ── Main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate MHP Adrenaline Drive ad")
    parser.add_argument("--image", required=True, help="Path to MHP guy photo")
    parser.add_argument("--out", default="output/mhp_adrenaline_ad.mp4", help="Output video path")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        sys.exit(f"ERROR: Image not found: {image_path}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    work_dir = Path(tempfile.mkdtemp(prefix="mhp_ad_"))
    print(f"\n Working directory: {work_dir}")

    scene_videos: list[Path] = []

    for i, line in enumerate(SCRIPT):
        print(f"\n[SCENE {i+1}/{len(SCRIPT)}] {line['speaker'].upper()}: {line['text'][:60]}...")

        if line["speaker"] == "guy":
            # Generate guy audio then lip-sync with his photo
            audio_path = work_dir / f"guy_{i}.mp3"
            generate_elevenlabs_audio(line["text"], VOICES["guy"], audio_path)
            video_path = lipsync_with_fal(image_path, audio_path, work_dir)

        else:
            # Generate animated product character scene
            video_path = generate_product_scene(line["text"], work_dir, i)

        scene_videos.append(video_path)
        print(f"  Scene {i+1} ready → {video_path}")

    print(f"\n[FINAL] Concatenating all scenes...")
    final = concat_videos(scene_videos, out_path)

    print(f"\n✅ Done! Ad saved to: {final}")
    print(f"   Run: vlc {final}")


if __name__ == "__main__":
    main()
