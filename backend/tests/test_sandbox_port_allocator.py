from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sandbox.session_manager import SandboxSession


def test_create_session_assigns_reserved_ports_in_range(monkeypatch, tmp_path: Path):
    import sandbox.session_manager as session_manager

    monkeypatch.setattr(session_manager, "SANDBOX_ROOT_DIR", tmp_path / "sandbox")
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_START", 3500, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_END", 3510, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_START", 8500, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_END", 8510, raising=False)

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    session = SandboxSession(
        project_root=project_root,
        task="allocate ports",
        model="local",
        session_id="session-a",
    )

    payload = session.create()
    reserved_ports = payload["reserved_ports"]

    assert isinstance(reserved_ports["frontend"], int)
    assert isinstance(reserved_ports["backend"], int)
    assert 3500 <= reserved_ports["frontend"] <= 3510
    assert 8500 <= reserved_ports["backend"] <= 8510


def test_sessions_get_distinct_reserved_ports(monkeypatch, tmp_path: Path):
    import sandbox.session_manager as session_manager

    monkeypatch.setattr(session_manager, "SANDBOX_ROOT_DIR", tmp_path / "sandbox")
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_START", 3500, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_FRONTEND_PORT_RANGE_END", 3510, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_START", 8500, raising=False)
    monkeypatch.setattr(session_manager, "SANDBOX_BACKEND_PORT_RANGE_END", 8510, raising=False)

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    first = SandboxSession(
        project_root=project_root,
        task="allocate ports one",
        model="local",
        session_id="session-one",
    ).create()
    second = SandboxSession(
        project_root=project_root,
        task="allocate ports two",
        model="local",
        session_id="session-two",
    ).create()

    assert first["reserved_ports"]["frontend"] != second["reserved_ports"]["frontend"]
    assert first["reserved_ports"]["backend"] != second["reserved_ports"]["backend"]
