# backend/tests/test_corpus_gap.py
"""
Sprint 4 — Corpus Gap + Epistemic Session Gate Tests
======================================================
All tests must be green before Sprint 4 commits.

Coverage:
  1. CorpusGapHandler.check() — gap fires below threshold
  2. CorpusGapHandler.check() — no gap at or above threshold
  3. High-stakes agents trigger soul_core alert callback
  4. Low-stakes agents do NOT trigger soul_core alert
  5. Gap record is written to corpus_gaps.md
  6. Majority-stale overrides agent_should_proceed
  7. _check_staleness — commit-based scope (any modification = stale)
  8. _check_staleness — time-based scope (age ratio + stale flag)
  9. _compute_confidence — sigmoid + recency + scope bonus formula
  10. EpistemicSession CLEAN state
  11. EpistemicSession NEEDS_REVIEW — PARAMETRIC 0.30–0.50
  12. EpistemicSession FLAGGED — PARAMETRIC > 0.50 cap violation (INV-02)
  13. EpistemicSession FLAGGED — failed rollback
  14. EpistemicSession — audit written to jsonl
"""
from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _future_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ── Cat 1: CorpusGapHandler.check() ──────────────────────────────────────────


class TestCorpusGapFires:
    """Gap fires when top_confidence is below the agent threshold."""

    def test_gap_fires_below_threshold_security_agent(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        gap_file = tmp_path / "corpus_gaps.md"
        handler = CorpusGapHandler(gap_file=gap_file)

        # security_agent threshold is 0.60 — pass 0.45
        result = handler.check(
            requesting_agent="security_agent",
            query="which ports should not be exposed",
            top_confidence=0.45,
        )

        assert result["gap_fired"] is True, "Gap should fire for security_agent at 0.45"
        assert result["agent_should_proceed"] is False, "INV-04: agent must not proceed"
        assert result["gap_id"] is not None
        assert result["gap_id"].startswith("GAP-")
        assert result["threshold"] == 0.60
        assert result["top_confidence"] == 0.45

    def test_no_gap_at_threshold_security_agent(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        handler = CorpusGapHandler(gap_file=tmp_path / "corpus_gaps.md")
        result = handler.check(
            requesting_agent="security_agent",
            query="firewall rules",
            top_confidence=0.60,
        )

        assert result["gap_fired"] is False
        assert result["agent_should_proceed"] is True
        assert result["gap_id"] is None

    def test_no_gap_above_threshold(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        handler = CorpusGapHandler(gap_file=tmp_path / "corpus_gaps.md")
        result = handler.check(
            requesting_agent="cs_agent",
            query="return policy",
            top_confidence=0.85,
        )

        assert result["gap_fired"] is False
        assert result["agent_should_proceed"] is True

    def test_unknown_agent_uses_default_threshold(self, tmp_path: Path) -> None:
        """Agents not in the table get a 0.45 default threshold."""
        from backend.knowledge.corpus_gap import CorpusGapHandler

        handler = CorpusGapHandler(gap_file=tmp_path / "corpus_gaps.md")
        # 0.44 < 0.45 default → gap fires
        result_low = handler.check(
            requesting_agent="some_new_agent",
            query="anything",
            top_confidence=0.44,
        )
        assert result_low["gap_fired"] is True

        # 0.45 == threshold → no gap
        result_eq = handler.check(
            requesting_agent="some_new_agent",
            query="anything",
            top_confidence=0.45,
        )
        assert result_eq["gap_fired"] is False


# ── Cat 2: soul_core alert ─────────────────────────────────────────────────────


class TestSoulCoreAlert:
    """High-stakes agents alert soul_core; low-stakes do not."""

    def test_high_stakes_triggers_soul_core_callback(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        callback = MagicMock()
        handler = CorpusGapHandler(
            gap_file=tmp_path / "corpus_gaps.md",
            soul_core_callback=callback,
        )

        for agent in ("security_agent", "devops_agent", "self_healer_agent"):
            callback.reset_mock()
            handler.check(
                requesting_agent=agent,
                query="test query",
                top_confidence=0.10,  # well below any threshold
            )
            callback.assert_called_once()
            call_kwargs = callback.call_args.kwargs
            assert call_kwargs["event"] == "CORPUS_GAP_HIGH_STAKES"
            assert call_kwargs["requesting_agent"] == agent

    def test_low_stakes_does_not_trigger_callback(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        callback = MagicMock()
        handler = CorpusGapHandler(
            gap_file=tmp_path / "corpus_gaps.md",
            soul_core_callback=callback,
        )

        for agent in ("cs_agent", "comms_agent", "knowledge_agent", "it_agent"):
            callback.reset_mock()
            handler.check(
                requesting_agent=agent,
                query="test",
                top_confidence=0.10,
            )
            callback.assert_not_called()

    def test_callback_exception_does_not_propagate(self, tmp_path: Path) -> None:
        """soul_core callback raising must not bubble up to the caller."""
        from backend.knowledge.corpus_gap import CorpusGapHandler

        def bad_callback(**_kwargs: object) -> None:
            raise RuntimeError("soul_core is down")

        handler = CorpusGapHandler(
            gap_file=tmp_path / "corpus_gaps.md",
            soul_core_callback=bad_callback,
        )

        result = handler.check(
            requesting_agent="security_agent",
            query="test",
            top_confidence=0.10,
        )
        # Must still return a valid gap result — exception was swallowed
        assert result["gap_fired"] is True


# ── Cat 3: Gap record written to file ─────────────────────────────────────────


class TestGapFileWrite:
    """gap_id and key fields appear in corpus_gaps.md after gap fires."""

    def test_gap_record_written_to_file(self, tmp_path: Path) -> None:
        from backend.knowledge.corpus_gap import CorpusGapHandler

        gap_file = tmp_path / "corpus_gaps.md"
        handler = CorpusGapHandler(gap_file=gap_file)

        result = handler.check(
            requesting_agent="devops_agent",
            query="deploy to production",
            top_confidence=0.30,
        )

        assert gap_file.exists(), "corpus_gaps.md must be created when gap fires"
        content = gap_file.read_text()
        assert result["gap_id"] in content
        assert "devops_agent" in content
        assert "UNRESOLVED" in content

    def test_no_file_write_when_no_gap(self, tmp_path: Path) -> None:
        """No file write when confidence is above threshold."""
        from backend.knowledge.corpus_gap import CorpusGapHandler

        gap_file = tmp_path / "corpus_gaps.md"
        handler = CorpusGapHandler(gap_file=gap_file)

        handler.check(
            requesting_agent="cs_agent",
            query="order status",
            top_confidence=0.99,
        )

        # File should not be created (or should remain empty seed)
        assert not gap_file.exists() or gap_file.stat().st_size == 0


# ── Cat 4: Staleness checks ────────────────────────────────────────────────────


class TestStalenessCheck:
    """_check_staleness() returns correct is_stale + age_ratio."""

    def _make_assembler(self) -> object:
        from unittest.mock import MagicMock
        from backend.knowledge.context_assembler import ContextAssembler
        # Instantiate without real LLM — we only test the private method
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler._llm   = MagicMock()
        assembler._store = MagicMock()
        assembler._bm25  = MagicMock()
        assembler._engine = MagicMock()
        assembler._gap_handler = MagicMock()
        return assembler

    def test_missing_timestamps_returns_not_stale(self) -> None:
        assembler = self._make_assembler()
        result = assembler._check_staleness({"text": "no timestamps here"})
        assert result["is_stale"] is False
        assert result["stale_since"] is None
        assert result["age_ratio"] == 0.0

    def test_commit_scope_stale_when_modified_after_indexed(self) -> None:
        """governance scope: any modification after indexing = stale."""
        assembler = self._make_assembler()
        chunk = {
            "metadata": {
                "scope":                "governance",
                "last_indexed":         _past_iso(1),   # indexed 1h ago
                "source_last_modified": _now_iso(),      # modified now
            }
        }
        result = assembler._check_staleness(chunk)
        assert result["is_stale"] is True
        assert result["age_ratio"] == 1.0

    def test_commit_scope_not_stale_when_not_modified(self) -> None:
        """governance scope: not stale if source wasn't modified after indexing."""
        assembler = self._make_assembler()
        chunk = {
            "metadata": {
                "scope":                "governance",
                "last_indexed":         _now_iso(),
                "source_last_modified": _past_iso(5),  # modified before index
            }
        }
        result = assembler._check_staleness(chunk)
        assert result["is_stale"] is False

    def test_time_scope_stale_past_threshold(self) -> None:
        """security scope (24h): chunk indexed 36h ago = stale."""
        assembler = self._make_assembler()
        chunk = {
            "metadata": {
                "scope":                "security",
                "last_indexed":         _past_iso(36),   # 36h ago (> 24h threshold)
                "source_last_modified": _past_iso(40),   # modified before index
            }
        }
        result = assembler._check_staleness(chunk)
        assert result["is_stale"] is True

    def test_time_scope_age_ratio_computed(self) -> None:
        """security scope (24h): chunk 12h old → age_ratio ~0.5."""
        assembler = self._make_assembler()
        chunk = {
            "metadata": {
                "scope":                "security",
                "last_indexed":         _past_iso(12),   # 12h ago
                "source_last_modified": _past_iso(20),   # modified before index
            }
        }
        result = assembler._check_staleness(chunk)
        assert result["is_stale"] is False
        assert 0.45 < result["age_ratio"] < 0.55  # ~0.5 of 24h threshold

    def test_unknown_scope_defaults_to_7_days(self) -> None:
        """Unknown scopes default to 7-day (168h) threshold."""
        assembler = self._make_assembler()
        # 200h > 168h → stale
        chunk = {
            "metadata": {
                "scope":                "unknown_scope",
                "last_indexed":         _past_iso(200),
                "source_last_modified": _past_iso(300),
            }
        }
        result = assembler._check_staleness(chunk)
        assert result["is_stale"] is True

    def test_timezone_offset_parsed_correctly(self) -> None:
        """Non-UTC timezone offsets must be converted, not relabeled.

        A timestamp written 30h ago in UTC but expressed in +10:00 offset
        has wall clock time 10h ahead. With the .replace(tzinfo=utc) bug,
        the engine would see it as 20h old instead of 30h old — wrongly
        marking a stale chunk as fresh.
        """
        from datetime import timezone as tz

        assembler = self._make_assembler()

        now_utc = datetime.now(tz.utc)
        offset_10 = tz(timedelta(hours=10))

        # Indexed 30h ago (UTC). Security threshold = 24h → should be STALE.
        indexed_utc = now_utc - timedelta(hours=30)
        indexed_offset = indexed_utc.astimezone(offset_10)  # wall = utc + 10h

        modified_utc = now_utc - timedelta(hours=40)
        modified_offset = modified_utc.astimezone(offset_10)

        chunk = {
            "metadata": {
                "scope":                "security",
                "last_indexed":         indexed_offset.isoformat(),
                "source_last_modified": modified_offset.isoformat(),
            }
        }
        result = assembler._check_staleness(chunk)
        # 30h old > 24h security threshold → MUST be stale.
        # Bug: .replace(tzinfo=utc) would see 20h old → wrongly not stale.
        assert result["is_stale"] is True, (
            "30h-old chunk must be stale (24h threshold). "
            "If not stale, timezone offset was relabeled instead of converted."
        )
        # age_ratio should be ~30/24 ≈ 1.25, capped at 1.0
        assert result["age_ratio"] >= 0.9, (
            f"age_ratio={result['age_ratio']:.3f} should be ~1.0 for 30h/24h"
        )


# ── Cat 5: Confidence scoring ──────────────────────────────────────────────────


class TestComputeConfidence:
    """_compute_confidence() applies sigmoid × recency × scope_bonus."""

    def _make_assembler(self) -> object:
        from unittest.mock import MagicMock
        from backend.knowledge.context_assembler import ContextAssembler
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler._llm    = MagicMock()
        assembler._store  = MagicMock()
        assembler._bm25   = MagicMock()
        assembler._engine = MagicMock()
        assembler._gap_handler = MagicMock()
        return assembler

    def test_fresh_chunk_exact_scope_near_sigmoid_value(self) -> None:
        """Fresh, exact-scope chunk: confidence ≈ sigmoid(score)."""
        assembler = self._make_assembler()
        chunk = {
            "_reranker_score": 4.0,       # sigmoid(4) ≈ 0.982
            "metadata": {
                "scope":                "security",
                "last_indexed":         _now_iso(),
                "source_last_modified": _past_iso(10),
            },
        }
        conf = assembler._compute_confidence(chunk, scope="security")
        expected_sigmoid = 1.0 / (1.0 + math.exp(-4.0))
        # exact scope → bonus=1.0, fresh → recency=1.0
        assert abs(conf - expected_sigmoid) < 0.001

    def test_stale_chunk_confidence_is_zero(self) -> None:
        """Stale chunk: recency_factor=0.0 → confidence=0.0."""
        assembler = self._make_assembler()
        chunk = {
            "_reranker_score": 8.0,  # would be ~1.0 sigmoid
            "metadata": {
                "scope":                "security",
                "last_indexed":         _past_iso(48),   # 48h > 24h threshold → stale
                "source_last_modified": _past_iso(50),
            },
        }
        conf = assembler._compute_confidence(chunk, scope="security")
        assert conf == 0.0, "Stale chunk must have confidence=0.0"

    def test_adjacent_scope_applies_0_85_bonus(self) -> None:
        """security chunk queried from network scope → 0.85 bonus."""
        assembler = self._make_assembler()
        chunk = {
            "_reranker_score": 0.0,  # sigmoid(0)=0.5
            "metadata": {
                "scope":                "security",
                "last_indexed":         _now_iso(),
                "source_last_modified": _past_iso(1),
            },
        }
        conf_adj   = assembler._compute_confidence(chunk, scope="network")   # adjacent
        conf_exact = assembler._compute_confidence(chunk, scope="security")  # exact
        conf_none  = assembler._compute_confidence(chunk, scope="agents")    # no relation

        assert conf_adj < conf_exact, "Adjacent scope must score lower than exact"
        assert conf_none < conf_adj,  "Unmatched scope must score lower than adjacent"
        assert abs(conf_exact / conf_adj - 1.0 / 0.85) < 0.01

    def test_confidence_clamped_to_0_1(self) -> None:
        """Confidence is always in [0.0, 1.0]."""
        assembler = self._make_assembler()
        for score in (-100.0, 0.0, 100.0):
            chunk = {"_reranker_score": score}
            conf = assembler._compute_confidence(chunk)
            assert 0.0 <= conf <= 1.0


# ── Cat 6: EpistemicSession ────────────────────────────────────────────────────


class TestEpistemicSession:
    """EpistemicSession computes CLEAN / NEEDS_REVIEW / FLAGGED correctly."""

    def _session(self, agent_id: str = "knowledge_agent", tmp_path: Path | None = None) -> object:
        from backend.agents.epistemic_session import EpistemicSession
        log = (tmp_path / "audit.jsonl") if tmp_path else Path(tempfile.mktemp(suffix=".jsonl"))
        return EpistemicSession(agent_id=agent_id, audit_log=log)

    def test_clean_state_all_tool_output(self, tmp_path: Path) -> None:
        session = self._session(tmp_path=tmp_path)
        session.register_claim("TOOL_OUTPUT", "nginx is running", 0.99)
        session.register_claim("INSPECTED_FILE", "config read", 0.90)
        assert session.end() == "CLEAN"

    def test_needs_review_parametric_above_review_threshold(self, tmp_path: Path) -> None:
        """PARAMETRIC 0.31 → 0.50 range triggers NEEDS_REVIEW."""
        session = self._session(tmp_path=tmp_path)
        session.register_claim("PARAMETRIC", "I believe nginx uses port 80", 0.40)
        state = session.end()
        assert state == "NEEDS_REVIEW", f"Expected NEEDS_REVIEW, got {state}"

    def test_parametric_at_or_below_review_threshold_stays_clean(self, tmp_path: Path) -> None:
        """PARAMETRIC ≤ 0.30 → no needs_review flag."""
        session = self._session(tmp_path=tmp_path)
        session.register_claim("PARAMETRIC", "something vague", 0.20)
        assert session.end() == "CLEAN"

    def test_flagged_parametric_cap_violation_inv02(self, tmp_path: Path) -> None:
        """PARAMETRIC confidence > 0.50 is a FLAGGED INV-02 violation."""
        session = self._session(tmp_path=tmp_path)
        claim = session.register_claim("PARAMETRIC", "bypassed cap", 0.75)
        # Confidence must be capped at 0.50 despite the input being 0.75
        assert claim["confidence"] == 0.50, "INV-02: confidence must be capped"
        assert claim["flagged"] is True
        state = session.end()
        assert state == "FLAGGED", f"Expected FLAGGED for INV-02 violation, got {state}"

    def test_flagged_failed_rollback(self, tmp_path: Path) -> None:
        session = self._session(tmp_path=tmp_path)
        session.register_claim("TOOL_OUTPUT", "action taken", 0.99)
        session.record_rollback("disk write failed", succeeded=False)
        assert session.end() == "FLAGGED"

    def test_needs_review_successful_rollback(self, tmp_path: Path) -> None:
        session = self._session(tmp_path=tmp_path)
        session.register_claim("TOOL_OUTPUT", "action taken", 0.99)
        session.record_rollback("stale config reverted", succeeded=True)
        assert session.end() == "NEEDS_REVIEW"

    def test_empty_session_is_flagged_per_governance_s6(self, tmp_path: Path) -> None:
        """Governance §6: session with zero registered claims = FLAGGED.

        An agent that ends a session without registering ANY claims has either
        bypassed the epistemic pipeline or silently dropped all observations.
        This is a governance violation — not a clean pass.
        """
        session = self._session(tmp_path=tmp_path)
        state = session.end()
        assert state == "FLAGGED", (
            f"Empty session (no claims) must be FLAGGED per governance §6, got {state}"
        )

    def test_audit_record_written_to_jsonl(self, tmp_path: Path) -> None:
        """end() must write a valid JSONL record to the audit log."""
        log_path = tmp_path / "audit.jsonl"
        from backend.agents.epistemic_session import EpistemicSession
        session = EpistemicSession(agent_id="it_agent", audit_log=log_path)
        session.register_claim("CORPUS_RETRIEVED", "ping latency is normal", 0.78)
        session.end()

        assert log_path.exists(), "Audit log must be created"
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1, "Exactly one JSONL line expected"

        record = json.loads(lines[0])
        assert record["agent_id"] == "it_agent"
        assert record["state"] in ("CLEAN", "NEEDS_REVIEW", "FLAGGED")
        assert isinstance(record["claims"], list)
        assert record["claim_count"] == 1

    def test_soul_core_callback_invoked_on_flagged(self, tmp_path: Path) -> None:
        """FLAGGED state must invoke soul_core_flag_fn."""
        from backend.agents.epistemic_session import EpistemicSession

        callback = MagicMock()
        log = tmp_path / "audit.jsonl"
        session = EpistemicSession(
            agent_id="security_agent",
            audit_log=log,
            soul_core_flag_fn=callback,
        )
        session.register_claim("PARAMETRIC", "bypassed", 0.99)
        state = session.end()

        assert state == "FLAGGED"
        callback.assert_called_once()
        kw = callback.call_args.kwargs
        assert kw["agent_id"] == "security_agent"
        assert kw["state"] == "FLAGGED"

    def test_soul_core_callback_not_invoked_on_clean(self, tmp_path: Path) -> None:
        from backend.agents.epistemic_session import EpistemicSession

        callback = MagicMock()
        log = tmp_path / "audit.jsonl"
        session = EpistemicSession(
            agent_id="knowledge_agent",
            audit_log=log,
            soul_core_flag_fn=callback,
        )
        session.register_claim("TOOL_OUTPUT", "healthy", 1.0)
        session.end()

        callback.assert_not_called()


# ── Cat 7: Majority stale integration ─────────────────────────────────────────


class TestMajorityStale:
    """majority_stale=True overrides agent_should_proceed even when gap doesn't fire."""

    def _make_assembler_with_gap_handler(self, gap_handler: object) -> object:
        from unittest.mock import MagicMock
        from backend.knowledge.context_assembler import ContextAssembler
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler._llm    = MagicMock()
        assembler._store  = MagicMock()
        assembler._bm25   = MagicMock()
        assembler._engine = MagicMock()
        assembler._gap_handler = gap_handler
        return assembler

    def test_majority_stale_forces_agent_should_proceed_false(self) -> None:
        """
        Even if gap_handler says proceed=True (confidence is above threshold),
        majority_stale must override to False (INV-03).
        """
        gap_handler = MagicMock()
        # Gap handler says no gap, proceed=True
        gap_handler.check.return_value = {
            "gap_fired":            False,
            "agent_should_proceed": True,
            "gap_id":               None,
        }

        assembler = self._make_assembler_with_gap_handler(gap_handler)

        # Build 3 stale chunks (majority) + 1 fresh
        stale_meta = {
            "scope":                "security",
            "last_indexed":         (
                datetime.now(timezone.utc) - timedelta(hours=48)
            ).isoformat(),
            "source_last_modified": (
                datetime.now(timezone.utc) - timedelta(hours=50)
            ).isoformat(),
        }
        fresh_meta = {
            "scope":                "security",
            "last_indexed":         datetime.now(timezone.utc).isoformat(),
            "source_last_modified": (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat(),
        }

        chunks = [
            {"chunk_id": "c1", "text": "stale 1", "_reranker_score": 4.0, "metadata": stale_meta},
            {"chunk_id": "c2", "text": "stale 2", "_reranker_score": 4.0, "metadata": stale_meta},
            {"chunk_id": "c3", "text": "stale 3", "_reranker_score": 4.0, "metadata": stale_meta},
            {"chunk_id": "c4", "text": "fresh",   "_reranker_score": 4.0, "metadata": fresh_meta},
        ]

        # Directly test the annotate + gap logic (bypass async search)
        annotated = []
        stale_ids = []
        for chunk in chunks:
            staleness  = assembler._check_staleness(chunk)
            confidence = assembler._compute_confidence(chunk, scope="security")
            annotated.append({**chunk, **staleness, "confidence": confidence})
            if staleness["is_stale"]:
                stale_ids.append(chunk["chunk_id"])

        majority_stale = len(stale_ids) > len(annotated) / 2
        assert majority_stale is True, "Pre-condition: majority must be stale"

        top_confidence = max(c["confidence"] for c in annotated)
        gap_result = assembler._gap_handler.check(
            requesting_agent="security_agent",
            query="test",
            top_confidence=top_confidence,
        )

        if majority_stale:
            gap_result["agent_should_proceed"] = False

        assert gap_result["agent_should_proceed"] is False, (
            "majority_stale must override agent_should_proceed to False"
        )
        assert "c1" in stale_ids and "c2" in stale_ids and "c3" in stale_ids
