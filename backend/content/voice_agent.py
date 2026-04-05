"""
VoiceAgent — Generates spoken audio from scripts.
==================================================
Uses local open-source TTS backends (no cloud services):
  1. Qwen CosyVoice 2 (best quality, local, 0.5B params)
  2. Piper TTS (fully local, fast, good quality)
  3. Coqui TTS (local, supports voice cloning)
  4. eSpeak-NG (basic fallback, always available)

Default: CosyVoice 2 — runs entirely on your machine.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from backend.config import MEMORY_DIR, QWEN_TTS_MODEL, QWEN_TTS_VOICE
from backend.content.base_agent import ContentAgent
from backend.content.video_job import JobStatus, VideoJob
from backend.utils import logger

AUDIO_DIR = MEMORY_DIR / "content_audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


class VoiceAgent(ContentAgent):
    name = "VoiceAgent"
    trigger_status = JobStatus.GENERATED

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._log_available_backends()

    def _log_available_backends(self) -> None:
        backends = []
        if self._has_cosyvoice():
            backends.append("CosyVoice2")
        if self._has_piper():
            backends.append("Piper")
        if self._has_coqui():
            backends.append("Coqui")
        if self._has_espeak():
            backends.append("eSpeak-NG")

        if backends:
            logger.info(f"[{self.name}] TTS backends available: {', '.join(backends)}")
        else:
            logger.warning(
                f"[{self.name}] NO TTS backend found. Install at least one:\n"
                "  sudo apt install espeak-ng          # always-available fallback\n"
                "  pip install piper-tts               # fast, fully local\n"
                "  pip install TTS                     # Coqui, voice cloning\n"
                "  pip install cosyvoice               # best quality (0.5B, Qwen)"
            )

    async def process(self, job: VideoJob) -> VideoJob | None:
        logger.info(f"[{self.name}] Generating audio for {job.job_id}")

        spoken_text = self._clean_for_tts(job.script)
        audio_path = AUDIO_DIR / f"{job.job_id}.wav"

        # Try backends in order of preference — all open-source, all local
        success = False

        if self._has_cosyvoice():
            success = self._generate_cosyvoice(spoken_text, audio_path)

        if not success and self._has_piper():
            success = self._generate_piper(spoken_text, audio_path)

        if not success and self._has_coqui():
            success = self._generate_coqui(spoken_text, audio_path)

        if not success and self._has_espeak():
            success = self._generate_espeak(spoken_text, audio_path)

        if not success:
            raise RuntimeError(
                "No TTS backend available. Install one:\n"
                "  - CosyVoice: pip install cosyvoice\n"
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
                    stripped = stripped[len(label) :].strip()
                    break
            if stripped and stripped[0].isdigit() and len(stripped) > 2 and stripped[1] == ".":
                stripped = stripped[2:].strip()
            if stripped:
                lines.append(stripped)
        return " ".join(lines)

    # ── TTS Backends ─────────────────────────────────────

    def _has_cosyvoice(self) -> bool:
        """Check if Qwen CosyVoice 2 is installed."""
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2  # noqa: F401

            return True
        except ImportError:
            return False

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

    def _generate_cosyvoice(self, text: str, output: Path) -> bool:
        """Generate audio using Qwen CosyVoice 2 (local, open-source)."""
        try:
            import torchaudio
            from cosyvoice.cli.cosyvoice import CosyVoice2

            model = CosyVoice2(
                QWEN_TTS_MODEL,
                load_jit=True,
                load_trt=False,
            )

            # Use streaming inference, collect all chunks
            chunks = []
            for chunk in model.inference_sft(text, QWEN_TTS_VOICE, stream=False):
                chunks.append(chunk["tts_speech"])

            if not chunks:
                logger.warning(f"[{self.name}] CosyVoice returned no audio chunks")
                return False

            import torch

            audio = torch.cat(chunks, dim=1)
            torchaudio.save(str(output), audio, model.sample_rate)

            logger.info(f"[{self.name}] CosyVoice TTS success ({QWEN_TTS_MODEL})")
            return True
        except Exception as e:
            logger.warning(f"[{self.name}] CosyVoice error: {e}")
            return False

    def _generate_piper(self, text: str, output: Path) -> bool:
        """Generate audio using Piper TTS (fully local)."""
        try:
            cmd = [
                "piper",
                "--model",
                "en_US-lessac-medium",
                "--output_file",
                str(output),
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
            result = subprocess.run(cmd, capture_output=True, timeout=30)  # type: ignore[arg-type]
            if result.returncode == 0 and output.exists():
                logger.info(f"[{self.name}] eSpeak TTS success")
                return True
            return False
        except Exception as e:
            logger.warning(f"[{self.name}] eSpeak error: {e}")
            return False
