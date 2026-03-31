from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_docker_container_lifecycle_for_local_session(monkeypatch, tmp_path: Path):
    import sandbox.session_manager as session_manager

    sandbox_root = tmp_path / "sandbox"
    project_root = tmp_path / "project"
    playbox_root = tmp_path / "playbox"
    (project_root / "docs").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(session_manager, "SANDBOX_ROOT_DIR", sandbox_root)
    monkeypatch.setattr(session_manager, "PLAYBOX_DIR", playbox_root)
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_START", 3700, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_END", 3710, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_START", 8700, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_END", 8710, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_DOCKER_ENABLED", True, raising=False)
    monkeypatch.setattr(session_manager.shutil, "which", lambda name: "/usr/bin/docker")

    executed: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, timeout=0, check=False):
        executed.append(list(cmd))
        if cmd[1] == "run":
            return subprocess.CompletedProcess(cmd, 0, stdout="container123\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(session_manager.subprocess, "run", fake_run)

    session = session_manager.SandboxSession(
        project_root=project_root,
        task="docker lifecycle",
        model="local",
        session_id="session-docker",
    )

    payload = session.create()
    assert payload["container_id"] == "container123"
    assert payload["container_status"] == "running"

    session.destroy(promoted_files=[])
    assert not session.root.exists()

    commands = [" ".join(cmd) for cmd in executed]
    assert any("docker run" in line for line in commands)
    assert any("docker stop" in line for line in commands)
    assert any("docker rm" in line for line in commands)
