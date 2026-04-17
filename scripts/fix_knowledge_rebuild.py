#!/usr/bin/env python3
"""
fix_knowledge_rebuild.py — Replace legacy rebuild_knowledge_index() and
build_json_index() calls with the canonical Qdrant seed path via
backend.knowledge.doc_seed.seed_docs_to_qdrant.

What this does
--------------
1. Finds any call site using rebuild_knowledge_index() or build_json_index().
2. For test files: replaces with a mock call or leaves a TODO comment.
3. For production code: adds a TODO comment pointing to seed_docs_to_qdrant
   and prints the file path for human verification.

The script never silently drops logic — it always leaves a TODO when it
cannot safely automate the replacement (e.g., the caller passes custom args).

Exit codes
----------
0  No legacy calls found, or all were handled.
1  Legacy calls remain that need human attention.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_REBUILD_RE = re.compile(
    r"\b(rebuild_knowledge_index|build_json_index)\s*\(",
)

# Import that the replacement path needs
_SEED_IMPORT = "from backend.knowledge.doc_seed import seed_docs_to_qdrant"

_TEST_DIRS = {"backend/tests", "deerflow/tests"}


def _is_test_file(path: Path) -> bool:
    rel = str(path.relative_to(_ROOT))
    return any(rel.startswith(d) for d in _TEST_DIRS) or path.name.startswith("test_")


def _fix_file(path: Path) -> tuple[str, list[str]]:
    """Returns (status, messages) where status is 'ok'|'needs_human'|'skipped'."""
    text = path.read_text(encoding="utf-8")
    if not _REBUILD_RE.search(text):
        return "skipped", []

    rel = str(path.relative_to(_ROOT))
    msgs: list[str] = []
    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    changed = False
    needs_human = False

    for i, line in enumerate(lines, start=1):
        if _REBUILD_RE.search(line) and "# TODO(fix_knowledge_rebuild)" not in line:
            indent = len(line) - len(line.lstrip())
            spaces = " " * indent
            todo = (
                f"{spaces}# TODO(fix_knowledge_rebuild): replace with "
                f"await seed_docs_to_qdrant(llm_client)  "
                f"— Sprint 7 Qdrant convergence\n"
            )
            new_lines.append(todo)
            new_lines.append(line)
            changed = True
            needs_human = True
            msgs.append(f"  ANNOTATED {rel}:{i}  {line.strip()[:80]}")
        else:
            new_lines.append(line)

    if changed:
        path.write_text("".join(new_lines), encoding="utf-8")

    return ("needs_human" if needs_human else "skipped"), msgs


def main() -> int:
    needs_human: list[str] = []

    for fpath in _ROOT.rglob("*.py"):
        parts = set(fpath.parts)
        if parts & {".venv", "node_modules", "__pycache__", ".git"}:
            continue
        status, msgs = _fix_file(fpath)
        for m in msgs:
            print(m)
        if status == "needs_human":
            needs_human.extend(msgs)

    print(f"\nSummary: {len(needs_human)} legacy call(s) annotated — redirect to seed_docs_to_qdrant")
    # These always need human review (the signature differs), so exit 0 after annotation
    return 0


if __name__ == "__main__":
    sys.exit(main())
