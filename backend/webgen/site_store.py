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

from backend.webgen.models import SiteProject


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
