"""Sprint 1 — WebGen Intercept Guard Tests
==========================================
Verifies that:
1. Plain "make me a X website" messages trigger the webgen intercept.
2. Messages containing any valid agent name bypass the webgen intercept
   and are routed to soul_core / the normal agent loop.
3. "show me the website" triggers the operator answer (no intercept).

Run with:
    pytest backend/tests/test_chat_webgen_intercept.py -v
"""

from __future__ import annotations

import re
import pytest

# ── Replicate the exact regex logic from backend/server.py ──────────────────

_WEBGEN_RE = re.compile(
    r'\b(make|build|create|generate|design|develop|spin\s+up|code)\b'
    r'(?:\s+(?:me|us|a|an|the|my|our|their|one))?\s*'
    r'(?:[\w\s&\'\-]{0,40}?)\s*'
    r'(?:website|web\s*site|web\s*app|landing\s*page|homepage|web\s*page|site\b)',
    re.IGNORECASE,
)

_AGENT_NAME_RE = re.compile(
    r'\b(soul[\s_]core|devops[\s_]agent|monitor[\s_]agent|self[\s_]healer[\s_]?agent|'
    r'code[\s_]review[\s_]agent|security[\s_]agent|data[\s_]agent|comms[\s_]agent|'
    r'cs[\s_]agent|it[\s_]agent|knowledge[\s_]agent|ocr[\s_]agent|'
    r'(soul|devops|monitor|security|data|comms|cs|it|knowledge|ocr)\s+agent|'
    r'\w[\w\s]{1,30}agent(?!\s*(?:website|web|app|page|site)))\b',
    re.IGNORECASE,
)


def _would_intercept(message: str) -> bool:
    """True if server.py would take the direct webgen path (not agent loop)."""
    return bool(_WEBGEN_RE.search(message)) and not bool(_AGENT_NAME_RE.search(message))


# ── Cases that SHOULD trigger the webgen intercept ──────────────────────────

@pytest.mark.parametrize("msg", [
    "make me a plumbing website",
    "build a consulting website for my firm",
    "create a landing page for my bakery",
    "design a website for my startup",
    "generate a web app for booking",
    "make a homepage for our startup",
    "develop a website for our law firm",
    "spin up a site for us",
    "build our company website",
    # Webgen without any agent name mentioned
    "create a modern portfolio website",
])
def test_webgen_intercept_fires(msg: str) -> None:
    """These messages should hit the direct webgen pipeline."""
    assert _would_intercept(msg), (
        f"Expected webgen intercept for: {msg!r}\n"
        f"  WEBGEN_RE matched: {bool(_WEBGEN_RE.search(msg))}\n"
        f"  AGENT_NAME_RE matched: {bool(_AGENT_NAME_RE.search(msg))}"
    )


# ── Cases that MUST bypass webgen (agent name present) ──────────────────────

@pytest.mark.parametrize("msg", [
    # Exact user message from the screenshot
    "use the prompt optimizer agent first to make this prompt less ambiguous "
    "and make a new consulting website for me",
    # All 11 agent IDs (underscore form)
    "use soul_core and make a website",
    "have devops_agent deploy the site and build a website",
    "ask monitor_agent to check the logs and create a website",
    "call self_healer_agent to fix the crash and make a landing page",
    "run code_review_agent on the diff then build the site",
    "run security_agent and create the web app",
    "use data_agent to seed the DB then generate a website",
    "alert comms_agent and design a homepage",
    "check with cs_agent first then make a website",
    "use it_agent to diagnose the network then build a site",
    "ask knowledge_agent and create a landing page",
    "run ocr_agent on the PDF then make a web page",
    # Natural-language agent name forms
    "use the devops agent to deploy and build a website",
    "ask the cs agent and make a site for me",
    "have the knowledge agent search and create a webpage",
    "ask soul core to reflect then build a consulting website",
    "use comms agent and make a landing page",
])
def test_webgen_intercept_bypassed_with_agent_name(msg: str) -> None:
    """Messages naming an agent must NOT hit the direct webgen pipeline."""
    assert not _would_intercept(msg), (
        f"Expected webgen intercept BYPASS for: {msg!r}\n"
        f"  WEBGEN_RE matched: {bool(_WEBGEN_RE.search(msg))}\n"
        f"  AGENT_NAME_RE matched: {bool(_AGENT_NAME_RE.search(msg))}"
    )


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_webgen_no_match_for_plain_chat() -> None:
    """Ordinary messages must not trigger webgen."""
    assert not _would_intercept("hello")
    assert not _would_intercept("what is the status of my tasks?")
    assert not _would_intercept("show me the website you built")    # "I need a website" has no action verb — regex does not match (correct)
    assert not _would_intercept("I need a website for my restaurant")

def test_agent_name_regex_covers_all_canonical_agents() -> None:
    """Every canonical agent ID must be matched by the agent-name guard."""
    canonical = [
        "soul_core", "devops_agent", "monitor_agent", "self_healer_agent",
        "code_review_agent", "security_agent", "data_agent", "comms_agent",
        "cs_agent", "it_agent", "knowledge_agent", "ocr_agent",
    ]
    for agent_id in canonical:
        msg = f"use {agent_id} and make a website"
        assert _AGENT_NAME_RE.search(msg), (
            f"Agent ID {agent_id!r} not matched by _AGENT_NAME_RE in: {msg!r}"
        )


def test_timeout_config() -> None:
    """AGENT_STEP_TIMEOUT_SECONDS must be >= 90 after Sprint 1."""
    from backend.config import AGENT_STEP_TIMEOUT_SECONDS
    assert AGENT_STEP_TIMEOUT_SECONDS >= 90, (
        f"Timeout too low: {AGENT_STEP_TIMEOUT_SECONDS}s — must be >= 90"
    )


def test_router_model_is_lex_v3() -> None:
    """LEX_ROUTER_MODEL default must be lex-v3 (fine-tuned router)."""
    from backend.orchestrator.lex_router import LEX_ROUTER_MODEL
    assert LEX_ROUTER_MODEL == "lex-v3", (
        f"Expected lex-v3, got: {LEX_ROUTER_MODEL!r}"
    )
