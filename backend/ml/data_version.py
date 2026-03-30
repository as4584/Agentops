"""
Data Versioner — Tracks dataset versions and integrity.
========================================================
Computes content hashes for training data directories so every experiment
run can record exactly which dataset version it trained on.

No cloud dependency — uses SHA-256 over file contents.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config import TRAINING_DATA_DIR, ML_DIR
from backend.utils import logger


class DataVersioner:
    """Tracks data directory versions via content hashing."""

    def __init__(
        self,
        training_dir: Optional[Path] = None,
        versions_dir: Optional[Path] = None,
    ) -> None:
        self._data_dir = training_dir or TRAINING_DATA_DIR
        self._versions_dir = versions_dir or (ML_DIR / "data_versions")
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._versions_dir / "manifest.json"
        self._manifest: dict[str, Any] = self._load_manifest()

    def compute_version(self, subdir: str = "") -> dict[str, Any]:
        """Compute a version hash for the data directory (or a subdirectory)."""
        target = self._data_dir / subdir if subdir else self._data_dir

        if not target.exists():
            raise FileNotFoundError(f"Data directory not found: {target}")

        files_info = []
        hasher = hashlib.sha256()

        for path in sorted(target.rglob("*")):
            if path.is_dir() or ".git" in path.parts:
                continue
            rel = str(path.relative_to(target))
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            size = path.stat().st_size
            files_info.append({"path": rel, "hash": content_hash, "size": size})
            hasher.update(f"{rel}:{content_hash}".encode())

        version_hash = hasher.hexdigest()[:16]

        version = {
            "version": version_hash,
            "directory": str(target.relative_to(self._data_dir)) if subdir else ".",
            "file_count": len(files_info),
            "total_size": sum(f["size"] for f in files_info),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "files": files_info,
        }

        # Save to manifest
        self._manifest[version_hash] = {
            "directory": version["directory"],
            "file_count": version["file_count"],
            "total_size": version["total_size"],
            "computed_at": version["computed_at"],
        }
        self._save_manifest()

        # Save full version file
        version_path = self._versions_dir / f"{version_hash}.json"
        version_path.write_text(json.dumps(version, indent=2))

        logger.info(
            f"[DataVersioner] Version {version_hash}: "
            f"{version['file_count']} files, {version['total_size']} bytes"
        )
        return version

    def get_version(self, version_hash: str) -> Optional[dict[str, Any]]:
        """Retrieve a previously computed version."""
        path = self._versions_dir / f"{version_hash}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def list_versions(self) -> list[dict[str, Any]]:
        """List all known data versions."""
        return [
            {"version": k, **v}
            for k, v in sorted(
                self._manifest.items(),
                key=lambda x: x[1].get("computed_at", ""),
                reverse=True,
            )
        ]

    def diff_versions(self, v1: str, v2: str) -> dict[str, Any]:
        """Compare two data versions — show added, removed, modified files."""
        data1 = self.get_version(v1)
        data2 = self.get_version(v2)
        if not data1 or not data2:
            raise KeyError(f"Version not found: {v1 if not data1 else v2}")

        files1 = {f["path"]: f["hash"] for f in data1["files"]}
        files2 = {f["path"]: f["hash"] for f in data2["files"]}

        added = [p for p in files2 if p not in files1]
        removed = [p for p in files1 if p not in files2]
        modified = [p for p in files1 if p in files2 and files1[p] != files2[p]]

        return {
            "v1": v1,
            "v2": v2,
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": len(files1) - len(removed) - len(modified),
        }

    def _load_manifest(self) -> dict[str, Any]:
        if self._manifest_path.exists():
            try:
                return json.loads(self._manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_manifest(self) -> None:
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2))
