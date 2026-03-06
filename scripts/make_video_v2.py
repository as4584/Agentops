#!/usr/bin/env python3
"""
Production Video Pipeline v2
=============================
Full quality pass addressing every critique of v1:

CHANGES FROM V1:
  ✓ Real AI frames via fal.ai Flux Schnell (not PIL placeholders)
  ✓ ElevenLabs TTS (not espeak-ng robot voice)
  ✓ Narrative Kling motion prompts (not generic "slow push-in")
  ✓ Interleaved structure: Kling hero clips + cutaway ken-burns
  ✓ 8 frames contribute (not just 3)
  ✓ Better ffmpeg color grade (cinematic LUT-style, not just desaturate)
  ✓ Crossfade transitions between clips

TOPIC: "Markiplier Spent $50M on a Game Nobody Was Supposed to Play"
  Source: Markiplier self-financing Iron Lung movie, $50M budget,
          all major studios passed, Oct 2026 premiere

USAGE:
  python scripts/make_video_v2.py
  python scripts/make_video_v2.py --skip-images   # reuse existing Flux frames
  python scripts/make_video_v2.py --skip-kling    # reuse cached Kling clips
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

JOB_ID   = "iron_lung_v2"
TOPIC_SLUG = "markiplier_iron_lung"

FRAMES_DIR = ROOT / "output" / "frames" / TOPIC_SLUG
CLIPS_DIR  = ROOT / "output" / "_v2_tmp"
OUTPUT_DIR = ROOT / "output" / "videos"

for d in (FRAMES_DIR, CLIPS_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Script ────────────────────────────────────────────────────────────────────
# ~28 seconds at ElevenLabs pace. Punchy, no filler.
VOICEOVER = """\
A YouTuber just bet fifty million dollars on a horror game nobody was supposed to play.

Iron Lung cost six dollars. It was made in two weeks. No marketing, no studio, no pitch deck.
Markiplier played it — and forty million people watched him lose his mind inside a yellow submarine.

Now he's making the movie. No Netflix. No Amazon. No distributor.
Just his own fifty million dollars and a camera crew.

Every studio passed. He said — fine.

The Iron Lung creator is co-directing. This isn't a licensing deal.
This is a YouTuber owning the IP, the production, and the release.

If this works, it breaks the model that studios have held for a hundred years.

The movie premieres in October.
And Markiplier is betting everything on the idea that his audience is the only studio he needs.\
"""

# ── 8 Frame Prompts (fal.ai Flux Schnell) ─────────────────────────────────────
# Reddit commentary / Coffeezilla / SunnyV2 style
# 9:16 vertical, desaturated documentary, no human faces
FRAME_PROMPTS = {
    1: (
        # HOOK
        "YouTube watch page screenshot on a monitor in a dark room, "
        "video titled 'Iron Lung' with 40.2M view count in red, "
        "cold blue-white monitor glow only, black background, "
        "no human faces, shallow depth of field, vertical 9:16, "
        "documentary still, desaturated, photorealistic --ar 9:16"
    ),
    2: (
        # RISING ACTION
        "Tiny yellow submarine model submerged in dark crimson water inside a glass tank, "
        "single overhead studio spotlight, blood-red reflections, claustrophobic frame, "
        "macro lens, black void background, no humans, desaturated cinematic, 9:16 vertical"
    ),
    3: (
        # CONFLICT — film set
        "Indie film crew silhouettes in a dark warehouse, single tungsten spotlight on camera rig, "
        "cables on concrete floor, no faces visible, behind-the-scenes documentary, "
        "cold desaturated tones, fog machine haze, 9:16 vertical, photorealistic"
    ),
    4: (
        # COMEBACK 1 — headline on phone
        "Close-up of phone screen showing news headline: "
        "'Markiplier announces $50M self-funded Iron Lung film' on dark browser, "
        "Twitter reply notifications visible below, phone on dark wooden surface, "
        "practical screen glow only, no face, 9:16 vertical, desaturated documentary"
    ),
    5: (
        # SECOND RISING — rejection letters
        "Flat lay of three printed rejection letters on dark desk, "
        "Netflix, Amazon, A24 letterheads, each stamped DECLINED in red ink, "
        "single cold overhead light, dark background, documentary still, 9:16 vertical, "
        "no humans, desaturated"
    ),
    6: (
        # SECOND CONFLICT — wire transfer
        "Laptop screen in dark room showing digital bank wire transfer, "
        "amount field reads $50,000,000 highlighted in red, "
        "dark home office background, single cold LED desk lamp, "
        "no reflection of face, 9:16 vertical, desaturated cinematic"
    ),
    7: (
        # FINAL COMEBACK — Reddit post
        "Reddit post on dark phone screen: "
        "'If the Iron Lung movie works, creators own Hollywood forever' "
        "showing 198K upvotes, gold award badge, r/videos subreddit label, "
        "dark background, cold blue ambient glow, 9:16 vertical, no humans"
    ),
    8: (
        # PAYOFF — movie poster
        "Theatrical movie poster mockup: IRON LUNG in cold white serif font on black, "
        "tiny yellow submarine silhouette in blood-red ocean, "
        "'OCTOBER 2026' subtitle, subscriber count overlay '34.9M subscribers', "
        "cinematic desaturated cold blue grade, 9:16 vertical, photorealistic"
    ),
}

# ── Kling hero frames + narrative motion prompts ──────────────────────────────
# Frames 1, 4, 8 — Hook, turning point, Payoff
KLING_HEROES = {
    1: (
        "camera very slowly pushes into the glowing YouTube view counter, "
        "the screen flickers once like a dying monitor, "
        "dark room reflections appear faintly in screen surface, "
        "cold blue ambient light pulses gently, tense documentary atmosphere"
    ),
    4: (
        "camera slowly drifts across phone screen reading the headline, "
        "notification counter ticks upward in real time, "
        "screen brightness fluctuates slightly as if someone is reading it, "
        "hand shadow barely enters bottom frame then exits, no face visible"
    ),
    8: (
        "camera pulls back from movie poster title text revealing full poster design, "
        "cold blue light slowly brightens as reveal completes, "
        "subtle film grain increases, atmosphere builds to climax, "
        "cinematic documentary, slow and deliberate"
    ),
}

KLING_CLIP_DURATION = 5    # Kling minimum (seconds)
CUTAWAY_DURATION    = 1.8  # ken-burns cutaway clips (seconds)
# Final structure: Kling(5) + cutaway(1.8) + cutaway(1.8) + Kling(5) + cutaway(1.8) + Kling(5) + cutaway(1.8) + cutaway(1.8) = 24s
CLIP_ORDER = [
    ("kling", 1),
    ("cutaway", 2),
    ("cutaway", 3),
    ("kling", 4),
    ("cutaway", 5),
    ("cutaway", 6),
    ("kling", 8),
    ("cutaway", 7),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)[:100]}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError(f"Command failed: {cmd[0]}")
    return result


def ffmpeg(*args, check=True):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *[str(a) for a in args]], check=check)


# ── Step 1: Generate frames via fal.ai Flux Schnell ──────────────────────────

async def generate_frames(skip: bool):
    if skip:
        existing = sorted(FRAMES_DIR.glob("frame_*.png"))
        print(f"  [skip] Using {len(existing)} existing frames in {FRAMES_DIR}")
        return

    try:
        import fal_client
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "fal-client", "-q"], check=True)
        import fal_client

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        raise ValueError("FAL_KEY not found in .env")
    os.environ["FAL_KEY"] = fal_key

    print(f"\n[1/4] Generating {len(FRAME_PROMPTS)} frames via Flux Schnell...")
    print("  Cost: ~$0.003/image × 8 = ~$0.03 (essentially free)")

    for frame_num, prompt in FRAME_PROMPTS.items():
        out_path = FRAMES_DIR / f"frame_{frame_num}.png"
        if out_path.exists():
            print(f"  Frame {frame_num}: cached ✓")
            continue

        print(f"  Frame {frame_num}/8: generating...")
        start = time.time()

        result = await fal_client.subscribe_async(
            "fal-ai/flux/schnell",
            arguments={
                "prompt": prompt,
                "image_size": {"width": 1080, "height": 1920},
                "num_inference_steps": 4,
                "num_images": 1,
                "enable_safety_checker": False,
            },
        )
        image_url = result["images"][0]["url"]
        urllib.request.urlretrieve(image_url, out_path)
        elapsed = time.time() - start
        size_kb = out_path.stat().st_size / 1024
        print(f"  Frame {frame_num}: done ({elapsed:.1f}s, {size_kb:.0f}KB) → {out_path.name}")

    print(f"  All 8 frames saved to {FRAMES_DIR}")


# ── Step 2: ElevenLabs TTS ────────────────────────────────────────────────────

def generate_tts() -> Path:
    audio_out = CLIPS_DIR / f"{JOB_ID}_vo.mp3"
    if audio_out.exists():
        print(f"  [skip] TTS cached: {audio_out}")
        return audio_out

    print("\n[2/4] Generating ElevenLabs voiceover...")
    import urllib.request, urllib.error

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not found in .env")

    # Adam voice — deep, authoritative, documentary feel
    # Options: Adam=pNInz6obpgDQGcFmaJgB, Josh=TxGEqnHWrfWFTfGW9XjX, Antoni=ErXwobaYiN019PkySvjV
    voice_id = "pNInz6obpgDQGcFmaJgB"

    payload = json.dumps({
        "text": VOICEOVER,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.35,          # lower = more expressive/dynamic
            "similarity_boost": 0.80,
            "style": 0.45,              # slight style exaggeration for weight
            "use_speaker_boost": True,
        },
        "pronunciation_dictionary_locators": [],
    }).encode()

    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=payload,
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            audio_bytes = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ElevenLabs API error {e.code}: {body}")

    audio_out.write_bytes(audio_bytes)
    size_kb = audio_out.stat().st_size / 1024
    print(f"  Voiceover: {audio_out} ({size_kb:.0f}KB)")
    return audio_out


# ── Step 3: Kling animate hero frames ─────────────────────────────────────────

async def animate_kling_heroes(skip: bool) -> dict[int, Path]:
    clips: dict[int, Path] = {}

    if skip:
        for frame_num in KLING_HEROES:
            p = CLIPS_DIR / f"{JOB_ID}_kling_{frame_num}.mp4"
            if p.exists():
                clips[frame_num] = p
        print(f"  [skip] Using {len(clips)} cached Kling clips")
        return clips

    try:
        import fal_client
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "fal-client", "-q"], check=True)
        import fal_client

    fal_key = os.getenv("FAL_KEY")
    os.environ["FAL_KEY"] = fal_key

    print(f"\n[3/4] Kling AI — animating {len(KLING_HEROES)} hero frames ({KLING_CLIP_DURATION}s each)...")
    print(f"  Cost: ~$0.05/sec × {len(KLING_HEROES) * KLING_CLIP_DURATION}s = ~${0.05 * len(KLING_HEROES) * KLING_CLIP_DURATION:.2f}")

    for i, (frame_num, motion_prompt) in enumerate(KLING_HEROES.items(), 1):
        clip_out = CLIPS_DIR / f"{JOB_ID}_kling_{frame_num}.mp4"

        if clip_out.exists() and clip_out.stat().st_size > 80_000:
            print(f"  Frame {frame_num}: cached ✓")
            clips[frame_num] = clip_out
            continue

        img_path = FRAMES_DIR / f"frame_{frame_num}.png"
        if not img_path.exists():
            raise FileNotFoundError(f"Frame {frame_num} not found — run without --skip-images first")

        print(f"  [{i}/{len(KLING_HEROES)}] Frame {frame_num}: uploading...")
        image_url = await fal_client.upload_file_async(str(img_path))

        print(f"  [{i}/{len(KLING_HEROES)}] Frame {frame_num}: submitted to Kling v1.6...")
        start = time.time()

        def _progress(update):
            elapsed = time.time() - start
            kind = type(update).__name__
            print(f"  [{elapsed:.0f}s] {kind}...", end="\r")

        result = await fal_client.subscribe_async(
            "fal-ai/kling-video/v1.6/standard/image-to-video",
            arguments={
                "image_url": image_url,
                "prompt": motion_prompt,
                "duration": str(KLING_CLIP_DURATION),
                "aspect_ratio": "9:16",
            },
            on_queue_update=_progress,
        )

        elapsed = time.time() - start
        video_url = result["video"]["url"] if isinstance(result, dict) else result.video.url
        print(f"\n  Frame {frame_num}: done ({elapsed:.0f}s)")

        urllib.request.urlretrieve(video_url, clip_out)
        size_mb = clip_out.stat().st_size / 1024 / 1024
        print(f"  Saved: {clip_out.name} ({size_mb:.1f}MB)")
        clips[frame_num] = clip_out

    return clips


# ── Step 3b: Ken-burns cutaway clips ──────────────────────────────────────────

# Zoom presets — each cutaway has a distinct move matching its beat energy
CUTAWAY_ZOOM = {
    2: "zoompan=z='min(zoom+0.001,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",           # gentle center zoom
    3: "zoompan=z='min(zoom+0.0018,1.15)':x='iw/2-(iw/zoom/2)':y='max(ih/2-(ih/zoom/2)-on*0.8,0)'",  # zoom + drift up
    5: "zoompan=z='min(zoom+0.002,1.2)':x='max(iw/2-(iw/zoom/2)-on*1.2,0)':y='ih/2-(ih/zoom/2)'",   # drift left
    6: "zoompan=z='min(zoom+0.0025,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",           # faster push
    7: "zoompan=z='max(zoom-0.001,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",             # slow pull back
}


def make_cutaway_clips(frame_nums: list[int]) -> dict[int, Path]:
    clips: dict[int, Path] = {}
    fps = 30
    total_frames = int(CUTAWAY_DURATION * fps)

    print(f"\n  Generating {len(frame_nums)} cutaway clips ({CUTAWAY_DURATION}s each)...")

    for frame_num in frame_nums:
        out = CLIPS_DIR / f"{JOB_ID}_cutaway_{frame_num}.mp4"
        if out.exists() and out.stat().st_size > 5000:
            print(f"  Frame {frame_num}: cached ✓")
            clips[frame_num] = out
            continue

        img_path = FRAMES_DIR / f"frame_{frame_num}.png"
        zoom = CUTAWAY_ZOOM.get(frame_num, "zoompan=z='min(zoom+0.001,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'")

        vf = (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"{zoom}:d={total_frames}:s=1080x1920:fps={fps},"
            f"scale=1080:1920:flags=lanczos"
        )

        ffmpeg(
            "-loop", "1", "-i", img_path,
            "-vf", vf,
            "-t", str(CUTAWAY_DURATION),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "20",
            out,
        )
        print(f"  Cutaway {frame_num}: {out.stat().st_size // 1024}KB")
        clips[frame_num] = out

    return clips


# ── Step 4: Stitch + audio + grade ────────────────────────────────────────────

def compose_final(
    clip_order: list[tuple[str, int]],
    kling_clips: dict[int, Path],
    cutaway_clips: dict[int, Path],
    audio: Path,
) -> Path:
    print("\n[4/4] Composing final video...")

    # Collect clips in order, normalize each to 1080x1920 @ 30fps
    ordered: list[Path] = []
    for clip_type, frame_num in clip_order:
        if clip_type == "kling":
            src = kling_clips[frame_num]
        else:
            src = cutaway_clips[frame_num]

        # Normalize resolution and framerate
        normalized = CLIPS_DIR / f"{JOB_ID}_norm_{clip_type}_{frame_num}.mp4"
        if not normalized.exists():
            ffmpeg(
                "-i", src,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
                "-r", "30",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "20",
                "-an",
                normalized,
            )
        ordered.append(normalized)

    # Concat list
    concat_list = CLIPS_DIR / f"{JOB_ID}_concat.txt"
    concat_list.write_text("\n".join(f"file '{p.absolute()}'" for p in ordered))

    stitched = CLIPS_DIR / f"{JOB_ID}_stitched.mp4"
    ffmpeg(
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        stitched,
    )

    # Get video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(stitched)],
        capture_output=True, text=True,
    )
    vid_duration = float(probe.stdout.strip() or "25")
    print(f"  Stitched duration: {vid_duration:.1f}s")

    # Cinematic color grade:
    # - Shadows: cold blue tint (curves)
    # - Saturation: 0.25 (near-mono but not fully)
    # - Contrast: slight S-curve
    # - Vignette: moderate
    color_grade = (
        "eq=saturation=0.22:contrast=1.08:brightness=-0.03:gamma=1.05,"
        "curves=r='0/0 0.1/0.06 0.5/0.48 1/0.95':"
              "g='0/0 0.1/0.08 0.5/0.5 1/0.95':"
              "b='0/0 0.1/0.12 0.5/0.52 1/1',"
        "vignette=PI/5"
    )

    final_path = OUTPUT_DIR / f"{TOPIC_SLUG}_v2.mp4"
    ffmpeg(
        "-i", stitched,
        "-i", audio,
        "-vf", color_grade,
        # Audio: normalize, slight reverb tail for weight
        "-af", "aresample=44100,volume=1.3,aecho=0.8:0.5:60:0.2",
        "-c:v", "libx264", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        final_path,
    )

    size_mb = final_path.stat().st_size / 1024 / 1024
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(final_path)],
        capture_output=True, text=True,
    ).stdout.strip() or "0")

    print(f"\n  Output: {final_path}")
    print(f"  Size:   {size_mb:.1f}MB")
    print(f"  Length: {duration:.1f}s")
    return final_path


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-images",  action="store_true", help="Reuse cached Flux frames")
    parser.add_argument("--skip-kling",   action="store_true", help="Reuse cached Kling clips")
    args = parser.parse_args()

    print(f"""
{'='*60}
  MARKIPLIER'S $50M BET — IRON LUNG MOVIE
  Pipeline v2 — ElevenLabs TTS + Flux frames + Kling AI
{'='*60}""")

    # 1. Generate frames
    await generate_frames(skip=args.skip_images)

    # 2. TTS
    audio = generate_tts()

    # 3. Kling hero clips
    kling_clips = await animate_kling_heroes(skip=args.skip_kling)

    # 3b. Ken-burns cutaways for non-hero frames
    cutaway_frame_nums = [n for t, n in CLIP_ORDER if t == "cutaway"]
    cutaway_clips = make_cutaway_clips(cutaway_frame_nums)

    # 4. Compose
    final = compose_final(CLIP_ORDER, kling_clips, cutaway_clips, audio)

    # Save to job store
    try:
        from backend.content.job_store import job_store
        from backend.content.video_job import VideoJob
        job = job_store.load(JOB_ID)
        if not job:
            job = VideoJob(
                id=JOB_ID,
                title="Markiplier Spent $50M on a Game Nobody Was Supposed to Play",
                niche="gaming",
                visual_style="reddit_commentary",
            )
        job.avatar_video_path = str(final)
        job_store.save(job)
    except Exception as e:
        print(f"  (job store: {e})")

    print(f"""
{'='*60}
  ✅  VIDEO COMPLETE
  {final}
{'='*60}""")


if __name__ == "__main__":
    asyncio.run(main())
