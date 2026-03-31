"""
ML Training Data Routes — API endpoints for training data inspection.
=====================================================================
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.config import PROJECT_ROOT

router = APIRouter(prefix="/api/ml/training", tags=["ml-training"])

TRAINING_DIR = PROJECT_ROOT / "data" / "training"


@router.get("/files")
async def list_training_files() -> dict[str, Any]:
    """List all JSONL training files with stats."""
    files = []
    total_lines = 0

    if TRAINING_DIR.exists():
        for f in sorted(TRAINING_DIR.glob("*.jsonl")):
            if not f.is_file():
                continue
            line_count = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
            files.append(
                {
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "line_count": line_count,
                }
            )
            total_lines += line_count

    return {
        "files": files,
        "total_files": len(files),
        "total_lines": total_lines,
    }
