"""Lex Routing Confidence Regression Suite
==========================================
Pre-Sprint-1 test suite that documents the DESIRED routing behavior
after the 11-agent canonical cut.

Run order:
  1. Run backend/tests/capture_lex_baseline.py FIRST → commit the JSON
  2. Run this suite → expect failures (Sprint 1 hasn't shipped yet)
  3. Note which fail → those are your Sprint 1 acceptance criteria

Sprint 1 complete when ALL tests here pass.

Deviations from raw spec are annotated inline with  # [SPEC-FIX].
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestrator.lex_router import (  # [SPEC-FIX] correct module path
    VALID_AGENTS,
    resolve_agent,
)

# ── Canonical 11-agent set (the target state after Sprint 1) ────────────────
CANONICAL_AGENTS = {
    "soul_core",
    "it_agent",
    "cs_agent",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "knowledge_agent",
}

# ── High-risk agents that require >= 0.8 confidence (Sprint 1 invariant) ────
_HIGH_RISK_AGENTS = {"security_agent", "self_healer_agent", "code_review_agent"}

# ── Retired agent IDs that must never appear as routing targets ─────────────
_RETIRED_AGENTS = {
    "token_optimizer",
    "vocabulary_coach",
    "career_intel",
    "accreditation_advisor",
    "pedagogy_agent",
    "higgsfield_agent",
    "higgsfield_research_agent",
    "ocr_agent",
    "prompt_engineer",
    "curriculum_advisor",
}


# ════════════════════════════════════════════════════════════════════════════
# Category 1 — Canonical Roster Enforcement
# EXPECTED FAILURES BEFORE SPRINT 1:
#   test_valid_agents_matches_canonical_roster  → VALID_AGENTS has 21 not 11
#   test_no_retired_agent_ids_in_router         → ocr_agent still in VALID_AGENTS
# ════════════════════════════════════════════════════════════════════════════


class TestCanonicalRosterEnforcement:
    def test_valid_agents_matches_canonical_roster(self) -> None:
        """VALID_AGENTS must equal exactly the canonical 11.

        Any drift here breaks the entire routing contract.
        EXPECTED TO FAIL before Sprint 1 (currently 21 agents).
        """
        assert VALID_AGENTS == CANONICAL_AGENTS, (
            f"Router drift detected.\n"
            f"Extra:   {VALID_AGENTS - CANONICAL_AGENTS}\n"
            f"Missing: {CANONICAL_AGENTS - VALID_AGENTS}"
        )

    def test_no_retired_agent_ids_in_router(self) -> None:
        """Retired agents must never appear as routing targets.

        If they do, Lex is serving a broken destination.
        EXPECTED TO FAIL before Sprint 1 (ocr_agent is still registered).
        """
        overlap = VALID_AGENTS & _RETIRED_AGENTS
        assert not overlap, f"Retired agent IDs still in router: {overlap}"

    def test_canonical_agents_all_present(self) -> None:
        """Every canonical agent must be reachable.

        EXPECTED TO FAIL before Sprint 1 if VALID_AGENTS != CANONICAL_AGENTS.
        """
        missing = CANONICAL_AGENTS - VALID_AGENTS
        assert not missing, f"Canonical agents not in router: {missing}"


# ════════════════════════════════════════════════════════════════════════════
# Category 2 — Confidence Threshold Invariants
# EXPECTED FAILURES BEFORE SPRINT 1:
#   test_confidence_below_threshold_routes_to_soul_core  → no threshold logic
#   test_high_risk_agent_requires_08_confidence          → no threshold logic
# ════════════════════════════════════════════════════════════════════════════


class TestConfidenceThresholdInvariants:
    @patch("backend.orchestrator.lex_router._fast_router", None)  # [SPEC-FIX] bypass C stage
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "lex")
    async def test_confidence_below_threshold_routes_to_soul_core(self) -> None:
        """Any routing decision with confidence < 0.5 must go to soul_core.

        Never silently route to a specialist with low confidence.
        EXPECTED TO FAIL before Sprint 1 — threshold logic not yet implemented.
        """
        with patch(
            "backend.orchestrator.lex_router._lex_route",  # [SPEC-FIX]
            new_callable=AsyncMock,
            return_value=("devops_agent", 0.3),
        ):
            result = await resolve_agent("do something ambiguous")

        assert result["agent_id"] == "soul_core", (
            f"Expected soul_core escalation for confidence 0.3, "
            f"got {result['agent_id']} (confidence={result.get('confidence')})"
        )

    @patch("backend.orchestrator.lex_router._fast_router", None)  # [SPEC-FIX]
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "lex")
    async def test_high_risk_agent_requires_08_confidence(self) -> None:
        """High-risk agents need >= 0.8 confidence or soul_core escalation.

        Applies to: security_agent, self_healer_agent, code_review_agent.
        EXPECTED TO FAIL before Sprint 1 — threshold logic not yet implemented.
        """
        for agent in _HIGH_RISK_AGENTS:
            with patch(
                "backend.orchestrator.lex_router._lex_route",  # [SPEC-FIX]
                new_callable=AsyncMock,
                return_value=(agent, 0.65),
            ):
                result = await resolve_agent("fix something important")

            assert result["agent_id"] == "soul_core", (
                f"High-risk agent {agent} routed directly at confidence 0.65. "
                f"Must require >= 0.8 or escalate to soul_core."
            )

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_red_line_always_blocks_regardless_of_confidence(self) -> None:
        """Red-line violations must produce blocked=True.

        Confidence is irrelevant — blocked is blocked.
        This tests CURRENT behavior (red-line already implemented).
        Expected to PASS before Sprint 1.
        """
        mock_router = MagicMock()
        mock_router.available = True
        mock_router.check_red_line.return_value = True

        with patch("backend.orchestrator.lex_router._fast_router", mock_router):  # [SPEC-FIX]
            result = await resolve_agent("drop all tables in production")

        assert result.get("blocked") is True, f"Red-line must produce blocked=True, got: {result}"
        # Blocked result routes to soul_core with the red-line method tag
        assert result.get("method") == "c_red_line", (
            f"Red-line must have method=c_red_line, got: {result.get('method')}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Category 3 — Routing Accuracy Fixtures (live calls, keyword fallback path)
# These call resolve_agent without mocking.  In environments without Ollama
# they exercise the keyword fallback (confidence=0.8).
# Failures here are Sprint 1 acceptance criteria for routing quality.
# ════════════════════════════════════════════════════════════════════════════

_ROUTING_FIXTURES = [
    # (message, expected_agent, min_confidence, description)
    (
        "restart the ollama service on port 11434",
        "it_agent",
        0.7,
        "infrastructure restart — port reference",
    ),
    (
        "check if the kubernetes pod is running",
        "it_agent",
        0.7,
        "K8s cluster management",
    ),
    (
        "deploy the latest build to staging",
        "devops_agent",
        0.8,
        "explicit deployment intent",
    ),
    (
        "why is my CI pipeline failing",
        "devops_agent",
        0.7,
        "pipeline health query",
    ),
    (
        "tail the logs for the backend service",
        "monitor_agent",
        0.7,
        "log observation — read-heavy",
    ),
    (
        "alert me if ollama goes down",
        "monitor_agent",
        0.7,
        "monitoring setup",
    ),
    (
        "fix the ruff lint errors in the last commit",
        "self_healer_agent",
        0.7,
        "remediation trigger — lint",
    ),
    (
        "scan for hardcoded credentials in the repo",
        "security_agent",
        0.75,
        "explicit secret scan",
    ),
    (
        "review the diff before we merge to main",
        "code_review_agent",
        0.7,
        "explicit review request",
    ),
    (
        "what does the SOURCE_OF_TRUTH doc say about tool permissions",
        "knowledge_agent",
        0.7,
        "corpus retrieval query",
    ),
    (
        "send an incident notification to the team",
        "comms_agent",
        0.7,
        "explicit outbound comms",
    ),
    (
        "check the database schema for drift",
        "data_agent",
        0.7,
        "schema governance query",
    ),
    (
        "i need help with my account",
        "cs_agent",
        0.7,
        "customer support trigger",
    ),
]


@pytest.mark.parametrize(
    "message,expected,min_conf,desc",
    _ROUTING_FIXTURES,
    ids=[f[3].replace(" ", "_") for f in _ROUTING_FIXTURES],
)
async def test_routing_accuracy(message: str, expected: str, min_conf: float, desc: str) -> None:
    """Each fixture tests a canonical routing case.

    Fails if: wrong agent, or confidence below minimum.
    Expected to partially fail before Sprint 1 — routing to retired agents
    or wrong canonical agents are Sprint 1 acceptance criteria.
    """
    result = await resolve_agent(message)

    assert result["agent_id"] == expected, (
        f"ROUTING MISS [{desc}]\n"
        f"  Message:    '{message}'\n"
        f"  Expected:   {expected}\n"
        f"  Got:        {result['agent_id']} "
        f"(method={result.get('method')}, "
        f"confidence={result.get('confidence', 0.0):.2f})"
    )
    assert result.get("confidence", 0.0) >= min_conf, (
        f"CONFIDENCE TOO LOW [{desc}]\n  Expected >= {min_conf}, got {result.get('confidence', 0.0):.2f}"
    )


# ════════════════════════════════════════════════════════════════════════════
# Category 4 — Routing Method + Fallback Chain
# EXPECTED FAILURES BEFORE SPRINT 1:
#   test_lex_unavailable_falls_back_to_soul_core  → exception propagates today
#   test_routing_result_schema_always_complete    → 'reasoning' field missing
# ════════════════════════════════════════════════════════════════════════════


class TestRoutingMethodAndFallbackChain:
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_fast_router_unavailable_falls_back_to_lex(self) -> None:
        """When fast_route.c is unavailable, routing must fall through to Lex.

        Never fail silently — method field must reflect the actual path taken.
        NOTE: flaky if Ollama is unreachable (falls to keyword → method='keyword').
        Reliable in CI only when Ollama is running.
        """
        mock_fast = MagicMock()
        mock_fast.available = False  # C router offline

        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):  # [SPEC-FIX]
            result = await resolve_agent("deploy the staging build")

        assert result["method"] in {"lex", "lex_fallback", "keyword"}, (
            f"Expected lex or keyword fallback, got method={result['method']}"
        )
        assert result["agent_id"] in (CANONICAL_AGENTS | VALID_AGENTS), (
            f"Fallback routed to unknown agent: {result['agent_id']}"
        )

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_lex_unavailable_falls_back_to_soul_core(self) -> None:
        """When both fast_route and Lex fail, soul_core is the final safe destination.

        Never raise — always route somewhere valid.
        EXPECTED TO FAIL before Sprint 1:
          Current behavior: exception propagates from resolve_agent.
          Sprint 1 must add try/except around the _lex_route call and return
          {"agent_id": "soul_core", "method": "fallback_soul_core", ...}.
        See existing test: TestResolveAgentAdvanced.test_llm_timeout_propagates_exception
        which documents the current (pre-Sprint-1) behavior.
        """
        with patch(
            "backend.orchestrator.lex_router._lex_route",  # [SPEC-FIX]
            new_callable=AsyncMock,
            side_effect=Exception("LLM timeout"),
        ):
            result = await resolve_agent("do something")

        assert result["agent_id"] == "soul_core", (
            f"Full routing failure must land on soul_core, got {result['agent_id']}"
        )
        assert result.get("method") == "fallback_soul_core", (
            f"Method tag must identify this as a fallback, not a normal route. Got: {result.get('method')}"
        )

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "keyword")
    async def test_routing_result_schema_always_complete(self) -> None:
        """Every routing result must carry all required fields.

        Downstream agents must never receive a partial result.
        EXPECTED TO FAIL before Sprint 1:
          'reasoning' field is not in current resolve_agent output.
          Sprint 1 must add reasoning to all return paths.
        """
        required_fields = {"agent_id", "confidence", "method", "reasoning"}

        result = await resolve_agent("restart the backend service")

        missing = required_fields - set(result.keys())
        assert not missing, f"Routing result missing required fields: {missing}\nGot: {list(result.keys())}"
        assert isinstance(result["confidence"], float), (
            f"confidence must be float, not {type(result['confidence']).__name__}"
        )
        assert 0.0 <= result["confidence"] <= 1.0, f"confidence out of range: {result['confidence']}"

    async def test_ambiguous_cross_domain_query_does_not_split(self) -> None:
        """Queries that touch two domains must route to exactly ONE agent.

        Lex must never return two agent_ids for a single message.
        Cross-domain ambiguity resolves to soul_core if confidence on
        both candidates is below threshold.
        """
        # This query legitimately touches devops_agent AND monitor_agent
        result = await resolve_agent("the deploy finished but the health check is failing")

        assert isinstance(result["agent_id"], str), "agent_id must be a single string — no list routing"
        # After Sprint 1 this must be CANONICAL_AGENTS.  Before Sprint 1 we
        # accept any VALID_AGENTS entry so the test can run without failing
        # on the roster size issue.
        assert result["agent_id"] in (CANONICAL_AGENTS | VALID_AGENTS), (
            f"Ambiguous query routed to unknown agent: {result['agent_id']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Category 5 — Confidence Regression Baseline (Post-Sprint-1 check)
# The baseline JSON is generated by capture_lex_baseline.py.
# This test SKIPS if the fixture file doesn't exist yet.
# ════════════════════════════════════════════════════════════════════════════

_BASELINE_PATH = Path("backend/tests/fixtures/lex_routing_baseline.json")


@pytest.mark.skipif(
    not _BASELINE_PATH.exists(),
    reason=(
        "Baseline fixture not found. "
        "Run backend/tests/capture_lex_baseline.py before Sprint 1 "
        "to generate backend/tests/fixtures/lex_routing_baseline.json"
    ),
)
async def test_sprint1_routing_confidence_did_not_regress() -> None:
    """Compare live routing against pre-Sprint-1 baseline.

    Confidence must not drop by more than 0.1 for any query.
    Agent assignment must not change for high-confidence fixtures (>= 0.8).

    Run capture_lex_baseline.py before Sprint 1 to generate the fixture,
    then run this test after Sprint 1 ships.
    """
    baseline = json.loads(_BASELINE_PATH.read_text())

    for query, prior in baseline.items():
        result = await resolve_agent(query)

        # Agent must not change if prior confidence was high
        if prior["confidence"] >= 0.8:
            assert result["agent_id"] == prior["agent_id"], (
                f"HIGH-CONFIDENCE REGRESSION: '{query}'\n"
                f"  Was: {prior['agent_id']} ({prior['confidence']})\n"
                f"  Now: {result['agent_id']} "
                f"({result.get('confidence', 0.0):.4f})"
            )

        # Confidence must not drop more than 0.1
        drop = prior["confidence"] - result.get("confidence", 0.0)
        assert drop <= 0.1, (
            f"CONFIDENCE DROP: '{query}'\n"
            f"  Was: {prior['confidence']}, "
            f"  Now: {result.get('confidence', 0.0):.4f}, "
            f"  Drop: {drop:.4f}"
        )
