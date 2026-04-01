"""
OCR Layer — GLM-OCR document extraction client.
================================================
Wraps the GLM-OCR Flask microservice (localhost:5002) to convert
PDFs, images, and complex documents into clean Markdown before
they reach the main LLM (llama3.2).

Token savings rationale:
  - llama3.2 is text-only — raw images are impossible without this layer.
  - Raw PDF text dumps are noisy and waste context; GLM-OCR produces
    structured Markdown with tables, headings, and code blocks intact.
  - 0.9B model runs locally, far smaller than llama3.2.

Setup (run once before starting the backend):
    pip install "glmocr[server]"
    python -m glmocr.server          # starts on port 5002

Config:
    GLMOCR_URL      — microservice URL  (default: http://localhost:5002)
    GLMOCR_ENABLED  — set false to skip (default: true)
    GLMOCR_TIMEOUT  — seconds per file  (default: 60)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config import GLMOCR_ENABLED, GLMOCR_TIMEOUT, GLMOCR_URL
from backend.utils import logger

# File types GLM-OCR can handle
OCR_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp", ".doc", ".docx"}
)


def is_supported(file_path: str) -> bool:
    """Return True if the file extension is handled by GLM-OCR."""
    return Path(file_path).suffix.lower() in OCR_EXTENSIONS


async def extract_text(file_path: str) -> str | None:
    """
    Extract clean Markdown from a document or image via GLM-OCR.

    Calls the local GLM-OCR Flask microservice.  Returns None when:
      - GLMOCR_ENABLED is false
      - the file type is unsupported
      - the microservice is unreachable (degrades gracefully)

    Args:
        file_path: Absolute path to the document/image.

    Returns:
        Markdown string, or None on failure/unavailability.
    """
    if not GLMOCR_ENABLED:
        return None

    path = Path(file_path)
    if path.suffix.lower() not in OCR_EXTENSIONS:
        return None

    if not path.exists():
        logger.warning(f"glm-ocr: file not found: {file_path}")
        return None

    try:
        async with httpx.AsyncClient(timeout=float(GLMOCR_TIMEOUT)) as client:
            resp = await client.post(
                f"{GLMOCR_URL}/glmocr/parse",
                json={"images": [str(path.resolve())]},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        # GLM-OCR Flask response shape: {"result": {"markdown": "...", "json_result": [...]}}
        # Fallback: {"markdown": "..."} at top level
        result = data.get("result", data)
        markdown: str = result.get("markdown") or result.get("content", "")

        if markdown:
            logger.info(
                f"glm-ocr: extracted {len(markdown):,} chars from {path.name}"
            )
            return markdown.strip()

        logger.warning(f"glm-ocr: empty response for {path.name}")
        return None

    except httpx.ConnectError:
        logger.warning(
            "glm-ocr: microservice unreachable at %s — "
            "run: python -m glmocr.server",
            GLMOCR_URL,
        )
        return None
    except Exception as exc:
        logger.warning(f"glm-ocr: extraction failed for {path.name}: {exc}")
        return None
