"""
AI Video Generator — Minecraft Pro Tips
========================================
Uses Zeroscope V2 576w (open weights, free, 3.8GB, fits RTX 4070 8GB).
Generates 3 x 5-second AI video clips then stitches them to ~15 seconds.
Pipeline:
  1. Ollama (local LLM)       → script + 3 video prompts
  2. Zeroscope V2 576w (GPU)  → 3 real AI video clips
  3. espeak-ng (local TTS)    → voice audio
  4. ffmpeg                   → stitch clips + overlay audio + title card

Cost: $0.00
Output: output/videos/minecraft_ai_pro_tips.mp4
"""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output" / "videos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_PATH  = OUTPUT_DIR / "mc_ai_audio.wav"
FINAL_PATH  = OUTPUT_DIR / "minecraft_ai_pro_tips.mp4"

MODEL_ID = "cerspense/zeroscope_v2_576w"

# ---------------------------------------------------------------------------
# Step 1: Generate script + 3 visual prompts via Ollama (free/local)
# ---------------------------------------------------------------------------

def generate_script_and_prompts() -> tuple[str, list[str]]:
    print("🧠 Generating script + video prompts via local LLM...")

    payload = {
        "model": "llama3.2",
        "prompt": (
            "You are a social media video director. "
            "Create content for a 15-second TikTok: 'How to Become a Pro at Minecraft'.\n\n"
            "Return ONLY valid JSON with exactly these keys:\n"
            "{\n"
            '  "script": "<punchy spoken script under 60 words>",\n'
            '  "prompts": [\n'
            '    "<cinematic video prompt for Minecraft scene 1, 15 words max>",\n'
            '    "<cinematic video prompt for Minecraft scene 2, 15 words max>",\n'
            '    "<cinematic video prompt for Minecraft scene 3, 15 words max>"\n'
            "  ]\n"
            "}\n\n"
            "Make prompts vivid and visual. No hashtags. Return JSON only."
        ),
        "stream": False,
        "format": "json",
    }

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://localhost:11434/api/generate",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        parsed = json.loads(data.get("response", "{}"))
        script  = parsed.get("script", "").strip()
        prompts = parsed.get("prompts", [])
        if script and len(prompts) == 3:
            print(f"✅ Script: {script[:80]}...")
            for i, p in enumerate(prompts):
                print(f"   Prompt {i+1}: {p}")
            return script, prompts
    except Exception as e:
        print(f"⚠️  LLM parse failed ({e}), using fallback")

    return (
        "Want to become a Minecraft pro? Master these three skills: "
        "resource gathering, smart building, and combat strategy. "
        "Start underground, carry a water bucket, and never dig straight down. "
        "Apply these and you will dominate every world.",
        [
            "aerial view of Minecraft blocky landscape at golden sunset, cinematic",
            "Minecraft player building a massive stone castle underground by torchlight",
            "epic Minecraft sword combat against Ender Dragon, dramatic lighting",
        ],
    )


# ---------------------------------------------------------------------------
# Step 2: Generate AI video clips using CogVideoX-2b
# ---------------------------------------------------------------------------

def generate_ai_clips(prompts: list[str]) -> list[Path]:
    print(f"\n🎬 Loading Zeroscope V2 576w on GPU ({torch.cuda.get_device_name(0)})...")

    from diffusers import DiffusionPipeline
    from diffusers.utils import export_to_video

    pipe = DiffusionPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        use_safetensors=False,        # model uses .bin format
    )
    pipe = pipe.to("cuda")
    pipe.enable_attention_slicing()   # reduce peak VRAM

    clip_paths: list[Path] = []

    for i, prompt in enumerate(prompts):
        clip_path = OUTPUT_DIR / f"mc_clip_{i+1}.mp4"
        print(f"\n  🎥 Generating clip {i+1}/3: \"{prompt[:60]}\"")

        video_frames = pipe(
            prompt=prompt,
            num_inference_steps=25,
            height=320,
            width=576,
            num_frames=40,            # ~5 seconds at 8fps
            guidance_scale=7.5,
            generator=torch.Generator(device="cuda").manual_seed(42 + i),
        ).frames[0]

        export_to_video(video_frames, str(clip_path), fps=8)
        print(f"  ✅ Clip {i+1} saved: {clip_path}")
        clip_paths.append(clip_path)

        # Free VRAM between clips
        gc.collect()
        torch.cuda.empty_cache()

    # Unload model
    del pipe
    gc.collect()
    torch.cuda.empty_cache()

    return clip_paths


# ---------------------------------------------------------------------------
# Step 3: Generate voice audio via espeak-ng
# ---------------------------------------------------------------------------

def generate_audio(script: str) -> bool:
    print("\n🎙️  Generating voice with espeak-ng...")
    try:
        result = subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "145", "-p", "45", "-a", "180",
             "-w", str(AUDIO_PATH), script],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and AUDIO_PATH.exists():
            print(f"✅ Audio: {AUDIO_PATH}")
            return True
        print(f"❌ espeak-ng failed: {result.stderr.decode()[:200]}")
        return False
    except FileNotFoundError:
        print("❌ espeak-ng not found. Run: apt install espeak-ng")
        return False


# ---------------------------------------------------------------------------
# Step 4: Stitch clips + overlay title + add audio via ffmpeg
# ---------------------------------------------------------------------------

def stitch_and_compose(clip_paths: list[Path], script: str) -> bool:
    print("\n✂️  Stitching clips + composing final video with ffmpeg...")

    # Write concat list
    concat_file = OUTPUT_DIR / "concat_list.txt"
    with open(concat_file, "w") as f:
        for cp in clip_paths:
            f.write(f"file '{cp.resolve()}'\n")

    stitched = OUTPUT_DIR / "mc_stitched.mp4"

    # Step 1: Concatenate clips
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(stitched),
    ]
    r = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"❌ Concat failed: {r.stderr[-300:]}")
        return False

    # Step 2: Get stitched video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(stitched)],
        capture_output=True, text=True, timeout=10,
    )
    vid_duration = 15.0
    try:
        vid_duration = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        pass

    # Step 3: Title overlay text
    title1 = "HOW TO BECOME A"
    title2 = "MINECRAFT PRO"
    lines  = textwrap.wrap(script, width=34)[:4]

    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:").replace("%", "\\%")

    filters = [
        f"scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        f"drawtext=text='{esc(title1)}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.65:boxborderw=10",
        f"drawtext=text='{esc(title2)}':fontcolor=0x55FF55:fontsize=72:x=(w-text_w)/2:y=185:box=1:boxcolor=black@0.7:boxborderw=10",
    ]
    for i, line in enumerate(lines):
        y = 1500 + i * 68
        filters.append(
            f"drawtext=text='{esc(line)}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y={y}:box=1:boxcolor=black@0.5:boxborderw=6"
        )

    vf = ",".join(filters)

    # Step 4: Compose with audio
    if AUDIO_PATH.exists():
        final_cmd = [
            "ffmpeg", "-y",
            "-i", str(stitched),
            "-i", str(AUDIO_PATH),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(FINAL_PATH),
        ]
    else:
        final_cmd = [
            "ffmpeg", "-y",
            "-i", str(stitched),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(FINAL_PATH),
        ]

    r2 = subprocess.run(final_cmd, capture_output=True, text=True, timeout=180)
    if r2.returncode == 0 and FINAL_PATH.exists():
        size_mb = FINAL_PATH.stat().st_size / (1024 * 1024)
        print(f"✅ Final video: {FINAL_PATH} ({size_mb:.1f} MB, {vid_duration:.1f}s)")
        return True

    print(f"❌ Final compose failed: {r2.stderr[-300:]}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"🚀 Minecraft AI Video Generator (Zeroscope V2) — $0.00\n")

    if not torch.cuda.is_available():
        print("❌ CUDA not available. GPU required for CogVideoX.")
        sys.exit(1)

    print(f"🖥️  GPU: {torch.cuda.get_device_name(0)} | "
          f"VRAM: {torch.cuda.get_device_properties(0).total_memory // 1024**2} MB\n")

    script, prompts = generate_script_and_prompts()

    print("\n--- SCRIPT ---")
    print(script)
    print("--------------")

    clip_paths = generate_ai_clips(prompts)

    generate_audio(script)

    if not stitch_and_compose(clip_paths, script):
        print("\n❌ Final stitch failed.")
        sys.exit(1)

    print(f"\n✅ DONE! AI video ready at:\n   {FINAL_PATH}\n")
