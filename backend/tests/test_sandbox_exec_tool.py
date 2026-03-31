"""Tests for the sandbox_exec tool (Sprint 8 — Docker Sandbox).

Verifies that the ``sandbox_exec`` tool is registered, routes through
``SandboxSession.exec_in_container``, and respects missing-arg guard-rails.
Docker is NOT required — all tests patch exec_in_container directly.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_stub(tmp_path: Path, container_id: str | None = None, status: str = "not_started") -> Any:
    from sandbox.session_manager import SandboxSession

    session_id = "sb-tool-001"
    root = tmp_path / session_id
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "session_id": session_id,
        "task": "tool-test",
        "model": "local",
        "status": "active",
        "container_name": f"agentop-sbx-{session_id}",
        "container_id": container_id,
        "container_status": status,
        "promoted_files": [],
        "reserved_ports": {},
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    session = SandboxSession.__new__(SandboxSession)
    session.session_id = session_id
    session.root = root
    session.workspace = workspace
    session.meta_path = root / "meta.json"
    session.project_root = tmp_path
    session.task = "tool-test"
    session.model = "local"
    return session


# ---------------------------------------------------------------------------
# Registry — sandbox_exec is registered
# ---------------------------------------------------------------------------


def test_sandbox_exec_in_registry() -> None:
    from backend.tools import get_tool_definition

    tool = get_tool_definition("sandbox_exec")
    assert tool is not None
    assert tool.name == "sandbox_exec"


def test_sandbox_exec_is_state_modify() -> None:
    from backend.tools import ModificationType, get_tool_definition

    tool = get_tool_definition("sandbox_exec")
    assert tool is not None
    assert tool.modification_type == ModificationType.STATE_MODIFY


# ---------------------------------------------------------------------------
# execute_tool routing — missing args
# ---------------------------------------------------------------------------


def test_sandbox_exec_missing_session_id() -> None:
    from backend.tools import execute_tool

    async def _run():
        return await execute_tool(
            "sandbox_exec",
            agent_id="agent-x",
            allowed_tools=["sandbox_exec"],
            command=["echo", "hi"],
        )

    result = asyncio.run(_run())
    assert "error" in result
    assert "session_id" in result["error"]


def test_sandbox_exec_missing_command() -> None:
    from backend.tools import execute_tool

    async def _run():
        return await execute_tool(
            "sandbox_exec",
            agent_id="agent-x",
            allowed_tools=["sandbox_exec"],
            session_id="some-session",
            command=[],
        )

    result = asyncio.run(_run())
    assert "error" in result
    assert "command" in result["error"]


# ---------------------------------------------------------------------------
# execute_tool routing — local fallback (SANDBOX_DOCKER_ENABLED=False)
# ---------------------------------------------------------------------------


def test_sandbox_exec_local_fallback(tmp_path: Path) -> None:
    from backend.tools import execute_tool

    session = _make_session_stub(tmp_path, container_id=None, status="not_started")

    fake_result = {
        "stdout": "hello",
        "stderr": "",
        "returncode": 0,
        "mode": "local",
        "container_id": None,
    }

    async def _run():
        with (
            patch("sandbox.session_manager.SandboxSession") as mock_cls,
        ):
            mock_cls.return_value = session
            session.exec_in_container = MagicMock(return_value=fake_result)
            return await execute_tool(
                "sandbox_exec",
                agent_id="agent-x",
                allowed_tools=["sandbox_exec"],
                session_id=session.session_id,
                command=["echo", "hello"],
                timeout=10,
            )

    result = asyncio.run(_run())
    assert result.get("mode") == "local"
    assert result.get("stdout") == "hello"


# ---------------------------------------------------------------------------
# execute_tool routing — container mode (SANDBOX_DOCKER_ENABLED=True)
# ---------------------------------------------------------------------------


def test_sandbox_exec_container_mode(tmp_path: Path) -> None:
    from backend.tools import execute_tool

    session = _make_session_stub(tmp_path, container_id="abc123", status="running")

    fake_result = {
        "stdout": "container-output",
        "stderr": "",
        "returncode": 0,
        "mode": "container",
        "container_id": "abc123",
    }

    async def _run():
        with (
            patch("sandbox.session_manager.SandboxSession") as mock_cls,
        ):
            mock_cls.return_value = session
            session.exec_in_container = MagicMock(return_value=fake_result)
            return await execute_tool(
                "sandbox_exec",
                agent_id="agent-x",
                allowed_tools=["sandbox_exec"],
                session_id=session.session_id,
                command=["ls", "-la"],
                timeout=15,
            )

    result = asyncio.run(_run())
    assert result.get("mode") == "container"
    assert result.get("container_id") == "abc123"
    session.exec_in_container.assert_called_once_with(command=["ls", "-la"], timeout=15)


# ---------------------------------------------------------------------------
# execute_tool routing — agent not authorised
# ---------------------------------------------------------------------------


def test_sandbox_exec_unauthorised_agent() -> None:
    from backend.tools import execute_tool

    async def _run():
        return await execute_tool(
            "sandbox_exec",
            agent_id="agent-x",
            allowed_tools=["safe_shell"],  # sandbox_exec not permitted
            session_id="sess-1",
            command=["echo", "hi"],
        )

    result = asyncio.run(_run())
    assert "error" in result
    assert "not authorized" in result["error"]


# ---------------------------------------------------------------------------
# Dockerfile exists and contains non-root user
# ---------------------------------------------------------------------------


def test_sandbox_dockerfile_exists() -> None:
    from backend.config import PROJECT_ROOT

    dockerfile = PROJECT_ROOT / "sandbox" / "Dockerfile"
    assert dockerfile.exists(), "sandbox/Dockerfile must exist"


def test_sandbox_dockerfile_has_nonroot_user() -> None:
    from backend.config import PROJECT_ROOT

    dockerfile = PROJECT_ROOT / "sandbox" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    assert "USER agent" in content, "Dockerfile must switch to non-root 'agent' user"
    assert "useradd" in content, "Dockerfile must create the agent user"


def test_sandbox_build_script_exists() -> None:
    from backend.config import PROJECT_ROOT

    build_sh = PROJECT_ROOT / "sandbox" / "build.sh"
    assert build_sh.exists(), "sandbox/build.sh must exist"
