"""
GSD Store — JSON-backed persistent store for GSD workflow state.

All writes use an atomic tmp → rename pattern (same as job_store.py and
site_store.py) to guard against partial writes during interruptions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.models.gsd import (
    GSDMapResult,
    GSDPlan,
    GSDStateFile,
    GSDVerifyReport,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_GSD_ROOT = Path("backend/memory/gsd")
_STATE_PATH = _GSD_ROOT / "gsd_state.json"
_MAP_PATH = _GSD_ROOT / "map_docs.json"
_PHASES_ROOT = _GSD_ROOT / "phases"


def _atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via a sibling .tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.rename(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class GSDStore:
    """Manages all on-disk state for the GSD workflow."""

    # ---- State file -------------------------------------------------------

    def load_state(self) -> GSDStateFile:
        raw = _read_json(_STATE_PATH)
        if not raw:
            return GSDStateFile()
        return GSDStateFile.model_validate(raw)

    def save_state(self, state: GSDStateFile) -> None:
        state.last_updated = datetime.now(timezone.utc)
        _atomic_write(_STATE_PATH, state.model_dump_json(indent=2))

    # ---- Phase plans -------------------------------------------------------

    def save_plan(self, phase_n: int, plan: GSDPlan) -> None:
        plan_dir = _PHASES_ROOT / str(phase_n)
        plan_path = plan_dir / "plan.json"
        _atomic_write(plan_path, plan.model_dump_json(indent=2))
        # Also write the human-readable PLAN.md
        md_path = plan_dir / "PLAN.md"
        _atomic_write(md_path, _plan_to_markdown(plan))

    def load_plan(self, phase_n: int) -> GSDPlan | None:
        plan_path = _PHASES_ROOT / str(phase_n) / "plan.json"
        raw = _read_json(plan_path)
        if not raw:
            return None
        return GSDPlan.model_validate(raw)

    def list_phases(self) -> list[int]:
        if not _PHASES_ROOT.exists():
            return []
        return sorted(
            int(p.name) for p in _PHASES_ROOT.iterdir()
            if p.is_dir() and p.name.isdigit()
        )

    # ---- Execution logs ----------------------------------------------------

    def append_execution_log(self, phase_n: int, entry: str) -> None:
        log_path = _PHASES_ROOT / str(phase_n) / "EXECUTION_LOG.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")

    def read_execution_log(self, phase_n: int) -> str:
        log_path = _PHASES_ROOT / str(phase_n) / "EXECUTION_LOG.md"
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8")

    # ---- Verify reports ----------------------------------------------------

    def save_verify_report(self, report: GSDVerifyReport, phase_n: int | None = None) -> None:
        key = str(phase_n) if phase_n is not None else "latest"
        report_path = _PHASES_ROOT / key / "VERIFY_REPORT.md"
        _atomic_write(report_path, _verify_report_to_markdown(report))
        json_path = _PHASES_ROOT / key / "verify_report.json"
        _atomic_write(json_path, report.model_dump_json(indent=2))

    def load_verify_report(self, phase_n: int | None = None) -> GSDVerifyReport | None:
        key = str(phase_n) if phase_n is not None else "latest"
        json_path = _PHASES_ROOT / key / "verify_report.json"
        raw = _read_json(json_path)
        if not raw:
            return None
        return GSDVerifyReport.model_validate(raw)

    # ---- Map docs ----------------------------------------------------------

    def save_map_docs(self, result: GSDMapResult) -> None:
        _atomic_write(_MAP_PATH, result.model_dump_json(indent=2))
        # Write individual human-readable docs to docs/gsd/
        docs_dir = Path("docs/gsd")
        docs_dir.mkdir(parents=True, exist_ok=True)
        for field_name, heading in (
            ("stack",        "STACK"),
            ("architecture", "ARCHITECTURE"),
            ("conventions",  "CONVENTIONS"),
            ("concerns",     "CONCERNS"),
        ):
            content = getattr(result, field_name, "") or ""
            _atomic_write(
                docs_dir / f"{heading}.md",
                f"# GSD: {heading}\n\n> Auto-generated by `/gsd:map-codebase`\n> "
                f"Generated: {result.generated_at.isoformat()}\n\n{content}",
            )

    def load_map_docs(self) -> GSDMapResult | None:
        raw = _read_json(_MAP_PATH)
        if not raw:
            return None
        return GSDMapResult.model_validate(raw)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _plan_to_markdown(plan: GSDPlan) -> str:
    lines = [
        f"# Phase {plan.phase}: {plan.title}",
        "",
        f"> {plan.description}",
        f"> Status: `{plan.status.value}`",
        f"> Created: {plan.created_at.isoformat()}",
        "",
        "## Tasks",
        "",
    ]
    for task in plan.tasks:
        lines.append(f"### [{task.wave}] {task.id} — {task.description}")
        if task.file_targets:
            lines.append(f"- **Files:** {', '.join(task.file_targets)}")
        if task.symbol_refs:
            lines.append(f"- **Symbols:** {', '.join(task.symbol_refs)}")
        if task.depends_on:
            lines.append(f"- **Depends on:** {', '.join(task.depends_on)}")
        lines.append(f"- **Status:** `{task.status.value}`")
        lines.append("")
    if plan.gatekeeper_violations:
        lines += ["## Gatekeeper Violations", ""]
        for v in plan.gatekeeper_violations:
            lines.append(f"- {v}")
    return "\n".join(lines)


def _verify_report_to_markdown(report: GSDVerifyReport) -> str:
    phase_str = str(report.phase) if report.phase is not None else "latest"
    lines = [
        f"# GSD Verify Report — Phase {phase_str}",
        "",
        f"> Generated: {report.generated_at.isoformat()}",
        "",
    ]
    for section_label, items in (
        ("✅ Passed",       report.passed),
        ("❌ Failed",       report.failed),
        ("❓ Unverifiable", report.unverifiable),
    ):
        lines.append(f"## {section_label} ({len(items)})")
        lines.append("")
        for item in items:
            lines.append(f"- **{item.description}** — {item.detail or item.status}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
gsd_store = GSDStore()
