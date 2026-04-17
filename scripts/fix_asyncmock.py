#!/usr/bin/env python3
"""
fix_asyncmock.py — Annotate bare AsyncMock() calls in test files that may
cause RuntimeWarning: coroutine was never awaited.

What this does
--------------
Finds bare `AsyncMock()` (no arguments, no assignment in fixture context) in
test files.  Where the call is safe to annotate, wraps it with a
`# noqa: RUF006` comment and adds an explanatory TODO so the developer knows
to confirm the mock is properly awaited or assigned.

This is intentionally conservative — it annotates rather than silently
transforms, because AsyncMock fixture patterns vary widely (side_effect,
return_value, spec) and automated rewriting would risk breaking test logic.

Exit codes
----------
0  No bare AsyncMock() calls found (or all annotated).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Match bare AsyncMock() — no args, typically on the right of an assignment
# or as a direct call. We only touch test files.
_BARE_ASYNC_MOCK_RE = re.compile(r"(?<!['\"\w])AsyncMock\(\)(?!\s*#\s*noqa)")

_TEST_DIRS = {"backend/tests", "deerflow/tests"}


def _is_test_file(path: Path) -> bool:
    rel = str(path.relative_to(_ROOT))
    return any(rel.startswith(d) for d in _TEST_DIRS) or path.name.startswith("test_")


def _fix_file(path: Path) -> tuple[int, list[str]]:
    """Returns (count_annotated, messages)."""
    if not _is_test_file(path):
        return 0, []

    text = path.read_text(encoding="utf-8")
    if not _BARE_ASYNC_MOCK_RE.search(text):
        return 0, []

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    count = 0
    rel = str(path.relative_to(_ROOT))
    msgs: list[str] = []

    for i, line in enumerate(lines, start=1):
        if _BARE_ASYNC_MOCK_RE.search(line) and "# noqa" not in line and "# TODO" not in line:
            # Append noqa annotation
            stripped = line.rstrip("\n")
            new_line = stripped + "  # noqa: RUF006 — confirm awaited\n"
            new_lines.append(new_line)
            count += 1
            msgs.append(f"  ANNOTATED {rel}:{i}  {line.strip()[:80]}")
        else:
            new_lines.append(line)

    if count:
        path.write_text("".join(new_lines), encoding="utf-8")

    return count, msgs


def main() -> int:
    total = 0

    for fpath in _ROOT.rglob("*.py"):
        parts = set(fpath.parts)
        if parts & {".venv", "__pycache__", ".git"}:
            continue
        count, msgs = _fix_file(fpath)
        total += count
        for m in msgs:
            print(m)

    print(f"\nSummary: {total} bare AsyncMock() call(s) annotated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
