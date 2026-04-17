#!/usr/bin/env python3
"""
fix_datetime_deprecated.py — Replace deprecated datetime.utcnow() and
datetime.utcfromtimestamp() calls with their timezone-aware equivalents.

Replacements
------------
  datetime.utcnow()                →  datetime.now(UTC)
  datetime.utcfromtimestamp(ts)    →  datetime.fromtimestamp(ts, tz=UTC)

Also ensures `from datetime import UTC` is present wherever the replacement
is made.  If the file already imports `timezone` or `datetime.timezone.utc`,
it is preserved and UTC is added alongside it.

Exit codes
----------
0  No deprecated calls found, or all were mechanically fixed.
1  Unexpected error during processing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_UTCNOW_RE = re.compile(r"\bdatetime\.utcnow\(\)")
_UTCFROMTS_RE = re.compile(r"\bdatetime\.utcfromtimestamp\(([^)]+)\)")

# Match existing datetime import line so we can augment it
_DATETIME_IMPORT_RE = re.compile(
    r"^(from datetime import )([^\n]+)$",
    re.MULTILINE,
)

_SCAN_EXTS = {".py"}


def _ensure_utc_import(text: str) -> str:
    """Add UTC to the `from datetime import ...` line if not already there."""
    m = _DATETIME_IMPORT_RE.search(text)
    if m:
        imports_str = m.group(2)
        existing = {s.strip() for s in imports_str.split(",")}
        if "UTC" not in existing:
            new_imports = ", ".join(sorted(existing | {"UTC"}))
            text = text[: m.start(2)] + new_imports + text[m.end(2) :]
    else:
        # No datetime import yet — add one at the top after __future__
        future_m = re.search(r"^from __future__ import annotations\n", text, re.MULTILINE)
        insert_after = future_m.end() if future_m else 0
        text = text[:insert_after] + "from datetime import UTC\n" + text[insert_after:]
    return text


def _fix_file(path: Path) -> tuple[bool, str]:
    """Return (changed, description)."""
    text = path.read_text(encoding="utf-8")

    has_utcnow = bool(_UTCNOW_RE.search(text))
    has_utcfromts = bool(_UTCFROMTS_RE.search(text))

    if not has_utcnow and not has_utcfromts:
        return False, ""

    rel = str(path.relative_to(_ROOT))
    new_text = text

    if has_utcnow:
        new_text = _UTCNOW_RE.sub("datetime.now(UTC)", new_text)

    if has_utcfromts:
        new_text = _UTCFROMTS_RE.sub(r"datetime.fromtimestamp(\1, tz=UTC)", new_text)

    new_text = _ensure_utc_import(new_text)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        changes: list[str] = []
        if has_utcnow:
            changes.append("utcnow()")
        if has_utcfromts:
            changes.append("utcfromtimestamp()")
        return True, f"  FIXED {rel}  ({', '.join(changes)} → UTC-aware)"

    return False, f"  SKIP  {rel}  (no rewritable pattern after parse)"


def main() -> int:
    fixed: list[str] = []
    errors: list[str] = []

    for fpath in _ROOT.rglob("*.py"):
        parts = set(fpath.parts)
        if parts & {".venv", "node_modules", "__pycache__", ".git"}:
            continue
        try:
            changed, desc = _fix_file(fpath)
            if changed:
                print(desc)
                fixed.append(desc)
        except OSError as exc:
            msg = f"  ERROR {fpath}: {exc}"
            print(msg)
            errors.append(msg)

    print(f"\nSummary: {len(fixed)} file(s) fixed, {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
