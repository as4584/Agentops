"""
AvatarVideoAgent — Generates talking-head video from audio.
============================================================
Local-first approach:
  1. SadTalker (fully local face animation)
  2. Wav2Lip (local lip-sync)
  3. Static image + audio composite (fallback)

No cloud API required for basic operation.
Optional: HeyGen API if HEYGEN_API_KEY is set.
"""

from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

VIDEO_DIR = MEMORY_DIR / "content_video"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_IMAGE_PATH = MEMORY_DIR / "avatar" / "creator.png"


class AvatarVideoAgent(ContentAgent):
    name = "AvatarVideoAgent"
    trigger_status = JobStatus.AUDIO_READY

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] Generating video for {job.job_id}")

        audio_path = Path(job.voice_audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        video_path = VIDEO_DIR / f"{job.job_id}_avatar.mp4"

        success = False

        # Try local backends
        if self._has_sadtalker():
            success = self._generate_sadtalker(audio_path, video_path)
        elif self._has_wav2lip():
            success = self._generate_wav2lip(audio_path, video_path)

        # Fallback: static image + audio composite
        if not success:
            success = self._generate_static_composite(audio_path, video_path)

        if not success:
            raise RuntimeError(
                "Video generation failed. Ensure ffmpeg is installed:\n"
                "  sudo apt install ffmpeg\n"
                "And optionally place an avatar image at:\n"
                f"  {AVATAR_IMAGE_PATH}"
            )

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.VIDEO_READY,
            avatar_video_path=str(video_path),
        )

        logger.info(f"[{self.name}] Video saved: {video_path}")
        return updated

    # ── Backends ─────────────────────────────────────────

    def _has_sadtalker(self) -> bool:
        return shutil.which("sadtalker") is not None

    def _has_wav2lip(self) -> bool:
        return shutil.which("wav2lip") is not None

    def _generate_sadtalker(self, audio: Path, output: Path) -> bool:
        """Generate talking-head video using SadTalker (local)."""
        if not AVATAR_IMAGE_PATH.exists():
            logger.warning(f"[{self.name}] No avatar image at {AVATAR_IMAGE_PATH}")
            return False
        try:
            cmd = [
                "sadtalker",
                "--driven_audio", str(audio),
                "--source_image", str(AVATAR_IMAGE_PATH),
                "--result_dir", str(output.parent),
                "--still",
                "--preprocess", "crop",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info(f"[{self.name}] SadTalker success")
                return True
            logger.warning(f"[{self.name}] SadTalker failed: {result.stderr[:200]}")
            return False
        except Exception as e:
            logger.warning(f"[{self.name}] SadTalker error: {e}")
            return False

    def _generate_wav2lip(self, audio: Path, output: Path) -> bool:
        """Generate lip-synced video using Wav2Lip (local)."""
        if not AVATAR_IMAGE_PATH.exists():
            return False
        try:
            cmd = [
                "wav2lip",
                "--audio", str(audio),
                "--face", str(AVATAR_IMAGE_PATH),
                "--outfile", str(output),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0
        except Exception:
            return False

    def _generate_static_composite(self, audio: Path, output: Path) -> bool:
        """
        Fallback: Compose a static image (or color background)
        with audio into a 9:16 video using FFmpeg.
        """
        if not shutil.which("ffmpeg"):
            logger.error(f"[{self.name}] ffmpeg not found")
            return False

        try:
            # Get audio duration
            duration = self._get_audio_duration(audio)

            if AVATAR_IMAGE_PATH.exists():
                # Use creator avatar image
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(AVATAR_IMAGE_PATH),
                    "-i", str(audio),
                    "-c:v", "libx264",
                    "-tune", "stillimage",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    str(output),
                ]
            else:
                # Generate plain background with audio
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c=#1a1a2e:s=1080x1920:d={duration}",
                    "-i", str(audio),
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    str(output),
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and output.exists():
                logger.info(f"[{self.name}] Static composite success")
                return True
            logger.warning(f"[{self.name}] FFmpeg failed: {result.stderr[:200]}")
            return False
        except Exception as e:
            logger.warning(f"[{self.name}] Static composite error: {e}")
            return False

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration in seconds via ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", str(audio_path),
            ]
            import json
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 30))
        except Exception:
            return 30.0
