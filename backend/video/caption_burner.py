"""
Caption Burner — Agentop Studio
=================================
Takes a video + word-level transcript and burns animated captions
in the style of viral short-form content (bold, centered, 2-3 words
at a time, highlight word in accent color).

Pipeline:
    1. Group words into caption chunks (2-3 words, max ~2s each)
    2. Generate an .ass subtitle file with per-word color highlight
    3. Run ffmpeg to burn subtitles into the video
    4. Optionally crop/scale to 9:16 for Reels/TikTok

Requirements: ffmpeg in PATH
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("agentop.studio.caption_burner")

# Caption style defaults — can be overridden per export
DEFAULT_STYLE = {
    "font_name": "Arial",
    "font_size": 22,  # ASS font size (scaled to resolution)
    "primary_color": "&H00FFFFFF",  # white
    "highlight_color": "&H0000CFFF",  # yellow-orange accent
    "outline_color": "&H00000000",  # black outline
    "shadow_color": "&H80000000",
    "bold": True,
    "outline": 3,
    "shadow": 1,
    "margin_v": 60,  # distance from bottom
    "words_per_chunk": 3,
    "max_chunk_duration": 2.5,
}


def _group_words_into_chunks(words: list[dict], words_per_chunk: int, max_duration: float) -> list[dict]:
    """Group word-level timestamps into caption chunks."""
    chunks = []
    current: list[dict] = []

    for w in words:
        current.append(w)
        duration = current[-1]["end"] - current[0]["start"]
        if len(current) >= words_per_chunk or duration >= max_duration:
            chunks.append(
                {
                    "words": list(current),
                    "start": current[0]["start"],
                    "end": current[-1]["end"],
                    "text": " ".join(x["word"] for x in current),
                }
            )
            current = []

    if current:
        chunks.append(
            {
                "words": list(current),
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(x["word"] for x in current),
            }
        )

    return chunks


def _seconds_to_ass(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s % 1) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _build_ass(
    chunks: list[dict],
    style: dict,
    video_width: int,
    video_height: int,
) -> str:
    """Build a full .ass subtitle file with per-word highlight animation."""
    font_size = int(style["font_size"] * (video_height / 1080))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style["font_name"]},{font_size},{style["primary_color"]},&H000000FF,{style["outline_color"]},{style["shadow_color"]},{1 if style["bold"] else 0},0,0,0,100,100,0,0,1,{style["outline"]},{style["shadow"]},2,10,10,{style["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    highlight = style["highlight_color"]
    white = style["primary_color"]

    for chunk in chunks:
        start = _seconds_to_ass(chunk["start"])
        end = _seconds_to_ass(chunk["end"])
        words = chunk["words"]

        # For each word in the chunk, create a dialogue line that highlights
        # only that word while others stay white — layered approach
        for i, word in enumerate(words):
            w_start = _seconds_to_ass(word["start"])
            w_end = _seconds_to_ass(word["end"])

            # Build the text with the current word highlighted
            parts = []
            for j, w in enumerate(words):
                if j == i:
                    parts.append(f"{{\\c{highlight}&}}{w['word']}{{\\c{white}&}}")
                else:
                    parts.append(w["word"])
            text = " ".join(parts)

            events.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{text}")

        # Also add a base line for the full chunk (lower layer) for readability
        base_text = " ".join(w["word"] for w in words)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\alpha&HFF&}}{base_text}")

    return header + "\n".join(events)


def get_video_dimensions(video_path: str | Path) -> tuple[int, int]:
    """Return (width, height) of a video using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    parts = result.stdout.strip().split(",")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 1080, 1920  # fallback


def burn_captions(
    video_path: str | Path,
    transcript: dict[str, Any],
    output_path: str | Path,
    style: dict | None = None,
    crop_to_vertical: bool = False,
) -> Path:
    """
    Burn animated word-highlight captions into a video.

    Args:
        video_path: Input video file
        transcript: Output from transcriber.transcribe()
        output_path: Where to save the captioned video
        style: Override default caption style
        crop_to_vertical: If True, crop/scale to 9:16 (1080x1920)

    Returns:
        Path to the output file
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    merged_style = {**DEFAULT_STYLE, **(style or {})}

    # Collect all words across segments
    all_words = []
    for seg in transcript.get("segments", []):
        all_words.extend(seg.get("words", []))

    if not all_words:
        raise ValueError("No word-level timestamps in transcript")

    chunks = _group_words_into_chunks(
        all_words,
        merged_style["words_per_chunk"],
        merged_style["max_chunk_duration"],
    )

    w, h = get_video_dimensions(video_path)
    ass_content = _build_ass(chunks, merged_style, w, h)

    # Write .ass to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ass", delete=False) as f:
        f.write(ass_content)
        ass_path = f.name

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build ffmpeg filter chain
        filters = []
        if crop_to_vertical:
            # Crop to 9:16 centered, then scale to 1080x1920
            crop_w = min(w, int(h * 9 / 16))
            crop_h = min(h, int(w * 16 / 9))
            filters.append(f"crop={crop_w}:{crop_h},scale=1080:1920")

        filters.append(f"ass={ass_path}")
        filter_str = ",".join(filters)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            filter_str,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]

        logger.info(f"[CaptionBurner] Running ffmpeg for {video_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"[CaptionBurner] ffmpeg error: {result.stderr[-500:]}")
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")

        logger.info(f"[CaptionBurner] Done → {output_path}")
        return output_path

    finally:
        os.unlink(ass_path)


def export_srt(transcript: dict[str, Any], output_path: str | Path) -> Path:
    """Export transcript as a standard .srt subtitle file."""
    output_path = Path(output_path)
    lines = []
    idx = 1

    all_words = []
    for seg in transcript.get("segments", []):
        all_words.extend(seg.get("words", []))

    chunks = _group_words_into_chunks(all_words, 3, 2.5)

    def _srt_ts(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{int(sec):02d},{ms:03d}"

    for chunk in chunks:
        lines.append(str(idx))
        lines.append(f"{_srt_ts(chunk['start'])} --> {_srt_ts(chunk['end'])}")
        lines.append(chunk["text"])
        lines.append("")
        idx += 1

    output_path.write_text("\n".join(lines))
    return output_path
