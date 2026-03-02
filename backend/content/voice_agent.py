"""
VoiceAgent — Generates spoken audio from scripts.
==================================================
Uses local TTS options:
  1. Piper TTS (fully local, fast, good quality)
  2. Coqui TTS (local, supports voice cloning)
  3. ElevenLabs API (optional, if configured)

Default: Piper TTS — runs entirely on your machine.
"""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

AUDIO_DIR = MEMORY_DIR / "content_audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


class VoiceAgent(ContentAgent):
    name = "VoiceAgent"
    trigger_status = JobStatus.GENERATED

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] Generating audio for {job.job_id}")

        spoken_text = self._clean_for_tts(job.script)
        audio_path = AUDIO_DIR / f"{job.job_id}.wav"

        # Try backends in order of preference
        success = False

        if self._has_piper():
            success = self._generate_piper(spoken_text, audio_path)
        elif self._has_coqui():
            success = self._generate_coqui(spoken_text, audio_path)
        elif self._has_espeak():
            success = self._generate_espeak(spoken_text, audio_path)

        if not success:
            raise RuntimeError(
                "No TTS backend available. Install one:\n"
                "  - Piper: pip install piper-tts\n"
                "  - Coqui: pip install TTS\n"
                "  - eSpeak: sudo apt install espeak-ng"
            )

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.AUDIO_READY,
            voice_audio_path=str(audio_path),
            final_transcript=spoken_text,
        )

        logger.info(f"[{self.name}] Audio saved: {audio_path}")
        return updated

    def _clean_for_tts(self, script: str) -> str:
        """Remove format labels, keep spoken content."""
        labels = {"HOOK:", "PROBLEM:", "FRAMEWORK:", "EXAMPLE:", "CTA:"}
        lines = []
        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "---":
                continue
            for label in labels:
                if stripped.upper().startswith(label):
                    stripped = stripped[len(label):].strip()
                    break
            if stripped and stripped[0].isdigit() and len(stripped) > 2 and stripped[1] == ".":
                stripped = stripped[2:].strip()
            if stripped:
                lines.append(stripped)
        return " ".join(lines)

    # ── TTS Backends ─────────────────────────────────────

    def _has_piper(self) -> bool:
        return shutil.which("piper") is not None

    def _has_coqui(self) -> bool:
        try:
            import TTS  # noqa: F401
            return True
        except ImportError:
            return False

    def _has_espeak(self) -> bool:
        return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None

    def _generate_piper(self, text: str, output: Path) -> bool:
        """Generate audio using Piper TTS (fully local)."""
        try:
            cmd = [
                "piper",
                "--model", "en_US-lessac-medium",
                "--output_file", str(output),
            ]
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and output.exists():
                logger.info(f"[{self.name}] Piper TTS success")
                return True
            logger.warning(f"[{self.name}] Piper failed: {result.stderr}")
            return False
        except Exception as e:
            logger.warning(f"[{self.name}] Piper error: {e}")
            return False

    def _generate_coqui(self, text: str, output: Path) -> bool:
        """Generate audio using Coqui TTS (local, supports cloning)."""
        try:
            from TTS.api import TTS as CoquiTTS
            tts = CoquiTTS(model_name="tts_models/en/ljspeech/tacotron2-DDC")
            tts.tts_to_file(text=text, file_path=str(output))
            logger.info(f"[{self.name}] Coqui TTS success")
            return True
        except Exception as e:
            logger.warning(f"[{self.name}] Coqui error: {e}")
            return False

    def _generate_espeak(self, text: str, output: Path) -> bool:
        """Generate audio using eSpeak-NG (basic but always available)."""
        try:
            espeak = shutil.which("espeak-ng") or shutil.which("espeak")
            cmd = [espeak, "-w", str(output), text]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and output.exists():
                logger.info(f"[{self.name}] eSpeak TTS success")
                return True
            return False
        except Exception as e:
            logger.warning(f"[{self.name}] eSpeak error: {e}")
            return False
