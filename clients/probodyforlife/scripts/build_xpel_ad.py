#!/usr/bin/env python3
"""
ProBodyForLife — XPEL Ad Builder
==================================
Rules:
  - ZERO image generation. Every visual is a pre-approved frame.
  - 7 scenes, hard cut between each (no fades).
  - ElevenLabs voice per scene.
  - FAL sync-lipsync to animate each frame.
  - ffmpeg final assembly at 1080x1920 9:16.

Output: probodyforlife/output/xpel_ad.mp4
"""

from __future__ import annotations

import os, sys, subprocess, tempfile, time
from pathlib import Path
import requests
import fal_client
from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
FRAMES_DIR = ROOT / "frames" / "xpel_ad"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Env ──────────────────────────────────────────────────
load_dotenv(ROOT.parent / ".env")
FAL_KEY        = os.getenv("FAL_KEY", "")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")

if not FAL_KEY:        sys.exit("ERROR: FAL_KEY not found")
if not ELEVENLABS_KEY: sys.exit("ERROR: ELEVENLABS_API_KEY not found")
os.environ["FAL_KEY"] = FAL_KEY

# ── Voices ───────────────────────────────────────────────
VOICE_GUY     = "pNInz6obpgDQGcFmaJgB"   # Adam — deep athletic male
VOICE_PRODUCT = "EXAVITQu4vr4xnSDxMaL"  # Bella — energetic punchy

# ── Locked Script ────────────────────────────────────────
# frame file, voice, line
SCENES = [
    ("frame_1.png", VOICE_GUY,
     "Hey XPEL... everyone at the gym keeps talking about you. What's your deal?"),

    ("frame_2.png", VOICE_PRODUCT,
     "I'm America's number one selling diuretic! I flush out excess water, reduce bloating, and support weight loss — naturally!"),

    ("frame_3.png", VOICE_GUY,
     "Okay okay... but what's actually inside you? What makes you work?"),

    ("frame_4.png", VOICE_PRODUCT,
     "Dandelion root, Uva Ursi, Buchu leaf — all natural herbal ingredients working together to help your body shed that water weight fast."),

    ("frame_5.png", VOICE_GUY,
     "Alright... but what's the catch? There's always a catch."),

    ("frame_6.png", VOICE_PRODUCT,
     "Well... make sure you stay hydrated. And if you have kidney issues, check with your doctor first. I'm powerful — use me responsibly!"),

    ("frame_7.png", VOICE_GUY,
     "And THAT is why everyone at the gym is talking about XPEL. Link in bio."),
]


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def banner(text: str):
    print(f"\n{'═'*54}\n {text}\n{'═'*54}")


def elevenlabs_tts(text: str, voice_id: str, out_mp3: Path) -> Path:
    """Generate speech via ElevenLabs, return mp3 path."""
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.80},
        },
        timeout=30,
    )
    r.raise_for_status()
    out_mp3.write_bytes(r.content)
    return out_mp3


def mp3_to_wav(mp3: Path, wav: Path) -> Path:
    """Convert MP3 → 16kHz mono WAV (required by sync-lipsync)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)],
        check=True, capture_output=True,
    )
    return wav


def audio_duration(path: Path) -> float:
    """Return duration in seconds via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def image_to_looping_video(img: Path, duration: float, out: Path) -> Path:
    """
    Convert a static PNG/JPG into a looping mp4.
    Pads to exactly 640x960 (sync-lipsync sweet spot).
    """
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(img),
        "-t", str(duration),
        "-vf", "scale=640:960:force_original_aspect_ratio=decrease,"
               "pad=640:960:(ow-iw)/2:(oh-ih)/2:color=white",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
        str(out),
    ], check=True, capture_output=True)
    return out


def lipsync(frame_video: Path, audio_wav: Path, out: Path) -> Path:
    """Run FAL sync-lipsync and download result."""
    print("    [FAL] Uploading frame video + audio...")
    video_url = fal_client.upload_file(str(frame_video))
    audio_url = fal_client.upload_file(str(audio_wav))

    print("    [FAL] Running sync-lipsync...")
    result = fal_client.subscribe(
        "fal-ai/sync-lipsync",
        arguments={
            "video_url": video_url,
            "audio_url": audio_url,
            "model": "lipsync-1.9.0-beta",
            "sync_mode": "bounce",
        },
        with_logs=False,
    )
    url = result["video"]["url"]
    print(f"    [FAL] Done → {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def normalize(src: Path, dst: Path) -> Path:
    """Upscale/pad to 1080x1920 at 25fps, high quality."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
        ),
        "-r", "25",
        "-c:v", "libx264", "-crf", "17", "-preset", "fast",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-pix_fmt", "yuv420p",
        str(dst),
    ], check=True, capture_output=True)
    return dst


def concat(clips: list[Path], out: Path) -> Path:
    """Hard-cut concat all clips."""
    list_file = out.parent / "concat.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in clips))
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out),
    ], check=True, capture_output=True)
    return out


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    work = Path(tempfile.mkdtemp(prefix="xpel_"))
    print(f"Working dir: {work}")

    normalized_clips: list[Path] = []

    for i, (frame_file, voice_id, line) in enumerate(SCENES, 1):
        frame_path = FRAMES_DIR / frame_file
        if not frame_path.exists():
            sys.exit(f"ERROR: Missing frame: {frame_path}")

        banner(f"SCENE {i}/{len(SCENES)}")
        print(f" Frame: {frame_file}")
        print(f" Line:  {line}")

        # 1 — Voice
        print("  [1/4] Generating voice...")
        mp3 = work / f"scene_{i}.mp3"
        wav = work / f"scene_{i}.wav"
        elevenlabs_tts(line, voice_id, mp3)
        mp3_to_wav(mp3, wav)
        dur = audio_duration(wav)
        print(f"        Duration: {dur:.1f}s")

        # 2 — Frame → looping video
        print("  [2/4] Creating looping frame video...")
        loop = work / f"scene_{i}_loop.mp4"
        image_to_looping_video(frame_path, dur, loop)

        # 3 — Lip-sync
        print("  [3/4] Lip-syncing...")
        synced = work / f"scene_{i}_synced.mp4"
        lipsync(loop, wav, synced)

        # 4 — Normalize to 1080x1920
        print("  [4/4] Normalizing to 1080x1920...")
        norm = work / f"scene_{i}_norm.mp4"
        normalize(synced, norm)
        normalized_clips.append(norm)

        print(f"  Scene {i} ✅")

    # Final assembly
    banner("FINAL ASSEMBLY — HARD CUTS")
    final = OUTPUT_DIR / "xpel_ad.mp4"
    concat(normalized_clips, final)

    size = final.stat().st_size / 1024 / 1024
    banner(f"DONE  →  {final}  ({size:.1f} MB)")
    print(f"  Play: vlc {final}\n")


if __name__ == "__main__":
    main()
