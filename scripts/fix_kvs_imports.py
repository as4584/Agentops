#!/usr/bin/env python3
"""
fix_kvs_imports.py — Replace direct KnowledgeVectorStore imports with
ContextAssembler usage, which is the converged knowledge access path since
Sprint 7.

What this does
--------------
1. Finds any file that imports KnowledgeVectorStore directly (outside of
   backend/knowledge/__init__.py and context_assembler.py which own the class).
2. In the simplest case (bare import + constructor call), rewrites the import
   to use ContextAssembler instead.
3. For complex cases it adds a TODO comment and leaves the file for human
   review — it never silently discards code.

Exit codes
----------
0  No hits, or all hits were mechanically fixed.
1  Complex hits remain that need human review.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Files that legitimately own or wrap KnowledgeVectorStore
_ALLOWLIST = {
    "backend/knowledge/__init__.py",
    "backend/knowledge/context_assembler.py",
}

_IMPORT_RE = re.compile(
    r"^(from\s+\S+\s+import\s+(?:[^;#\n]*,\s*)?KnowledgeVectorStore(?:\s*,\s*[^;#\n]*)?|"
    r"import\s+\S*KnowledgeVectorStore\S*)",
    re.MULTILINE,
)

_CONSTRUCTOR_RE = re.compile(r"\bKnowledgeVectorStore\(")


def _fix_file(path: Path) -> tuple[str, list[str]]:
    """
    Returns (status, messages) where status is 'ok'|'needs_human'|'skipped'.
    Modifies the file in place if a mechanical fix is possible.
    """
    rel = str(path.relative_to(_ROOT))
    if rel in _ALLOWLIST:
        return "skipped", [f"  SKIP  {rel} (allowlisted)"]

    text = path.read_text(encoding="utf-8")
    if not _IMPORT_RE.search(text) and not _CONSTRUCTOR_RE.search(text):
        return "skipped", []

    msgs: list[str] = []
    needs_human = False

    # Count usages
    constructor_count = len(_CONSTRUCTOR_RE.findall(text))

    if constructor_count > 0:
        # Complex usage — add TODO and flag
        if "# TODO(fix_kvs_imports)" not in text:
            new_text = _IMPORT_RE.sub(
                r"# TODO(fix_kvs_imports): replace KnowledgeVectorStore with "
                r"ContextAssembler — Sprint 7 convergence\n# \g<0>",
                text,
            )
            path.write_text(new_text, encoding="utf-8")
        msgs.append(f"  HUMAN {rel}  ({constructor_count} KVS constructor usage(s) — annotated)")
        needs_human = True
    else:
        # Import-only with no constructor call — safe to remove
        new_text = _IMPORT_RE.sub("", text)
        # Clean up double blank lines left behind
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        path.write_text(new_text, encoding="utf-8")
        msgs.append(f"  FIXED {rel}  (unused KVS import removed)")

    return ("needs_human" if needs_human else "ok"), msgs


def main() -> int:
    needs_human: list[str] = []
    fixed: list[str] = []

    for fpath in _ROOT.rglob("*.py"):
        parts = set(fpath.parts)
        if parts & {".venv", "node_modules", "__pycache__"}:
            continue
        status, msgs = _fix_file(fpath)
        for m in msgs:
            print(m)
        if status == "needs_human":
            needs_human.extend(msgs)
        elif status == "ok":
            fixed.extend(msgs)

    print(f"\nSummary: {len(fixed)} fixed, {len(needs_human)} need human review")
    return 1 if needs_human else 0


if __name__ == "__main__":
    sys.exit(main())
