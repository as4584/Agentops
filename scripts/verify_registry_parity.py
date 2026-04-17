#!/usr/bin/env python3
"""
Registry–router parity check.

Fails CI if the agent registry (ALL_AGENT_DEFINITIONS) and the router's
VALID_AGENTS set fall out of sync.

Any agent defined in the registry must appear in the router's valid set,
and vice versa — unless it is explicitly listed in _INTENTIONAL_EXCLUSIONS.

Usage
-----
    python scripts/verify_registry_parity.py

Exit codes
----------
0  — registry and router are in sync
1  — drift detected (printed to stdout)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents import ALL_AGENT_DEFINITIONS
from backend.orchestrator.lex_router import VALID_AGENTS

# Agents that are intentionally absent from one side.
# Document *why* each exclusion is intentional before adding here.
_INTENTIONAL_EXCLUSIONS: frozenset[str] = frozenset(
    {
        # Content pipeline and WebGen agents are internal pipeline stages;
        # they are routed to explicitly by their parent orchestrator, not by
        # the lex router, so they do not appear in VALID_AGENTS.
        "script_writer",
        "voice_agent",
        "avatar_video_agent",
        "qa_agent",
        "publisher_agent",
        "analytics_agent",
        "idea_intake_agent",
        "caption_agent",
        "trend_researcher",
    }
)


def check_parity(failures: list[str]) -> None:
    """Append human-readable drift descriptions to *failures* (in-place)."""
    registry_ids: set[str] = set(ALL_AGENT_DEFINITIONS.keys()) - _INTENTIONAL_EXCLUSIONS
    router_ids: set[str] = set(VALID_AGENTS) - _INTENTIONAL_EXCLUSIONS

    only_in_registry = registry_ids - router_ids
    only_in_router = router_ids - registry_ids

    if only_in_registry:
        failures.append(
            f"Agents in registry but missing from router VALID_AGENTS "
            f"(add to router or _INTENTIONAL_EXCLUSIONS): {sorted(only_in_registry)}"
        )

    if only_in_router:
        failures.append(
            f"Agents in router VALID_AGENTS but missing from registry "
            f"(add to ALL_AGENT_DEFINITIONS or _INTENTIONAL_EXCLUSIONS): {sorted(only_in_router)}"
        )


def main() -> int:
    failures: list[str] = []
    check_parity(failures)

    if failures:
        print("REGISTRY–ROUTER PARITY DRIFT DETECTED")
        print("=" * 60)
        for f in failures:
            print(f"  ✗ {f}")
        print()
        print("Fix: update ALL_AGENT_DEFINITIONS, VALID_AGENTS, or")
        print("     add the agent to _INTENTIONAL_EXCLUSIONS in this script.")
        return 1

    registry_count = len(ALL_AGENT_DEFINITIONS)
    router_count = len(VALID_AGENTS)
    print(
        f"Registry–router parity OK — {registry_count} registry agents, "
        f"{router_count} router agents (delta covered by intentional exclusions)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
