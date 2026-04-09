"""
Video Transcriber — Agentop Studio
====================================
Uses faster-whisper to transcribe uploaded videos and return
word-level timestamps for caption generation.

Output format:
    {
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.4,
                "text": "Hey what is up everyone",
                "words": [
                    {"word": "Hey", "start": 0.0, "end": 0.3, "probability": 0.99},
                    ...
                ]
            }
        ],
        "language": "en",
        "duration": 45.2
    }
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("agentop.studio.transcriber")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")  # tiny/base/small/medium


def transcribe(video_path: str | Path) -> dict[str, Any]:
    """
    Transcribe a video file using faster-whisper.
    Returns segments with word-level timestamps.
    """
    from faster_whisper import WhisperModel

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    logger.info(f"[Transcriber] Loading whisper model '{WHISPER_MODEL_SIZE}'")
    model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

    logger.info(f"[Transcriber] Transcribing {video_path.name}")
    segments_iter, info = model.transcribe(
        str(video_path),
        word_timestamps=True,
        vad_filter=True,  # remove silence
        vad_parameters={"min_silence_duration_ms": 300},
    )

    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append(
                    {
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "probability": round(w.probability, 3),
                    }
                )
        segments.append(
            {
                "id": seg.id,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )

    logger.info(f"[Transcriber] Done — {len(segments)} segments, lang={info.language}")
    return {
        "segments": segments,
        "language": info.language,
        "duration": round(info.duration, 2) if info.duration else None,
    }
