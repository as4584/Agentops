"""
Site Store — Persistence for website generation projects.
=========================================================
File-backed JSON storage, one file per project.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from backend.webgen.models import SiteProject, WebgenRunState, WebgenRunStatus


def _atomic_write_json(path: Path, data: object) -> None:
    """Write JSON atomically via a temp file and os.replace()."""
    content = json.dumps(data, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class SiteStore:
    """
    Persistent store for SiteProject instances.

    Storage layout:
        base_dir/
            {project_id}.json
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent / "memory" / "webgen_projects"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, project: SiteProject) -> None:
        """Save / update a project atomically."""
        path = self.base_dir / f"{project.id}.json"
        _atomic_write_json(path, project.model_dump())

    def load(self, project_id: str) -> SiteProject | None:
        """Load a project by ID."""
        path = self.base_dir / f"{project_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return SiteProject(**data)
        except Exception:
            return None

    def list_projects(self) -> list[SiteProject]:
        """List all projects."""
        projects = []
        for path in sorted(self.base_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                projects.append(SiteProject(**data))
            except Exception:
                continue
        return projects

    def delete(self, project_id: str) -> bool:
        """Delete a project by ID."""
        path = self.base_dir / f"{project_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False


class WebgenRunStore:
    """
    Persistent store for WebgenRunState instances (one JSON file per run_id).

    Storage layout:
        base_dir/
            {run_id}.json
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent / "memory" / "webgen_runs"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, run: WebgenRunState) -> None:
        """Save / update a run snapshot atomically."""
        path = self.base_dir / f"{run.run_id}.json"
        _atomic_write_json(path, run.model_dump())

    def load(self, run_id: str) -> WebgenRunState | None:
        """Load a run by ID."""
        path = self.base_dir / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return WebgenRunState(**data)
        except Exception:
            return None

    def get_active_run(self) -> WebgenRunState | None:
        """Return the most recently started run with RUNNING status, if any."""
        runs: list[WebgenRunState] = []
        for path in self.base_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                runs.append(WebgenRunState(**data))
            except Exception:
                continue
        running = [r for r in runs if r.status == WebgenRunStatus.RUNNING]
        if not running:
            return None
        return max(running, key=lambda r: r.started_at)
