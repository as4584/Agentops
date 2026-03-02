"""
QAAgent — Automated quality assurance using local tools + LLM.
==============================================================
All checks run locally (FFmpeg, difflib). Content policy check
uses the local Ollama LLM instead of cloud moderation APIs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus, QAReport
from backend.config import MEMORY_DIR
from backend.utils import logger

VIDEO_DIR = MEMORY_DIR / "content_video"


class QAAgent(ContentAgent):
    name = "QAAgent"
    trigger_status = JobStatus.CAPTIONED

    LUFS_MIN = -16.0
    LUFS_MAX = -14.0
    MIN_DURATION = 15.0
    MAX_DURATION = 65.0
    MIN_CAPTION_ACCURACY = 0.95

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] QA check on {job.job_id}")

        report = QAReport()
        notes: list[str] = []

        # Audio checks
        if job.voice_audio_path and Path(job.voice_audio_path).exists():
            lufs = self._measure_lufs(job.voice_audio_path)
            report.audio_lufs = lufs
            if lufs is not None:
                ok = self.LUFS_MIN <= lufs <= self.LUFS_MAX
                notes.append(
                    f"{'✅' if ok else '⚠️'} Audio LUFS: {lufs:.1f}"
                )
            clipped = self._check_clipping(job.voice_audio_path)
            report.audio_clipped = clipped
            notes.append("❌ Audio clipping" if clipped else "✅ No clipping")
        else:
            notes.append("⚠️ Audio file missing")

        # Video checks
        vid = job.captioned_video_path
        if vid and Path(vid).exists():
            dur = self._get_duration(vid)
            report.video_duration_sec = dur
            ok = self.MIN_DURATION <= dur <= self.MAX_DURATION
            notes.append(
                f"{'✅' if ok else '❌'} Duration: {dur:.1f}s"
            )
            report.visual_artifacts = self._check_artifacts(vid)
            notes.append(
                "❌ Visual artifacts" if report.visual_artifacts else "✅ No artifacts"
            )
        else:
            notes.append("⚠️ Video file missing")

        # Caption accuracy
        if job.final_transcript:
            srt_path = VIDEO_DIR / f"{job.job_id}.srt"
            if srt_path.exists():
                acc = self._caption_accuracy(job.final_transcript, srt_path)
                report.caption_accuracy = acc
                ok = acc >= self.MIN_CAPTION_ACCURACY
                notes.append(f"{'✅' if ok else '⚠️'} Caption accuracy: {acc:.1%}")

        # Content policy (local LLM)
        policy_ok = await self._check_policy_llm(job.script)
        report.policy_violation = not policy_ok
        notes.append(
            "✅ Content policy OK" if policy_ok else "❌ Policy concern flagged"
        )

        # Verdict
        report.notes = notes
        critical = [
            report.audio_clipped is True,
            report.visual_artifacts is True,
            report.policy_violation is True,
            (report.video_duration_sec is not None
             and not (self.MIN_DURATION <= report.video_duration_sec <= self.MAX_DURATION)),
        ]
        report.passed = not any(critical)

        new_status = JobStatus.QA if report.passed else JobStatus.FAILED
        failure = "" if report.passed else "QA failed: " + "; ".join(
            n for n in notes if n.startswith("❌")
        )

        updated = self.store.transition_job(
            job.job_id, new_status, qa_report=report, failure_reason=failure,
        )

        verdict = "PASSED ✅" if report.passed else "FAILED ❌"
        logger.info(f"[{self.name}] QA {verdict} for {job.job_id}")
        for n in notes:
            logger.info(f"  {n}")

        return updated

    # ── Policy check via local LLM ──────────────────────

    async def _check_policy_llm(self, script: str) -> bool:
        """Use local LLM to check for content policy issues."""
        if not script:
            return True

        try:
            result = await self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a content moderation assistant. "
                            "Check the following script for policy violations: "
                            "medical claims, financial advice guarantees, "
                            "hate speech, misleading claims, or prohibited content.\n"
                            "Respond with ONLY 'PASS' or 'FAIL: <reason>'."
                        ),
                    },
                    {"role": "user", "content": script},
                ],
                temperature=0.1,
                max_tokens=100,
            )
            return result.strip().upper().startswith("PASS")
        except Exception as e:
            logger.warning(f"[{self.name}] LLM policy check failed: {e}")
            # Fail open — if LLM is unavailable, do keyword check
            return self._keyword_policy_check(script)

    def _keyword_policy_check(self, script: str) -> bool:
        banned = [
            "guaranteed results", "get rich quick", "lose weight fast",
            "cure for", "medical advice", "financial advice",
        ]
        lower = script.lower()
        return not any(p in lower for p in banned)

    # ── FFmpeg checks ────────────────────────────────────

    def _measure_lufs(self, path: str) -> Optional[float]:
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            for line in r.stderr.splitlines():
                if '"input_i"' in line:
                    return float(line.split(":")[1].strip().strip('",'))
        except Exception:
            pass
        return None

    def _check_clipping(self, path: str) -> bool:
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", path, "-af", "astats=metadata=1:reset=1", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            return "Number of Clips" in r.stderr
        except Exception:
            return False

    def _get_duration(self, path: str) -> float:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
                capture_output=True, text=True, timeout=30,
            )
            return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
        except Exception:
            return 0.0

    def _check_artifacts(self, path: str) -> bool:
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", path, "-vf", "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            return "blackdetect" in r.stderr.lower()
        except Exception:
            return False

    def _caption_accuracy(self, transcript: str, srt_path: Path) -> float:
        srt_text = " ".join(
            l.strip() for l in srt_path.read_text().splitlines()
            if l.strip() and not l.strip().isdigit() and "-->" not in l
        )
        a = " ".join(transcript.lower().split())
        b = " ".join(srt_text.lower().split())
        return SequenceMatcher(None, a, b).ratio()
