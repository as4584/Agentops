#!/usr/bin/env python3
"""
GitNexus index refresher — Sprint 2 S2.3.

Usage:
    python scripts/gitnexus_refresh.py [--embeddings] [--dry-run]

Options:
    --embeddings    Rebuild embeddings alongside the structural index.
                    WARNING: This can take several minutes and requires
                    a sentence-transformer model to be available locally.
                    NOTE: Omitting --embeddings on a re-analyze of a repo
                    that previously had embeddings will DESTROY the existing
                    embeddings. Always pass --embeddings if you want to keep them.
    --dry-run       Print the command that would be run without executing it.

The script reads .gitnexus/meta.json before and after to report changes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.mcp.gitnexus_health import get_gitnexus_health


def main() -> int:
    args = sys.argv[1:]
    use_embeddings = "--embeddings" in args
    dry_run = "--dry-run" in args

    if not shutil.which("npx"):
        print("ERROR: npx is not on PATH. Install Node.js first.", file=sys.stderr)
        return 1

    cmd = ["npx", "gitnexus", "analyze"]
    if use_embeddings:
        cmd.append("--embeddings")
    else:
        # Warn the operator that embeddings will be dropped if they existed.
        before = get_gitnexus_health()
        if before.embeddings_present:
            print(
                "WARNING: The current index has embeddings, but --embeddings was not passed.\n"
                "         Re-analyzing WITHOUT --embeddings will DELETE the existing embeddings.\n"
                "         Pass --embeddings to preserve them, or proceed to drop them.",
                file=sys.stderr,
            )
            resp = input("Continue without embeddings? [y/N] ").strip().lower()
            if resp != "y":
                print("Aborted.")
                return 1

    print(f"{'[DRY RUN] ' if dry_run else ''}Running: {' '.join(cmd)}")
    if dry_run:
        return 0

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"ERROR: gitnexus analyze exited {result.returncode}", file=sys.stderr)
        return result.returncode

    after = get_gitnexus_health()
    print(f"\nIndex refreshed:")
    print(f"  Symbols      : {after.symbol_count:,}")
    print(f"  Relationships: {after.relationship_count:,}")
    print(f"  Embeddings   : {'yes' if after.embeddings_present else 'no'}")
    print(f"  Last analyzed: {after.last_analyzed_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
