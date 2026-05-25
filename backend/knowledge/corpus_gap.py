# backend/knowledge/corpus_gap.py
"""
CorpusGapHandler — enforces corpus gap thresholds from epistemic_principles.md §5.

Responsibilities:
  - Compare top_confidence against per-agent threshold.
  - Write gap records to data/rag/governance/corpus_gaps.md when gap fires.
  - Immediately alert soul_core for high-stakes agents.
  - Never raise — all failures are logged and degrade gracefully.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Per-agent confidence thresholds — mirrors epistemic_principles.md §5.
_THRESHOLDS: dict[str, float] = {
    "soul_core":         0.70,
    "security_agent":    0.60,
    "devops_agent":      0.55,
    "self_healer_agent": 0.55,
    "monitor_agent":     0.50,
    "code_review_agent": 0.50,
    "knowledge_agent":   0.45,
    "data_agent":        0.45,
    "it_agent":          0.45,
    "cs_agent":          0.40,
    "comms_agent":       0.40,
}

# Default threshold for agents not in the table.
_DEFAULT_THRESHOLD = 0.45

# Agents that get an immediate soul_core alert when their gap fires.
_HIGH_STAKES_AGENTS: frozenset[str] = frozenset(
    {"security_agent", "devops_agent", "self_healer_agent"}
)

_DEFAULT_GAP_FILE = Path("data/rag/governance/corpus_gaps.md")


class CorpusGapHandler:
    """
    Enforces corpus gap protocol (epistemic_principles.md §5).

    Args:
        gap_file:             Path to corpus_gaps.md. Defaults to the
                              project-root-relative canonical path.
        soul_core_callback:   Optional callable invoked immediately when a
                              high-stakes agent gap fires. Signature:
                              fn(event, gap_id, requesting_agent, query,
                                 top_confidence, threshold) -> None
    """

    def __init__(
        self,
        gap_file: Path | str = _DEFAULT_GAP_FILE,
        soul_core_callback: Callable[..., Any] | None = None,
    ) -> None:
        self._gap_file = Path(gap_file)
        self._soul_core_callback = soul_core_callback

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def check(
        self,
        requesting_agent: str,
        query: str,
        top_confidence: float,
    ) -> dict[str, Any]:
        """
        Evaluate whether a corpus gap has fired for this retrieval.

        Returns a dict with:
            gap_fired:            bool
            agent_should_proceed: bool  (False when gap fires — INV-04)
            gap_id:               str | None
            threshold:            float
            top_confidence:       float
        """
        threshold = _THRESHOLDS.get(requesting_agent, _DEFAULT_THRESHOLD)

        if top_confidence >= threshold:
            return {
                "gap_fired":            False,
                "agent_should_proceed": True,
                "gap_id":               None,
                "threshold":            threshold,
                "top_confidence":       top_confidence,
            }

        # Gap fires.
        gap_id = f"GAP-{secrets.token_hex(4).upper()}"
        timestamp = datetime.now(timezone.utc).isoformat()
        delta = round(threshold - top_confidence, 6)

        gap_record = {
            "gap_id":           gap_id,
            "timestamp":        timestamp,
            "requesting_agent": requesting_agent,
            "query":            query,
            "top_confidence":   top_confidence,
            "threshold":        threshold,
            "delta":            delta,
            "resolution":       "UNRESOLVED",
            "reviewed_by":      None,
        }

        self._write_gap(gap_record)
        self._maybe_alert_soul_core(**gap_record)

        logger.warning(
            "[CorpusGapHandler] gap_id=%s agent=%s top_confidence=%.4f threshold=%.4f delta=%.4f",
            gap_id,
            requesting_agent,
            top_confidence,
            threshold,
            delta,
        )

        return {
            "gap_fired":            True,
            "agent_should_proceed": False,
            "gap_id":               gap_id,
            "threshold":            threshold,
            "top_confidence":       top_confidence,
        }

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _write_gap(self, record: dict[str, Any]) -> None:
        """Append a gap record to corpus_gaps.md."""
        try:
            self._gap_file.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "\n### " + record["gap_id"],
                f"gap_id:           {record['gap_id']}",
                f"timestamp:        {record['timestamp']}",
                f"requesting_agent: {record['requesting_agent']}",
                f"query:            {record['query']!r}",
                f"top_confidence:   {record['top_confidence']}",
                f"threshold:        {record['threshold']}",
                f"delta:            {record['delta']}",
                f"resolution:       {record['resolution']}",
                f"reviewed_by:      {record['reviewed_by']}",
            ]
            with self._gap_file.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[CorpusGapHandler] Failed to write gap record %s: %s",
                record.get("gap_id"),
                exc,
            )

    def _maybe_alert_soul_core(self, **kwargs: Any) -> None:
        if kwargs["requesting_agent"] not in _HIGH_STAKES_AGENTS:
            return
        if self._soul_core_callback is None:
            logger.warning(
                "soul_core alert skipped — no callback registered | "
                "gap_id=%s agent=%s",
                kwargs["gap_id"],
                kwargs["requesting_agent"],
            )
            return
        try:
            self._soul_core_callback(
                event="CORPUS_GAP_HIGH_STAKES",
                gap_id=kwargs["gap_id"],
                requesting_agent=kwargs["requesting_agent"],
                query=kwargs["query"],
                top_confidence=kwargs["top_confidence"],
                threshold=kwargs["threshold"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "soul_core callback raised for %s: %s",
                kwargs["gap_id"],
                exc,
            )
