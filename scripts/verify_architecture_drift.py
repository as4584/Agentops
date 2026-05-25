#!/usr/bin/env python3
"""
Architecture drift verifier — Sprint 3.

Checks these invariants (machine-verifiable):
1. Tool registry and MCP_TOOL_MAP agree on GitNexus tools.
2. GitNexus tools are only permitted to approved agents.
3. Operator-only mode is set in config.
4. No public API exposes arbitrary GitNexus queries to unprivileged agents.

Exits 0 when all checks pass.
Exits 1 when any invariant is violated (prints named failures).

Usage:
    python scripts/verify_architecture_drift.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import AGENTOP_DEPLOYMENT_MODE
from backend.mcp import MCP_TOOL_MAP
from backend.tools import TOOL_REGISTRY

# Agents that are permitted to use GitNexus tools
_APPROVED_GITNEXUS_AGENTS = frozenset({"code_review_agent", "devops_agent", "security_agent"})

# Expected GitNexus tool set
_EXPECTED_GITNEXUS_TOOLS = frozenset(
    {
        "mcp_gitnexus_query",
        "mcp_gitnexus_context",
        "mcp_gitnexus_impact",
        "mcp_gitnexus_detect_changes",
        "mcp_gitnexus_list_repos",
    }
)


def _check_gitnexus_tool_parity(failures: list[str]) -> None:
    """INV: Tool registry and MCP_TOOL_MAP agree on GitNexus tools."""
    registry_gitnexus = frozenset(k for k in TOOL_REGISTRY if k.startswith("mcp_gitnexus_"))
    map_gitnexus = frozenset(k for k, v in MCP_TOOL_MAP.items() if v[0] == "gitnexus")

    only_in_registry = registry_gitnexus - map_gitnexus
    only_in_map = map_gitnexus - registry_gitnexus

    if only_in_registry:
        failures.append(
            f"DRIFT: GitNexus tools in TOOL_REGISTRY but missing from MCP_TOOL_MAP: {sorted(only_in_registry)}"
        )
    if only_in_map:
        failures.append(f"DRIFT: GitNexus tools in MCP_TOOL_MAP but missing from TOOL_REGISTRY: {sorted(only_in_map)}")
    unexpected = (registry_gitnexus | map_gitnexus) - _EXPECTED_GITNEXUS_TOOLS
    if unexpected:
        failures.append(f"DRIFT: Unexpected GitNexus tools found (not in expected set): {sorted(unexpected)}")
    missing = _EXPECTED_GITNEXUS_TOOLS - registry_gitnexus
    if missing:
        failures.append(f"DRIFT: Expected GitNexus tools missing from registry: {sorted(missing)}")


def _check_gitnexus_agent_permissions(failures: list[str]) -> None:
    """INV: GitNexus tools are only in approved agents' permission lists."""
    from backend.agents import ALL_AGENT_DEFINITIONS

    for agent_id, defn in ALL_AGENT_DEFINITIONS.items():
        agent_gn = frozenset(t for t in defn.tool_permissions if t.startswith("mcp_gitnexus_"))
        if agent_gn and agent_id not in _APPROVED_GITNEXUS_AGENTS:
            failures.append(
                f"DRIFT: Agent '{agent_id}' has GitNexus permissions but is not in approved list "
                f"{sorted(_APPROVED_GITNEXUS_AGENTS)}. Tools: {sorted(agent_gn)}"
            )


def _check_deployment_mode(failures: list[str]) -> None:
    """INV: Deployment mode must be operator_only."""
    if AGENTOP_DEPLOYMENT_MODE != "operator_only":
        failures.append(
            f"DRIFT: AGENTOP_DEPLOYMENT_MODE={AGENTOP_DEPLOYMENT_MODE!r}. "
            "Expected 'operator_only'. Public SaaS mode is not supported."
        )


def _check_router_registry_alignment(failures: list[str]) -> None:
    """INV: Auto-router must know every registered agent ID."""
    from backend.agents import ALL_AGENT_DEFINITIONS
    from backend.orchestrator.lex_router import VALID_AGENTS

    registered = frozenset(ALL_AGENT_DEFINITIONS)
    routed = frozenset(VALID_AGENTS)
    if routed != registered:
        failures.append(
            "DRIFT: lex_router VALID_AGENTS does not match ALL_AGENT_DEFINITIONS. "
            f"Missing={sorted(registered - routed)} Extra={sorted(routed - registered)}"
        )


def _check_knowledge_rag_convergence(failures: list[str]) -> None:
    """INV: live knowledge retrieval must use ContextAssembler, not direct store searches."""
    root = Path(__file__).resolve().parent.parent
    orchestrator_source = (root / "backend" / "orchestrator" / "__init__.py").read_text(encoding="utf-8")
    route_source = (root / "backend" / "routes" / "knowledge.py").read_text(encoding="utf-8")

    if "self._knowledge_store.search(" in orchestrator_source:
        failures.append("DRIFT: knowledge agent still calls KnowledgeVectorStore.search directly.")
    if "self._knowledge_store.search_business_profiles(" in orchestrator_source:
        failures.append("DRIFT: business-profile retrieval still bypasses ContextAssembler.")
    if (
        "self._knowledge_store.rebuild_index(" in orchestrator_source
        or "self._knowledge_store.ensure_index(" in orchestrator_source
    ):
        failures.append("DRIFT: knowledge reindex/startup seed still rebuilds the legacy KnowledgeVectorStore.")
    if "retrieve_records(" not in orchestrator_source:
        failures.append("DRIFT: knowledge agent path is not using ContextAssembler.retrieve_records().")
    if "ContextAssembler" not in route_source or "retrieve_records(" not in route_source:
        failures.append("DRIFT: /knowledge search route is not using ContextAssembler retrieval.")
    if "seed_docs_to_qdrant(" not in route_source:
        failures.append("DRIFT: /knowledge reindex route is not using Qdrant doc seeding.")


def verify_all() -> list[str]:
    """Run all drift checks and return a list of failures (empty = clean)."""
    failures: list[str] = []
    _check_deployment_mode(failures)
    _check_gitnexus_tool_parity(failures)
    _check_gitnexus_agent_permissions(failures)
    _check_router_registry_alignment(failures)
    _check_knowledge_rag_convergence(failures)
    return failures


def main() -> int:
    failures = verify_all()
    if failures:
        print("Architecture drift check FAILED:")
        for f in failures:
            print(f"  [DRIFT] {f}")
        return 1
    else:
        print("Architecture drift check PASSED — all invariants satisfied.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
