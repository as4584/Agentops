# backend/agents/epistemic_session.py
"""
EpistemicSession — per-agent session auditing against epistemic_principles.md §6.

Responsibilities:
  - Register every claim with source_type + confidence.
  - Enforce PARAMETRIC hard cap (INV-02).
  - Track gap events and rollback events.
  - On end(), compute CLEAN | NEEDS_REVIEW | FLAGGED and write to session_audit.jsonl.
  - On FLAGGED, invoke soul_core flag callback.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

AuditState = Literal["CLEAN", "NEEDS_REVIEW", "FLAGGED"]

# Source-type max confidence — mirrors epistemic_principles.md §2.
_MAX_CONFIDENCE: dict[str, float] = {
    "TOOL_OUTPUT":      1.0,
    "CORPUS_RETRIEVED": 0.85,
    "INSPECTED_FILE":   0.95,
    "INFERRED":         0.70,
    "PARAMETRIC":       0.50,
}

# INV-02 hard cap for PARAMETRIC claims.
_PARAMETRIC_CAP = 0.50

# PARAMETRIC confidence that triggers NEEDS_REVIEW (if not a cap violation).
_PARAMETRIC_REVIEW_THRESHOLD = 0.30

_DEFAULT_AUDIT_LOG = Path("backend/logs/session_audit.jsonl")

# High-stakes agents: gap-fired + agent proceeded → FLAGGED.
_HIGH_STAKES_AGENTS: frozenset[str] = frozenset(
    {"security_agent", "devops_agent", "self_healer_agent"}
)


class EpistemicSession:
    """
    Tracks all epistemic events within one agent action session.

    Usage::

        session = EpistemicSession(agent_id="devops_agent")
        session.register_claim(
            source_type="CORPUS_RETRIEVED",
            content="nginx config is at /etc/nginx/nginx.conf",
            confidence=0.82,
        )
        state = session.end()   # writes audit record, returns AuditState

    Args:
        agent_id:           The ID of the owning agent.
        session_id:         Optional session UUID. Auto-generated if omitted.
        audit_log:          Path to the JSONL audit log file.
        soul_core_flag_fn:  Optional callback invoked when state is FLAGGED.
                            Signature: fn(agent_id, session_id, state, flags) -> None
    """

    def __init__(
        self,
        agent_id: str,
        session_id: str | None = None,
        audit_log: Path | str = _DEFAULT_AUDIT_LOG,
        soul_core_flag_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._agent_id        = agent_id
        self._session_id      = session_id or str(uuid.uuid4())
        self._audit_log       = Path(audit_log)
        self._soul_core_flag_fn = soul_core_flag_fn

        self._claims:   list[dict[str, Any]] = []
        self._gap_events:    list[dict[str, Any]] = []
        self._rollback_events: list[dict[str, Any]] = []
        self._flags:    list[str]            = []

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def session_id(self) -> str:
        return self._session_id

    def register_claim(
        self,
        source_type: str,
        content: str,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Register one epistemic claim.

        Enforces:
          - PARAMETRIC hard cap at 0.50 (INV-02). Attempts above 0.50
            are capped AND flagged as a FLAGGED violation.
          - PARAMETRIC claims 0.30–0.50 are marked needs_review=True.
          - All source types are capped at their registered maximum.

        Returns the stored claim record.
        """
        flagged = False
        needs_review = False

        # INV-02: PARAMETRIC hard cap enforcement
        if source_type == "PARAMETRIC" and confidence > _PARAMETRIC_CAP:
            self._flags.append(
                f"PARAMETRIC_CAP_VIOLATION: confidence={confidence:.4f} "
                f"exceeds hard cap {_PARAMETRIC_CAP} (INV-02)"
            )
            flagged = True
            confidence = _PARAMETRIC_CAP

        # Apply source-type maximum
        type_max = _MAX_CONFIDENCE.get(source_type, 1.0)
        confidence = min(confidence, type_max)
        confidence = max(0.0, confidence)

        # PARAMETRIC 0.30–0.50 → needs review
        if source_type == "PARAMETRIC" and confidence > _PARAMETRIC_REVIEW_THRESHOLD:
            needs_review = True

        record: dict[str, Any] = {
            "claim_id":    str(uuid.uuid4()),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "source_type": source_type,
            "content":     content,
            "confidence":  round(confidence, 6),
            "needs_review": needs_review,
            "flagged":     flagged,
            "metadata":    metadata or {},
        }

        self._claims.append(record)
        logger.debug(
            "[%s] claim registered | source=%s confidence=%.3f flagged=%s",
            self._agent_id,
            source_type,
            confidence,
            flagged,
        )
        return record

    def record_gap_event(self, gap_result: dict[str, Any]) -> None:
        """Call this when CorpusGapHandler.check() returns gap_fired=True."""
        self._gap_events.append(gap_result)

    def record_rollback(self, reason: str, succeeded: bool) -> None:
        """Call this after any state-modifying action that required rollback."""
        self._rollback_events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason":    reason,
            "succeeded": succeeded,
        })
        if not succeeded:
            self._flags.append(f"ROLLBACK_FAILED: {reason}")

    def end(self) -> AuditState:
        """
        Evaluate all claims and events.
        Write to session_audit.jsonl.
        Trigger soul_core.flag_agent() if FLAGGED.
        Returns CLEAN | NEEDS_REVIEW | FLAGGED.
        """
        if not self._claims and not self._flags:
            # Governance §6: a session with zero claims means the agent
            # bypassed the epistemic pipeline entirely — that is FLAGGED.
            state: AuditState = "FLAGGED"
            self._flags.append("NO_CLAIMS_REGISTERED: agent ended session without any epistemic claims (governance §6)")
            self._write_audit(state)
            self._trigger_soul_core_flag(state)
            return state

        state = self._compute_state()
        self._write_audit(state)

        if state == "FLAGGED":
            self._trigger_soul_core_flag(state)

        logger.info(
            "[%s] session ended | session=%s state=%s "
            "claims=%d flags=%d gaps=%d rollbacks=%d",
            self._agent_id,
            self._session_id,
            state,
            len(self._claims),
            len(self._flags),
            len(self._gap_events),
            len(self._rollback_events),
        )
        return state

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _compute_state(self) -> AuditState:
        # Any explicit flag → FLAGGED
        if self._flags:
            return "FLAGGED"

        # Failed rollback → FLAGGED
        for rb in self._rollback_events:
            if not rb["succeeded"]:
                return "FLAGGED"

        # Gap fired on high-stakes agent with proceed=True → FLAGGED
        for gap in self._gap_events:
            if (
                gap.get("gap_fired")
                and gap.get("agent_should_proceed") is True
                and self._agent_id in _HIGH_STAKES_AGENTS
            ):
                return "FLAGGED"

        # NEEDS_REVIEW conditions
        for claim in self._claims:
            if claim["needs_review"]:
                return "NEEDS_REVIEW"

        # Gap fired but agent allowed to proceed (low-stakes only)
        for gap in self._gap_events:
            if gap.get("gap_fired") and gap.get("agent_should_proceed") is True:
                return "NEEDS_REVIEW"

        # Successful rollback → NEEDS_REVIEW
        if self._rollback_events:
            return "NEEDS_REVIEW"

        return "CLEAN"

    def _write_audit(self, state: AuditState) -> None:
        record = {
            "session_id":  self._session_id,
            "agent_id":    self._agent_id,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "state":       state,
            "claim_count": len(self._claims),
            "flag_count":  len(self._flags),
            "flags":       self._flags,
            "gap_events":  self._gap_events,
            "rollbacks":   self._rollback_events,
            "claims":      self._claims,
        }
        try:
            self._audit_log.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write session audit: %s", exc)

    def _trigger_soul_core_flag(self, state: AuditState) -> None:
        if self._soul_core_flag_fn is None:
            logger.warning(
                "[%s] FLAGGED but no soul_core_flag_fn registered. session=%s",
                self._agent_id,
                self._session_id,
            )
            return
        try:
            self._soul_core_flag_fn(
                agent_id=self._agent_id,
                session_id=self._session_id,
                state=state,
                flags=self._flags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "soul_core flag callback raised for session %s: %s",
                self._session_id,
                exc,
            )
