"""Tests for Feature 8.2 — Exec Routing.

Verifies that SandboxSession.exec_in_container() and the POST /sandbox/{id}/exec
route correctly choose between container-mode and local-mode execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bootstrap_session(tmp_path: Path, container_id: str | None = None, status: str = "not_started") -> Any:
    """Create a minimal session directory + meta.json and return a SandboxSession."""
    from sandbox.session_manager import SandboxSession

    session_id = "test-exec-001"
    root = tmp_path / session_id
    workspace = root / "workspace"
    playbox = root / "playbox"
    workspace.mkdir(parents=True)
    playbox.mkdir(parents=True)

    meta: dict[str, Any] = {
        "session_id": session_id,
        "task": "test-exec",
        "model": "local",
        "status": "active",
        "container_name": f"agentop-sbx-{session_id}",
        "container_id": container_id,
        "container_status": status,
        "promoted_files": [],
        "reserved_ports": [],
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    session = SandboxSession.__new__(SandboxSession)
    session.session_id = session_id
    session.root = root
    session.workspace = workspace
    session.playbox = playbox
    session.meta_path = root / "meta.json"
    session.project_root = tmp_path
    session.task = "test-exec"
    session.model = "local"
    return session


# ---------------------------------------------------------------------------
# Unit: exec_in_container — local fallback (no Docker)
# ---------------------------------------------------------------------------


def test_exec_falls_back_to_local_when_docker_disabled(tmp_path: Path) -> None:
    """When SANDBOX_DOCKER_ENABLED=False exec runs locally in workspace."""
    session = _bootstrap_session(tmp_path, container_id=None, status="not_started")

    with patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", False):
        result = session.exec_in_container(["echo", "hello"])

    assert result["mode"] == "local"
    assert result["container_id"] is None
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


def test_exec_local_captures_stderr(tmp_path: Path) -> None:
    session = _bootstrap_session(tmp_path)

    with patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", False):
        # python -c prints to stderr via sys.stderr.write
        result = session.exec_in_container(["python3", "-c", "import sys; sys.stderr.write('errout')"])

    assert result["mode"] == "local"
    assert "errout" in result["stderr"]


def test_exec_local_nonzero_returncode(tmp_path: Path) -> None:
    session = _bootstrap_session(tmp_path)

    with patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", False):
        result = session.exec_in_container(["python3", "-c", "raise SystemExit(42)"])

    assert result["returncode"] == 42
    assert result["mode"] == "local"


# ---------------------------------------------------------------------------
# Unit: exec_in_container — container path
# ---------------------------------------------------------------------------


def test_exec_routes_through_docker_exec_when_container_running(tmp_path: Path) -> None:
    """When container is running, docker exec is called with --no-new-privileges."""
    session = _bootstrap_session(tmp_path, container_id="abc123", status="running")

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "container output\n"
    fake_result.stderr = ""

    with (
        patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", True),
        patch("sandbox.session_manager.shutil.which", return_value="/usr/bin/docker"),
        patch("sandbox.session_manager.subprocess.run", return_value=fake_result) as mock_run,
    ):
        result = session.exec_in_container(["ls", "/workspace"])

    assert result["mode"] == "container"
    assert result["container_id"] == "abc123"
    assert result["returncode"] == 0
    assert "container output" in result["stdout"]

    call_args: list[str] = mock_run.call_args[0][0]
    assert "docker" in call_args[0]
    assert "exec" in call_args
    assert "--no-new-privileges" in call_args
    assert "abc123" in call_args
    assert "ls" in call_args
    assert "/workspace" in call_args


def test_exec_passes_cwd_flag_to_docker_exec(tmp_path: Path) -> None:
    """`-w /workspace` is passed so commands run in the session workspace."""
    session = _bootstrap_session(tmp_path, container_id="cid-999", status="running")

    fake_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", True),
        patch("sandbox.session_manager.shutil.which", return_value="/usr/bin/docker"),
        patch("sandbox.session_manager.subprocess.run", return_value=fake_result) as mock_run,
    ):
        session.exec_in_container(["pwd"])

    args: list[str] = mock_run.call_args[0][0]
    # Expect: ... exec --no-new-privileges -w /workspace cid-999 pwd
    assert "-w" in args
    w_idx = args.index("-w")
    assert args[w_idx + 1] == "/workspace"


def test_exec_falls_back_to_local_when_container_not_running(tmp_path: Path) -> None:
    """Container_id present but status='stopped' → local fallback."""
    session = _bootstrap_session(tmp_path, container_id="xyz", status="stopped")

    with patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", True):
        result = session.exec_in_container(["echo", "local"])

    assert result["mode"] == "local"


def test_exec_raises_on_docker_not_found(tmp_path: Path) -> None:
    """RuntimeError when docker binary is missing and container is marked running."""
    session = _bootstrap_session(tmp_path, container_id="live-id", status="running")

    with (
        patch("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", True),
        patch("sandbox.session_manager.shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="Docker CLI not found"),
    ):
        session.exec_in_container(["echo", "x"])


def test_exec_raises_on_empty_command(tmp_path: Path) -> None:
    session = _bootstrap_session(tmp_path)

    with pytest.raises(ValueError, match="non-empty"):
        session.exec_in_container([])


# ---------------------------------------------------------------------------
# Integration: POST /sandbox/{session_id}/exec route
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox_client(tmp_path: Path) -> TestClient:
    from fastapi import FastAPI

    from backend.routes.sandbox import router as sandbox_router

    app = FastAPI()
    app.include_router(sandbox_router)
    return TestClient(app, raise_server_exceptions=True)


def test_exec_route_returns_local_result(
    tmp_path: Path, sandbox_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /sandbox/{id}/exec returns stdout/mode/returncode from local exec."""
    from backend.routes import sandbox as sandbox_route_module

    session_id = "route-exec-001"
    root = tmp_path / session_id
    workspace = root / "workspace"
    workspace.mkdir(parents=True)

    meta: dict[str, Any] = {
        "session_id": session_id,
        "task": "route-exec",
        "model": "local",
        "status": "active",
        "container_id": None,
        "container_status": "not_started",
        "container_name": f"agentop-sbx-{session_id}",
        "promoted_files": [],
        "reserved_ports": [],
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # Patch PROJECT_ROOT and SANDBOX_ROOT_DIR so _session() finds the right dirs
    import sandbox.session_manager as sm

    monkeypatch.setattr(sm, "PLAYBOX_DIR", tmp_path / "playbox")
    monkeypatch.setattr(sm, "SANDBOX_ROOT_DIR", tmp_path)
    monkeypatch.setattr(sandbox_route_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sandbox.session_manager.SANDBOX_DOCKER_ENABLED", False)

    resp = sandbox_client.post(f"/sandbox/{session_id}/exec", json={"command": ["echo", "route_ok"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "local"
    assert "route_ok" in data["stdout"]
    assert data["returncode"] == 0
    assert data["session_id"] == session_id


def test_exec_route_404_for_missing_session(sandbox_client: TestClient) -> None:
    resp = sandbox_client.post("/sandbox/no-such-session/exec", json={"command": ["ls"]})
    assert resp.status_code == 404


def test_exec_route_422_for_empty_command(sandbox_client: TestClient) -> None:
    resp = sandbox_client.post("/sandbox/any-session/exec", json={"command": []})
    assert resp.status_code == 422
