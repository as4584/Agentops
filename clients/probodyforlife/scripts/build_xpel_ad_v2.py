#!/usr/bin/env python3
"""
ProBodyForLife — XPEL Ad Builder  v2  (Animated)
==================================================
Pipeline per scene:
  1. ElevenLabs TTS → MP3 → WAV
  2. Kling v2.1 image-to-video → smooth animated clip (real motion)
  3a. GUY scenes:     sync-lipsync → mouth follows voice on animated clip
  3b. PRODUCT scenes: ffmpeg mux   → add audio directly over animated clip
  4. Normalize → 1080x1920 9:16
  5. ffmpeg hard-cut concat → final video

Result: vivid Pixar-style animation + lip-sync, not just a wobbling mouth.
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
# (frame_file, voice_id, line, has_face, motion_prompt)
# has_face=True  → animated clip goes through sync-lipsync
# has_face=False → animated clip gets audio muxed directly (product shots)
SCENES = [
    (
        "frame_1.png", VOICE_GUY, True,
        "Hey XPEL... everyone at the gym keeps talking about you. What's your deal?",
        "Preserve exact character appearance. Very subtle idle animation: slow natural breathing, "
        "tiny chest rise and fall, gentle eye blink every 3 seconds, micro head sway left and right. "
        "Do not change the face, expression, or body. Static background. Cinematic lighting.",
    ),
    (
        "frame_2.png", VOICE_PRODUCT, False,
        "I'm America's number one selling diuretic! I flush out excess water, "
        "reduce bloating, and support weight loss — naturally!",
        "Preserve exact product packaging appearance. Very subtle motion: gentle glow pulse on the box, "
        "soft ambient sparkle particles floating around it. Do not distort or change the box design. "
        "Static background. Clean product shot.",
    ),
    (
        "frame_3.png", VOICE_GUY, True,
        "Okay okay... but what's actually inside you? What makes you work?",
        "Preserve exact character appearance. Very subtle idle animation: slow natural breathing, "
        "tiny chest rise and fall, gentle eye blink every 3 seconds, very slight weight shift. "
        "Do not change the face, expression, or body. Static background.",
    ),
    (
        "frame_4.png", VOICE_PRODUCT, False,
        "Dandelion root, Uva Ursi, Buchu leaf — all natural herbal ingredients working together "
        "to help your body shed that water weight fast.",
        "Preserve exact product packaging appearance. Very subtle motion: soft ambient light rays "
        "around the box, gentle floating particle effects. Do not distort or change the box design. "
        "Static background. Clean product shot.",
    ),
    (
        "frame_5.png", VOICE_GUY, True,
        "Alright... but what's the catch? There's always a catch.",
        "Preserve exact character appearance. Very subtle idle animation: slow natural breathing, "
        "tiny chest rise and fall, gentle eye blink every 3 seconds, very slight head tilt. "
        "Do not change the face, expression, or body. Static background.",
    ),
    (
        "frame_6.png", VOICE_PRODUCT, False,
        "Well... make sure you stay hydrated. And if you have kidney issues, check with your doctor "
        "first. I'm powerful — use me responsibly!",
        "Preserve exact product packaging appearance. Very subtle motion: gentle ambient glow pulse, "
        "soft floating particles. Do not distort or change the box design. Static background.",
    ),
    (
        "frame_7.png", VOICE_GUY, True,
        "And THAT is why everyone at the gym is talking about XPEL. Link in bio.",
        "Preserve exact character appearance. Very subtle idle animation: slow natural breathing, "
        "tiny chest rise and fall, gentle eye blink every 3 seconds, slight confident head nod. "
        "Do not change the face, expression, or body. Static background. Vibrant colors.",
    ),
]


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def banner(text: str):
    print(f"\n{'═'*60}\n {text}\n{'═'*60}")


def elevenlabs_tts(text: str, voice_id: str, out_mp3: Path) -> Path:
    """Generate speech via ElevenLabs → MP3."""
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


KLING_NEGATIVE = (
    "face distortion, morphing face, changing facial features, different person, "
    "different character, face warp, identity change, deformed face, ugly, "
    "blurry face, extra limbs, anatomy changes, body distortion"
)


def kling_animate(img: Path, motion_prompt: str, audio_dur: float, out: Path) -> Path:
    """
    Use Kling v2.1 image-to-video to animate a static frame.
    Selects 5s or 10s clip based on audio duration.
    Returns path to downloaded animated MP4.
    """
    dur_key = "10" if audio_dur > 5.0 else "5"
    print(f"    [KLING] Uploading image (dur={audio_dur:.1f}s → {dur_key}s clip)...")

    image_url = fal_client.upload_file(str(img))

    print(f"    [KLING] Running Kling v2.1 image-to-video...")
    result = fal_client.subscribe(
        "fal-ai/kling-video/v2.1/standard/image-to-video",
        arguments={
            "image_url": image_url,
            "prompt": motion_prompt,
            "negative_prompt": KLING_NEGATIVE,
            "duration": dur_key,
            "aspect_ratio": "9:16",
        },
        with_logs=True,
        on_queue_update=lambda u: print(f"      Kling: {u.status}" if hasattr(u, "status") else ""),
    )

    video_url = result["video"]["url"]
    print(f"    [KLING] Done → {video_url}")
    r = requests.get(video_url, timeout=180)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def lipsync(animated_video: Path, audio_wav: Path, out: Path) -> Path:
    """Run FAL sync-lipsync on the animated clip — mouth follows voice."""
    print("    [LIPSYNC] Uploading animated video + audio...")
    video_url = fal_client.upload_file(str(animated_video))
    audio_url = fal_client.upload_file(str(audio_wav))

    print("    [LIPSYNC] Running sync-lipsync on animated clip...")
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
    print(f"    [LIPSYNC] Done → {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


def mux_audio(video: Path, mp3: Path, out: Path) -> Path:
    """
    Combine animated video with audio (for product scenes with no face).
    Trims video to audio duration if needed, or loops if video is shorter.
    """
    dur = audio_duration(Path(mp3))
    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(video),   # loop video if needed
        "-i", str(mp3),
        "-map", "0:v", "-map", "1:a",
        "-t", str(dur),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-pix_fmt", "yuv420p",
        str(out),
    ], check=True, capture_output=True)
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
    list_file = out.parent / "concat_v2.txt"
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
    work = Path(tempfile.mkdtemp(prefix="xpel_v2_"))
    print(f"Working dir: {work}")

    normalized_clips: list[Path] = []

    for i, (frame_file, voice_id, has_face, line, motion_prompt) in enumerate(SCENES, 1):
        frame_path = FRAMES_DIR / frame_file
        if not frame_path.exists():
            sys.exit(f"ERROR: Missing frame: {frame_path}")

        scene_type = "GUY (animate+lipsync)" if has_face else "PRODUCT (animate+mux)"
        banner(f"SCENE {i}/{len(SCENES)}  [{scene_type}]")
        print(f" Frame: {frame_file}")
        print(f" Line:  {line[:80]}...")

        # 1 — Voice
        print("  [1/4] Generating voice...")
        mp3 = work / f"scene_{i}.mp3"
        wav = work / f"scene_{i}.wav"
        elevenlabs_tts(line, voice_id, mp3)
        mp3_to_wav(mp3, wav)
        dur = audio_duration(wav)
        print(f"        Duration: {dur:.1f}s")

        # 2 — Kling v2.1: static frame → smooth animated clip
        print("  [2/4] Animating frame with Kling v2.1...")
        animated = work / f"scene_{i}_animated.mp4"
        kling_animate(frame_path, motion_prompt, dur, animated)

        # 3 — Lip-sync (face scenes) or audio mux (product scenes)
        if has_face:
            print("  [3/4] Lip-syncing animated clip...")
            synced = work / f"scene_{i}_synced.mp4"
            lipsync(animated, wav, synced)
        else:
            print("  [3/4] Muxing audio onto animated product clip...")
            synced = work / f"scene_{i}_synced.mp4"
            mux_audio(animated, mp3, synced)

        # 4 — Normalize to 1080x1920
        print("  [4/4] Normalizing to 1080x1920...")
        norm = work / f"scene_{i}_norm.mp4"
        normalize(synced, norm)
        normalized_clips.append(norm)

        print(f"  Scene {i} ✅")

    # Final assembly
    banner("FINAL ASSEMBLY — HARD CUTS")
    final = OUTPUT_DIR / "xpel_ad_v2.mp4"
    concat(normalized_clips, final)

    size = final.stat().st_size / 1024 / 1024
    banner(f"DONE  →  {final}  ({size:.1f} MB)")
    print(f"  Play: vlc {final}\n")


if __name__ == "__main__":
    main()
