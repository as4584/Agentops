#!/usr/bin/env python3
"""
GitNexus status reporter — Sprint 2 S2.3.

Usage:
    python scripts/gitnexus_status.py

Exits 0 when index is present and healthy.
Exits 1 when index is missing, stale, or GitNexus is disabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the project root without pip install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.mcp.gitnexus_health import get_gitnexus_health


def main() -> int:
    state = get_gitnexus_health()
    print(f"GitNexus Status Report")
    print(f"  Enabled            : {state.enabled}")
    print(f"  Repo               : {state.repo_name or '(not set)'}")
    print(f"  Index exists       : {state.index_exists}")
    print(f"  Transport available: {state.transport_available}")
    if state.index_exists:
        print(f"  Symbols            : {state.symbol_count:,}")
        print(f"  Relationships      : {state.relationship_count:,}")
        print(f"  Embeddings         : {'yes (' + str(state.symbol_count) + ')' if state.embeddings_present else 'no (0)'}")
        print(f"  Last analyzed      : {state.last_analyzed_at or '(unknown)'}")
        print(f"  Stale (>{state.stale_hours}h)      : {state.stale}")
    if state.reason:
        print(f"  Reason             : {state.reason}")
    usable = state.usable
    print(f"\n  Usable             : {'YES' if usable else 'NO'}")
    if not usable and state.index_exists and state.stale:
        print("\n  Next action: run  npx gitnexus analyze")
    elif not usable and not state.index_exists and state.enabled:
        print("\n  Next action: run  npx gitnexus analyze")
    elif not usable and not state.enabled:
        print("\n  Next action: set  GITNEXUS_ENABLED=true  in .env")
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
