"""
Chat failure capture — writes structured JSONL records for failed /chat requests.

Records are stored in data/dpo/chat_failures_{YYYY-MM}.jsonl and can later be
converted into DPO correction examples or router training negatives.

Each record contains enough context to:
  - reproduce the failure condition
  - understand what was attempted
  - build a correction or negative training pair

This module has zero external dependencies — it only uses stdlib.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Output directory — relative to repo root
_DPO_DIR = Path(__file__).resolve().parents[2] / "data" / "dpo"


def write_chat_failure(
    *,
    request_id: str,
    user_message: str,
    chosen_agent: str | None,
    selected_model: str | None,
    last_live_step: str | None,
    ordo_trace: dict[str, Any] | None,
    error_class: str,
    error_detail: str,
    route_path: str | None = None,
    pipeline_stage: str | None = None,
) -> None:
    """Append a structured failure record to the monthly JSONL file.

    Silently swallows any IO error so it never causes a secondary failure.
    """
    now = datetime.now(UTC)
    month_tag = now.strftime("%Y-%m")
    record: dict[str, Any] = {
        "timestamp": now.isoformat(),
        "request_id": request_id,
        "user_message": user_message[:500],  # truncate long messages
        "chosen_agent": chosen_agent,
        "selected_model": selected_model,
        "last_live_step": last_live_step,
        "ordo_trace": ordo_trace,
        "error_class": error_class,
        "error_detail": error_detail[:1000],
        "route_path": route_path,
        "pipeline_stage": pipeline_stage,
        # Intentionally no good_response field — records are negatives/failures only
    }
    try:
        _DPO_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _DPO_DIR / f"chat_failures_{month_tag}.jsonl"
        with output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        logger.debug(f"[ChatFailureLog] wrote record request_id={request_id} to {output_path.name}")
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[ChatFailureLog] failed to write failure record: {exc}")
