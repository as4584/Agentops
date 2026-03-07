from __future__ import annotations

import json
import socket
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import (
    PLAYBOX_DIR,
    SANDBOX_DOCKER_CPU_LIMIT,
    SANDBOX_DOCKER_ENABLED,
    SANDBOX_DOCKER_IMAGE,
    SANDBOX_DOCKER_MEM_LIMIT,
    SANDBOX_DOCKER_NETWORK,
    SANDBOX_DOCKER_PIDS_LIMIT,
    SANDBOX_DOCKER_READONLY_ROOTFS,
    SANDBOX_BACKEND_PORT_RANGE_END,
    SANDBOX_BACKEND_PORT_RANGE_START,
    SANDBOX_FRONTEND_PORT_RANGE_END,
    SANDBOX_FRONTEND_PORT_RANGE_START,
    SANDBOX_ROOT_DIR,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _collect_reserved_ports(base_dir: Path) -> set[int]:
    if not base_dir.exists():
        return set()

    reserved_ports: set[int] = set()
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("status") != "active":
            continue
        session_ports = meta.get("reserved_ports")
        if not isinstance(session_ports, dict):
            continue
        session_ports_map = dict(session_ports)
        for key in ("frontend", "backend"):
            value = session_ports_map.get(key)
            if isinstance(value, int):
                reserved_ports.add(value)
    return reserved_ports


def _allocate_session_ports(base_dir: Path) -> dict[str, int]:
    reserved_ports = _collect_reserved_ports(base_dir)

    frontend_port: int | None = None
    for port in range(SANDBOX_FRONTEND_PORT_RANGE_START, SANDBOX_FRONTEND_PORT_RANGE_END + 1):
        if port in reserved_ports:
            continue
        if _is_port_available(port):
            frontend_port = port
            break
    if frontend_port is None:
        raise RuntimeError(
            "No available frontend port in configured range "
            f"{SANDBOX_FRONTEND_PORT_RANGE_START}-{SANDBOX_FRONTEND_PORT_RANGE_END}"
        )

    backend_port: int | None = None
    for port in range(SANDBOX_BACKEND_PORT_RANGE_START, SANDBOX_BACKEND_PORT_RANGE_END + 1):
        if port in reserved_ports or port == frontend_port:
            continue
        if _is_port_available(port):
            backend_port = port
            break
    if backend_port is None:
        raise RuntimeError(
            "No available backend port in configured range "
            f"{SANDBOX_BACKEND_PORT_RANGE_START}-{SANDBOX_BACKEND_PORT_RANGE_END}"
        )

    return {
        "frontend": frontend_port,
        "backend": backend_port,
    }


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
        self.root = SANDBOX_ROOT_DIR / self.session_id
        self.workspace = self.root / "workspace"
        self.reports = self.root / "reports"
        self.playbox = PLAYBOX_DIR / self.session_id / "staged"
        self.meta_path = self.root / "meta.json"

    @property
    def is_local_model(self) -> bool:
        marker = self.model.lower()
        return "local" in marker or "ollama" in marker or marker.startswith("llama")

    def create(self) -> dict[str, Any]:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        reserved_ports = _allocate_session_ports(SANDBOX_ROOT_DIR)
        container_name = f"agentop-sbx-{self.session_id}"
        payload: dict[str, Any] = {
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
            "reserved_ports": reserved_ports,
            "container_name": container_name,
            "container_id": None,
            "container_status": "not_started",
        }
        self.meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if SANDBOX_DOCKER_ENABLED and self.is_local_model:
            container = self.start_container()
            payload.update(container)

        return payload

    def read_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            raise FileNotFoundError(f"Sandbox session '{self.session_id}' does not exist")
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _write_meta(self, data: dict[str, Any]) -> None:
        self.meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def start_container(self) -> dict[str, Any]:
        if not SANDBOX_DOCKER_ENABLED:
            return {
                "container_id": None,
                "container_name": f"agentop-sbx-{self.session_id}",
                "container_status": "disabled",
            }

        docker_bin = shutil.which("docker")
        if not docker_bin:
            raise RuntimeError("Docker CLI not found while SANDBOX_DOCKER_ENABLED=true")

        meta = self.read_meta()
        container_name = str(meta.get("container_name") or f"agentop-sbx-{self.session_id}")

        cmd = [
            docker_bin,
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            SANDBOX_DOCKER_NETWORK,
            "--memory",
            SANDBOX_DOCKER_MEM_LIMIT,
            "--cpus",
            SANDBOX_DOCKER_CPU_LIMIT,
            "--pids-limit",
            str(SANDBOX_DOCKER_PIDS_LIMIT),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "-v",
            f"{self.workspace}:/workspace:rw",
            "-v",
            f"{self.project_root}:/project_ro:ro",
        ]
        if SANDBOX_DOCKER_READONLY_ROOTFS:
            cmd.append("--read-only")
        cmd.append(SANDBOX_DOCKER_IMAGE)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"Failed to start sandbox container: {stderr}")

        container_id = (result.stdout or "").strip()
        meta["container_id"] = container_id or None
        meta["container_name"] = container_name
        meta["container_status"] = "running" if container_id else "unknown"
        self._write_meta(meta)
        return {
            "container_id": meta.get("container_id"),
            "container_name": meta.get("container_name"),
            "container_status": meta.get("container_status"),
        }

    def stop_container(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {
                "container_id": None,
                "container_name": None,
                "container_status": "missing",
            }

        meta = self.read_meta()
        container_id = str(meta.get("container_id") or "").strip()
        container_name = str(meta.get("container_name") or "").strip()
        container_ref = container_id or container_name

        if container_ref and SANDBOX_DOCKER_ENABLED:
            docker_bin = shutil.which("docker")
            if docker_bin:
                subprocess.run([docker_bin, "stop", container_ref], capture_output=True, text=True, timeout=20, check=False)
                subprocess.run([docker_bin, "rm", container_ref], capture_output=True, text=True, timeout=20, check=False)

        meta["container_status"] = "stopped" if container_ref else "not_started"
        self._write_meta(meta)
        return {
            "container_id": meta.get("container_id"),
            "container_name": meta.get("container_name"),
            "container_status": meta.get("container_status"),
        }

    def exec_in_container(
        self,
        command: list[str],
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute a command inside the session's container (if running) or locally in the workspace.

        Returns a dict with keys:
            stdout, stderr, returncode, mode ("container" | "local"), container_id (str | None)
        """
        if not command:
            raise ValueError("command must be a non-empty list")

        meta = self.read_meta()

        container_id = str(meta.get("container_id") or "").strip()
        container_status = str(meta.get("container_status") or "").strip()
        use_container = (
            SANDBOX_DOCKER_ENABLED
            and bool(container_id)
            and container_status == "running"
        )

        if use_container:
            docker_bin = shutil.which("docker")
            if not docker_bin:
                raise RuntimeError("Docker CLI not found while SANDBOX_DOCKER_ENABLED=true")

            exec_cmd = [
                docker_bin,
                "exec",
                "--no-new-privileges",
                "-w",
                "/workspace",
                container_id,
            ] + command

            result = subprocess.run(
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return {
                "stdout": (result.stdout or "").strip(),
                "stderr": (result.stderr or "").strip(),
                "returncode": result.returncode,
                "mode": "container",
                "container_id": container_id,
            }

        # Fallback: run directly inside the workspace directory (non-containerised session)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(self.workspace),
        )
        return {
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "returncode": result.returncode,
            "mode": "local",
            "container_id": None,
        }

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

    def stage_to_playbox(self, files: list[str]) -> list[str]:
        staged: list[str] = []
        missing: list[str] = []
        for rel_path in files:
            src = self.workspace / rel_path
            dst = self.playbox / rel_path
            if not src.exists() or not src.is_file():
                missing.append(rel_path)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            staged.append(rel_path)

        if missing:
            raise FileNotFoundError(f"Missing files in sandbox workspace: {', '.join(missing)}")

        meta = self.read_meta()
        meta["staged_files"] = sorted(set(meta.get("staged_files", []) + staged))
        meta["last_staged_at"] = _utc_now()
        self._write_meta(meta)
        return staged

    def release_from_playbox(self, files: list[str]) -> list[str]:
        released: list[str] = []
        missing: list[str] = []
        for rel_path in files:
            src = self.playbox / rel_path
            dst = self.project_root / rel_path
            if not src.exists() or not src.is_file():
                missing.append(rel_path)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            released.append(rel_path)

        if missing:
            raise FileNotFoundError(f"Missing files in playbox staged area: {', '.join(missing)}")

        meta = self.read_meta()
        meta["released_files"] = sorted(set(meta.get("released_files", []) + released))
        meta["last_released_at"] = _utc_now()
        self._write_meta(meta)
        return released

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
        loaded = json.loads(summary_json_path.read_text(encoding="utf-8"))
        raw: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        summary = raw.get("summary")
        if isinstance(summary, dict):
            raw = summary
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
            self.stop_container()
            self.append_log(before_scores, after_scores, promoted, deleted_at)
            shutil.rmtree(self.root, ignore_errors=True)


def list_active_sessions(base_dir: Path = SANDBOX_ROOT_DIR) -> list[dict[str, Any]]:
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
