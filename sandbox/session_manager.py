from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScoreThreshold:
    performance: float = 90.0
    accessibility: float = 90.0
    best_practices: float = 90.0
    seo: float = 90.0


class SandboxSession:
    def __init__(
        self,
        project_root: Path,
        task: str,
        model: str,
        session_id: str | None = None,
        threshold: ScoreThreshold | None = None,
    ) -> None:
        self.project_root = project_root
        self.task = task
        self.model = model
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.threshold = threshold or ScoreThreshold()
        self.root = Path("/tmp/ai-sandbox") / self.session_id
        self.workspace = self.root / "workspace"
        self.reports = self.root / "reports"
        self.meta_path = self.root / "meta.json"

    def create(self) -> dict[str, Any]:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": self.session_id,
            "task": self.task,
            "model": self.model,
            "created_at": _utc_now(),
            "threshold": {
                "performance": self.threshold.performance,
                "accessibility": self.threshold.accessibility,
                "best_practices": self.threshold.best_practices,
                "seo": self.threshold.seo,
            },
            "status": "active",
            "promoted_files": [],
        }
        self.meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def read_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            raise FileNotFoundError(f"Sandbox session '{self.session_id}' does not exist")
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _write_meta(self, data: dict[str, Any]) -> None:
        self.meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def promote(self, files: list[str]) -> list[str]:
        promoted: list[str] = []
        for rel_path in files:
            src = self.workspace / rel_path
            dst = self.project_root / rel_path
            if not src.exists() or not src.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            promoted.append(rel_path)

        meta = self.read_meta()
        meta["promoted_files"] = sorted(set(meta.get("promoted_files", []) + promoted))
        meta["last_promoted_at"] = _utc_now()
        self._write_meta(meta)
        return promoted

    @staticmethod
    def scores_meet_threshold(summary: dict[str, Any], threshold: ScoreThreshold) -> bool:
        audits = [
            ("performance", threshold.performance),
            ("accessibility", threshold.accessibility),
            ("best_practices", threshold.best_practices),
            ("seo", threshold.seo),
        ]
        for key, min_score in audits:
            if float(summary.get(key, 0)) < float(min_score):
                return False
        return True

    @staticmethod
    def parse_lhci_summary(summary_json_path: Path) -> dict[str, Any]:
        raw = json.loads(summary_json_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "summary" in raw and isinstance(raw["summary"], dict):
            raw = raw["summary"]
        return {
            "performance": float(raw.get("performance", 0)),
            "accessibility": float(raw.get("accessibility", 0)),
            "best_practices": float(raw.get("best-practices", raw.get("best_practices", 0))),
            "seo": float(raw.get("seo", 0)),
        }

    def append_log(
        self,
        before_scores: dict[str, Any] | None,
        after_scores: dict[str, Any] | None,
        promoted_files: list[str],
        deleted_at: str,
    ) -> None:
        log_file = self.project_root / "docs" / "SANDBOX_LOG.md"
        if not log_file.exists():
            header = (
                "# Sandbox Activity Log\n\n"
                "| Session ID | Task | Model | Before Scores | After Scores | Files Promoted | Deleted At |\n"
                "|---|---|---|---|---|---|---|\n"
            )
            log_file.write_text(header, encoding="utf-8")

        def _fmt_scores(scores: dict[str, Any] | None) -> str:
            if not scores:
                return "n/a"
            return (
                f"P:{scores.get('performance', 0)} "
                f"A:{scores.get('accessibility', 0)} "
                f"BP:{scores.get('best_practices', 0)} "
                f"SEO:{scores.get('seo', 0)}"
            )

        row = (
            f"| {self.session_id} | {self.task.replace('|', '/')} | {self.model} | "
            f"{_fmt_scores(before_scores)} | {_fmt_scores(after_scores)} | "
            f"{', '.join(promoted_files) if promoted_files else 'none'} | {deleted_at} |\n"
        )
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(row)

    def destroy(
        self,
        before_scores: dict[str, Any] | None = None,
        after_scores: dict[str, Any] | None = None,
        promoted_files: list[str] | None = None,
    ) -> None:
        deleted_at = _utc_now()
        promoted = promoted_files or []
        if self.root.exists():
            self.append_log(before_scores, after_scores, promoted, deleted_at)
            shutil.rmtree(self.root, ignore_errors=True)


def list_active_sessions(base_dir: Path = Path("/tmp/ai-sandbox")) -> list[dict[str, Any]]:
    if not base_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for child in sorted(base_dir.iterdir()):
        meta = child / "meta.json"
        if not child.is_dir() or not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["path"] = str(child)
            sessions.append(data)
        except Exception:
            continue
    return sessions
