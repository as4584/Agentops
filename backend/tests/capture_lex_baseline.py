"""Capture pre-Sprint-1 Lex routing baseline.

Run this script ONCE before any Sprint 1 changes touch lex_router.py.
The output JSON becomes the regression fixture for
test_sprint1_routing_confidence_did_not_regress.

Usage:
    python backend/tests/capture_lex_baseline.py

Output:
    backend/tests/fixtures/lex_routing_baseline.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.orchestrator.lex_router import resolve_agent

_BASELINE_QUERIES: list[str] = [
    "restart ollama",
    "deploy to production",
    "scan for open ports",
    "fix lint errors",
    "what does the corpus say about VLAN 10",
    "send incident alert to ops team",
    "review the PR before merge",
    "tail backend logs",
    "check database schema",
    "help with billing issue",
]

_OUT = Path("backend/tests/fixtures/lex_routing_baseline.json")


async def capture_baseline() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for query in _BASELINE_QUERIES:
        result = await resolve_agent(query)
        results[query] = {
            "agent_id": result["agent_id"],
            "confidence": round(float(result.get("confidence", 0.0)), 4),
            "method": result.get("method", "unknown"),
        }
        print(
            f"  [{results[query]['method']:18s}] "
            f"{results[query]['agent_id']:22s} "
            f"conf={results[query]['confidence']:.4f}  "
            f"'{query}'"
        )
    return results


def main() -> None:
    print("Capturing pre-Sprint-1 Lex routing baseline...\n")
    baseline = asyncio.run(capture_baseline())
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(baseline, indent=2))
    print(f"\nBaseline written to {_OUT}")
    print("\n--- JSON ---")
    print(json.dumps(baseline, indent=2))


if __name__ == "__main__":
    main()
