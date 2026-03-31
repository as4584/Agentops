"""
CaptionAgent — Burns captions into video + ensures 9:16 format.
===============================================================
Uses FFmpeg (local). No cloud dependency.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from backend.config import MEMORY_DIR
from backend.content.base_agent import ContentAgent
from backend.content.video_job import JobStatus, VideoJob
from backend.utils import logger

VIDEO_DIR = MEMORY_DIR / "content_video"


class CaptionAgent(ContentAgent):
    name = "CaptionAgent"
    trigger_status = JobStatus.VIDEO_READY

    FONT_SIZE = 24
    OUTLINE_WIDTH = 2
    MARGIN_BOTTOM = 60

    async def process(self, job: VideoJob) -> VideoJob | None:
        logger.info(f"[{self.name}] Adding captions to {job.job_id}")

        input_video = Path(job.avatar_video_path)
        if not input_video.exists():
            raise FileNotFoundError(f"Avatar video not found: {input_video}")

        srt_path = self._generate_srt(job)
        output_path = VIDEO_DIR / f"{job.job_id}_captioned.mp4"
        self._burn_captions(input_video, srt_path, output_path)

        duration = self._get_duration(output_path)
        logger.info(f"[{self.name}] Captioned: {output_path} ({duration:.1f}s)")

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.CAPTIONED,
            captioned_video_path=str(output_path),
        )
        return updated

    def _generate_srt(self, job: VideoJob) -> Path:
        text = job.final_transcript or job.script
        if not text:
            raise ValueError(f"Job {job.job_id} has no transcript or script")

        words = text.split()
        words_per_sub = 6
        sub_duration = words_per_sub / 2.5  # ~2.5 words/sec

        srt_lines = []
        idx = 1
        t = 0.0
        for i in range(0, len(words), words_per_sub):
            chunk = " ".join(words[i : i + words_per_sub])
            start = self._srt_time(t)
            end = self._srt_time(t + sub_duration)
            srt_lines.extend([str(idx), f"{start} --> {end}", chunk, ""])
            idx += 1
            t += sub_duration

        srt_path = VIDEO_DIR / f"{job.job_id}.srt"
        srt_path.write_text("\n".join(srt_lines))
        return srt_path

    @staticmethod
    def _srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _burn_captions(self, input_v: Path, srt: Path, output: Path) -> None:
        sub_filter = (
            f"subtitles='{srt}':"
            f"force_style='FontSize={self.FONT_SIZE},"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"Outline={self.OUTLINE_WIDTH},"
            f"Alignment=2,"
            f"MarginV={self.MARGIN_BOTTOM}'"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_v),
            "-vf",
            (
                "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
                f"{sub_filter}"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:300]}")

    @staticmethod
    def _get_duration(path: Path) -> float:
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
        except Exception:
            return 0.0
