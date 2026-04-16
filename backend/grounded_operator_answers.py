"""Deterministic grounded replies for high-risk operator questions.

These helpers are intentionally narrow. They only answer a small set of
questions where invented behavior is especially damaging:

- dependency health summaries
- MCP bridge degradation semantics
- GitNexus fail-closed semantics
- v2 executor timeout fallback behavior

Everything here is derived from live dependency payloads or fixed
implementation facts in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GroundedChatReply:
    """A deterministic chat reply that bypasses freeform LLM narration."""

    agent_id: str
    message: str


def detect_grounded_chat_query(message: str) -> str | None:
    """Return the grounded reply kind for a high-risk operator query."""
    text = " ".join(message.lower().split())

    dependency_terms = (
        "ollama",
        "mcp bridge",
        "mcpbridge",
        "gitnexus",
        "docker",
        "ruff",
    )
    dependency_hits = sum(term in text for term in dependency_terms)

    if _contains_any(text, ("dependency health", "health/deps")):
        return "dependency_health"
    if dependency_hits >= 3 and _contains_any(text, ("health", "status", "summarize", "summary")):
        return "dependency_health"

    if (
        _contains_any(text, ("mcp bridge", "mcpbridge"))
        and "docker" in text
        and "gitnexus" in text
        and _contains_any(text, ("degrade", "degrades", "degradation", "unavailable"))
    ):
        return "mcpbridge_degradation"

    if (
        "gitnexus" in text
        and _contains_any(text, ("blocked", "block", "stale", "unavailable"))
        and _contains_any(text, ("github", "non-gitnexus", "continue to work", "still work", "unaffected"))
    ):
        return "gitnexus_fail_closed"

    if _contains_any(text, ("first v2 agent step", "v2 agent step", "v2 step")) and _contains_any(
        text, ("times out", "timed out", "timeout")
    ):
        return "v2_timeout_fallback"

    return None


def build_grounded_chat_reply(
    kind: str,
    requested_agent_id: str,
    deps_snapshot: dict[str, Any] | None = None,
) -> GroundedChatReply | None:
    """Build a deterministic reply for a previously detected grounded query."""
    if kind == "dependency_health":
        if deps_snapshot is None:
            return None
        return GroundedChatReply(
            agent_id=_resolved_agent_id(requested_agent_id, default_agent_id="devops_agent"),
            message=_format_dependency_health_reply(deps_snapshot),
        )

    if kind == "mcpbridge_degradation":
        return GroundedChatReply(
            agent_id=_resolved_agent_id(requested_agent_id, default_agent_id="devops_agent"),
            message=_format_mcpbridge_degradation_reply(),
        )

    if kind == "gitnexus_fail_closed":
        return GroundedChatReply(
            agent_id=_resolved_agent_id(requested_agent_id, default_agent_id="code_review_agent"),
            message=_format_gitnexus_fail_closed_reply(),
        )

    if kind == "v2_timeout_fallback":
        return GroundedChatReply(
            agent_id=_resolved_agent_id(requested_agent_id, default_agent_id="code_review_agent"),
            message=_format_v2_timeout_reply(),
        )

    return None


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _resolved_agent_id(requested_agent_id: str, default_agent_id: str) -> str:
    return default_agent_id if requested_agent_id == "auto" else requested_agent_id


def _status_label(ok: Any) -> str:
    return "OK" if bool(ok) else "NOT OK"


def _format_dependency_health_reply(snapshot: dict[str, Any]) -> str:
    deps = snapshot.get("dependencies") or {}

    ollama = deps.get("ollama") or {}
    mcp_bridge = deps.get("mcp_bridge") or {}
    docker = deps.get("docker") or {}
    ruff = deps.get("ruff") or {}
    gitnexus = deps.get("gitnexus") or {}
    gitnexus_detail = gitnexus.get("detail") if isinstance(gitnexus.get("detail"), dict) else {}
    mcp_detail = mcp_bridge.get("detail") if isinstance(mcp_bridge.get("detail"), dict) else {}

    gitnexus_reason = gitnexus_detail.get("reason") or ""
    gitnexus_reason_suffix = f" Reason: {gitnexus_reason}" if gitnexus_reason else ""

    lines = [
        "Grounded from live /health/deps plus backend/server.py and backend/mcp/gitnexus_health.py.",
        f"Overall status: {snapshot.get('status', 'unknown')}.",
        f"- Ollama: {_status_label(ollama.get('ok'))} - {ollama.get('detail', 'no detail')}",
        (
            f"- MCP bridge: {_status_label(mcp_bridge.get('ok'))} - "
            f"enabled={mcp_detail.get('enabled')}, cli_available={mcp_detail.get('cli_available')}, "
            f"initialised={mcp_detail.get('initialised')}, "
            f"discovered_tools={mcp_detail.get('discovered_tools')}/{mcp_detail.get('declared_tool_count')}"
        ),
        f"- Docker: {_status_label(docker.get('ok'))} - {docker.get('path', 'path unavailable')}",
        f"- Ruff: {_status_label(ruff.get('ok'))} - {ruff.get('path', 'path unavailable')}",
    ]

    if gitnexus_detail.get("enabled"):
        lines.append(
            f"- GitNexus: {_status_label(gitnexus.get('ok'))} - "
            f"usable={gitnexus_detail.get('usable')}, index_exists={gitnexus_detail.get('index_exists')}, "
            f"transport_available={gitnexus_detail.get('transport_available')}, "
            f"stale={gitnexus_detail.get('stale')}."
            f"{gitnexus_reason_suffix}"
        )
    else:
        lines.append(
            f"- GitNexus: DISABLED - usable={gitnexus_detail.get('usable')}, "
            f"index_exists={gitnexus_detail.get('index_exists')}, "
            f"transport_available={gitnexus_detail.get('transport_available')}. "
            "backend/server.py treats disabled GitNexus as non-degraded platform health."
            f"{gitnexus_reason_suffix}"
        )

    return "\n".join(lines)


def _format_mcpbridge_degradation_reply() -> str:
    lines = [
        "Grounded from backend/mcp/__init__.py, backend/mcp/gitnexus_health.py, and backend/tests/test_mcp_bridge.py.",
        "- If MCP_GATEWAY_ENABLED=false, MCPBridge returns a structured 'MCP Gateway disabled' error instead of trying to execute tools.",
        "- If Docker CLI is missing, MCPBridge initialises cleanly with cli_available=False and later returns a structured Docker error from call_tool instead of crashing.",
        "- _discover_tools is non-fatal. Discovery failures log a warning, leave the bridge initialised, and keep the process running.",
        "- GitNexus degradation is narrower than Docker degradation. Only GitNexus-mapped tools hit the fail-closed guard in call_tool.",
        "- GitNexus tool calls are blocked when get_gitnexus_health().usable is false, which covers disabled, missing index, stale index, or missing transport.",
        "- Non-GitNexus MCP tools are not blocked by GitNexus health. test_non_gitnexus_tool_unaffected_by_gitnexus_health covers that contract.",
    ]
    return "\n".join(lines)


def _format_gitnexus_fail_closed_reply() -> str:
    lines = [
        "Grounded from backend/mcp/__init__.py, backend/mcp/gitnexus_health.py, backend/models/__init__.py, and backend/tests/test_mcp_bridge.py.",
        "- MCPBridge.call_tool only applies the fail-closed branch when the mapped server is gitnexus.",
        "- GitNexusHealthState.usable is true only when GitNexus is enabled, transport is available, the index exists, and the index is not stale.",
        "- If usable is false, GitNexus tools return a structured 'GitNexus unavailable' error and stop there.",
        "- GitHub MCP tools do not go through that branch, so they still work as long as the MCP bridge itself is available.",
        "- The tests explicitly cover both sides: stale or disabled GitNexus is blocked, while a non-GitNexus MCP tool remains unaffected.",
    ]
    return "\n".join(lines)


def _format_v2_timeout_reply() -> str:
    lines = [
        "Grounded from backend/agents/__init__.py and backend/tests/test_base_agent_deep.py.",
        "- BaseAgent.process_message dispatches to process_message_v2 when AGENT_RUNTIME_V2 is enabled.",
        "- In process_message_v2, each executor turn is wrapped in asyncio.wait_for with the configured step timeout.",
        "- If step 1 times out before any turn completes, the agent logs the timeout, removes the duplicated trailing user message if needed, completes the task as a fallback, and returns the legacy single-pass chat path via _process_message_legacy(message, context).",
        "- That fallback exists so the request still gets a single-pass answer instead of falling through to the empty-turn branch that used to produce 'No response generated.'",
        "- There is no special retry loop, admin alert, or event-log side effect in this code path. The behavior is a direct fallback to the legacy chat path.",
    ]
    return "\n".join(lines)
