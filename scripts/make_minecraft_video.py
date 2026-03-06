"""
Standalone: Generate a 15-second Minecraft tips video — 100% free, no API keys.
Pipeline:
  1. Ollama (local LLM) → generate script
  2. espeak-ng          → text-to-speech audio
  3. ffmpeg             → compose video with animated text + audio
Output: output/videos/minecraft_pro_tips.mp4
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output" / "videos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_PATH = OUTPUT_DIR / "minecraft_audio.wav"
VIDEO_PATH = OUTPUT_DIR / "minecraft_pro_tips.mp4"


# ---------------------------------------------------------------------------
# Step 1: Generate script via Ollama (local — free)
# ---------------------------------------------------------------------------
def generate_script() -> str:
    print("🧠 Generating script with local LLM (ollama)...")
    payload = {
        "model": "llama3.2",
        "prompt": (
            "Write a punchy 15-second TikTok script for a video called "
            "'How to Become a Pro at Minecraft'. "
            "Make it energetic, beginner-friendly, and under 60 words. "
            "Start with a strong hook. No hashtags, no emojis, plain text only."
        ),
        "stream": False,
    }
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://localhost:11434/api/generate",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=60
        )
        data = json.loads(result.stdout)
        script = data.get("response", "").strip()
        if script:
            print(f"✅ Script generated ({len(script.split())} words)")
            print(f"\n--- SCRIPT ---\n{script}\n--------------\n")
            return script
    except Exception as e:
        print(f"⚠️  LLM failed ({e}), using fallback script")

    # Fallback script if LLM unavailable
    return (
        "Want to become a Minecraft pro? Here's what separates beginners from legends. "
        "Always carry a water bucket for fall damage. Build your base underground at night. "
        "Use torches to mark your mine path. Master the sword sweep attack. "
        "And never dig straight down. Apply these tips and you'll dominate survival mode."
    )


# ---------------------------------------------------------------------------
# Step 2: Text-to-speech via espeak-ng (free, local)
# ---------------------------------------------------------------------------
def generate_audio(script: str) -> bool:
    print("🎙️  Generating audio with espeak-ng...")
    try:
        result = subprocess.run(
            ["espeak-ng",
             "-v", "en-us",
             "-s", "145",        # words per minute — natural speech pace
             "-p", "45",         # pitch
             "-a", "180",        # amplitude
             "-w", str(AUDIO_PATH),
             script],
            capture_output=True, timeout=30
        )
        if result.returncode == 0 and AUDIO_PATH.exists():
            print(f"✅ Audio saved: {AUDIO_PATH}")
            return True
        print(f"❌ espeak-ng failed: {result.stderr.decode()[:200]}")
        return False
    except FileNotFoundError:
        print("❌ espeak-ng not found. Run: apt install espeak-ng")
        return False


# ---------------------------------------------------------------------------
# Step 3: Compose video with ffmpeg — animated title card + audio
# ---------------------------------------------------------------------------
def _esc(text: str) -> str:
    """Escape text for ffmpeg drawtext: backslash, colon, apostrophe, percent."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")   # replace smart quote to avoid shell issues
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


def generate_video(script: str) -> bool:
    print("🎬 Composing video with ffmpeg...")

    # Wrap script text for display (max 32 chars per line)
    lines = textwrap.wrap(script, width=32)
    display_lines = lines[:6]

    y_start = 580
    line_height = 65
    drawtext_filters = []

    # Title lines
    drawtext_filters.append(
        f"drawtext=text='HOW TO BECOME A':fontcolor=white:fontsize=50:"
        f"x=(w-text_w)/2:y=180:box=1:boxcolor=black@0.6:boxborderw=8"
    )
    drawtext_filters.append(
        f"drawtext=text='MINECRAFT PRO':fontcolor=0x55FF55:fontsize=68:"
        f"x=(w-text_w)/2:y=245:box=1:boxcolor=black@0.7:boxborderw=8"
    )

    # Script lines
    for i, line in enumerate(display_lines):
        line_esc = _esc(line)
        y = y_start + i * line_height
        drawtext_filters.append(
            f"drawtext=text='{line_esc}':fontcolor=white:fontsize=36:"
            f"x=(w-text_w)/2:y={y}"
        )

    vf = ",".join(drawtext_filters)

    try:
        # Get actual audio duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(AUDIO_PATH)],
            capture_output=True, text=True, timeout=10
        )
        duration = 15.0
        try:
            probe_data = json.loads(probe.stdout)
            duration = float(probe_data["format"]["duration"])
            # Clamp to at least 15 seconds for the 15-second video requirement
            duration = max(duration, 15.0)
        except Exception:
            pass

        cmd = [
            "ffmpeg", "-y",
            # Green/dark animated background (Minecraft feel)
            "-f", "lavfi",
            "-i", f"color=c=#1a2e1a:s=1080x1920:d={duration}",
            # Audio
            "-i", str(AUDIO_PATH),
            # Video filters: background + text
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(VIDEO_PATH),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and VIDEO_PATH.exists():
            size_mb = VIDEO_PATH.stat().st_size / (1024 * 1024)
            print(f"✅ Video saved: {VIDEO_PATH} ({size_mb:.1f} MB)")
            return True
        print(f"❌ ffmpeg failed:\n{result.stderr[-400:]}")
        return False
    except FileNotFoundError:
        print("❌ ffmpeg not found. Run: apt install ffmpeg")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n🚀 Minecraft Pro Tips Video Generator — 100% Free\n")

    script = generate_script()

    if not generate_audio(script):
        print("\n❌ Stopping: audio generation failed.")
        sys.exit(1)

    if not generate_video(script):
        print("\n❌ Stopping: video generation failed.")
        sys.exit(1)

    print(f"\n✅ DONE! Your video is ready at:\n   {VIDEO_PATH}\n")
