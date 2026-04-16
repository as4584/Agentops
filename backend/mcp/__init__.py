"""
MCP Bridge — Docker MCP Gateway integration layer.
===================================================
Connects Agentop agents to the Docker MCP Catalog via the `docker mcp` CLI.

The Docker MCP Gateway runs MCP servers as isolated Docker containers and provides
a unified HTTP/CLI interface for tool discovery and invocation.

Quick start:
    # Install MCP gateway (if not already installed via Docker Desktop)
    chmod +x ~/.docker/cli-plugins/docker-mcp

    # Enable desired MCP servers
    DOCKER_MCP_IN_CONTAINER=1 docker mcp server enable github filesystem docker time fetch sqlite slack

    # (Optional) run gateway in streaming mode for HTTP access
    DOCKER_MCP_IN_CONTAINER=1 docker mcp gateway run --transport streaming --port 8811

Architecture:
    The MCPBridge is the ONLY path through which agents call MCP tools.
    It enforces per-agent tool permission checking via execute_tool in tools/__init__.py.
    No agent contacts the Docker MCP CLI directly.

    MCPBridge is a singleton initialised in server.py lifespan. If the docker mcp CLI
    is unavailable the bridge degrades gracefully — all mcp_* tool calls return a
    structured error without crashing the backend.

Governance:
    - INV-3: MCP tools are pre-declared in TOOL_REGISTRY; no dynamic registration.
    - INV-7: Every MCP tool call is logged via CentralLogger.
    - Agent mcp_tool_permissions are validated before gateway dispatch.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from typing import Any

from backend.config import (
    MCP_CONFIG_DIR,
    MCP_GATEWAY_ENABLED,
    MCP_TOOL_TIMEOUT,
    PROJECT_ROOT,
)
from backend.utils import logger

# ---------------------------------------------------------------------------
# MCP tool name → (docker-mcp server name, mcp tool name)
# ---------------------------------------------------------------------------
# Maps our internal `mcp_{server}_{tool}` names to the Docker MCP CLI names.
# docker mcp tools call <mcp_tool_id> '<json_args>'
# mcp_tool_id is typically "{server_name}_{tool_name}" as returned by
# `docker mcp tools ls --format=json`.
# ---------------------------------------------------------------------------
MCP_TOOL_MAP: dict[str, tuple[str, str]] = {
    # GitHub MCP Server
    "mcp_github_search_repositories": ("github", "search_repositories"),
    "mcp_github_get_file_contents": ("github", "get_file_contents"),
    "mcp_github_list_issues": ("github", "list_issues"),
    "mcp_github_create_issue": ("github", "create_issue"),
    "mcp_github_search_code": ("github", "search_code"),
    "mcp_github_list_pull_requests": ("github", "list_pull_requests"),
    "mcp_github_get_pull_request": ("github", "get_pull_request"),
    # Filesystem MCP Server
    "mcp_filesystem_read_file": ("filesystem", "read_file"),
    "mcp_filesystem_write_file": ("filesystem", "write_file"),
    "mcp_filesystem_list_directory": ("filesystem", "list_directory"),
    "mcp_filesystem_search_files": ("filesystem", "search_files"),
    "mcp_filesystem_get_file_info": ("filesystem", "get_file_info"),
    # Docker MCP Server
    "mcp_docker_list_containers": ("docker", "list_containers"),
    "mcp_docker_get_container_logs": ("docker", "get_container_logs"),
    "mcp_docker_inspect_container": ("docker", "inspect_container"),
    "mcp_docker_restart_container": ("docker", "restart_container"),
    "mcp_docker_list_images": ("docker", "list_images"),
    # Time MCP Server
    "mcp_time_get_current_time": ("time", "get_current_time"),
    "mcp_time_convert_time": ("time", "convert_time"),
    # Fetch MCP Server
    "mcp_fetch_get": ("fetch", "fetch"),
    # SQLite MCP Server
    "mcp_sqlite_read_query": ("sqlite", "read_query"),
    "mcp_sqlite_list_tables": ("sqlite", "list_tables"),
    "mcp_sqlite_describe_table": ("sqlite", "describe_table"),
    # Slack MCP Server
    "mcp_slack_post_message": ("slack", "post_message"),
    "mcp_slack_list_channels": ("slack", "list_channels"),
    "mcp_slack_get_channel_history": ("slack", "get_channel_history"),
    # GitNexus MCP Server (code intelligence — Sprint 5)
    "mcp_gitnexus_query": ("gitnexus", "query"),
    "mcp_gitnexus_context": ("gitnexus", "context"),
    "mcp_gitnexus_impact": ("gitnexus", "impact"),
    "mcp_gitnexus_detect_changes": ("gitnexus", "detect_changes"),
    "mcp_gitnexus_list_repos": ("gitnexus", "list_repos"),
}


def is_mcp_tool(tool_name: str) -> bool:
    """Return True if the tool name is an MCP-routed tool."""
    return tool_name.startswith("mcp_")


class MCPBridge:
    """
    Singleton async bridge to the Docker MCP Gateway.

    Provides tool discovery and invocation via the `docker mcp` CLI.
    Degrades gracefully when Docker MCP is unavailable.
    """

    def __init__(self) -> None:
        self._enabled = MCP_GATEWAY_ENABLED
        self._cli_available: bool = False
        self._available_tools: dict[str, dict[str, Any]] = {}
        self._initialised: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """
        Check CLI availability and discover tools.
        Called once from server lifespan startup.
        """
        if not self._enabled:
            logger.info("MCPBridge: disabled via MCP_GATEWAY_ENABLED=false")
            self._initialised = True
            return

        # Check that docker mcp CLI exists
        self._cli_available = shutil.which("docker") is not None
        if not self._cli_available:
            logger.warning("MCPBridge: 'docker' binary not found — MCP tools unavailable")
            self._initialised = True
            return

        # Attempt tool discovery (non-fatal)
        try:
            await self._discover_tools()
        except Exception as exc:
            logger.warning(f"MCPBridge: tool discovery failed ({exc}) — MCP tools may be unavailable")

        self._initialised = True
        logger.info(
            f"MCPBridge initialised: {len(self._available_tools)} MCP tools discovered, "
            f"CLI={'available' if self._cli_available else 'missing'}"
        )

    async def shutdown(self) -> None:
        """Cleanup hook — currently no persistent subprocess to terminate."""
        logger.info("MCPBridge: shutdown complete")

    # ------------------------------------------------------------------
    # Tool Discovery
    # ------------------------------------------------------------------

    async def _discover_tools(self) -> None:
        """
        Discover available MCP tools via `docker mcp tools ls --format=json`.
        Populates self._available_tools with tool metadata.
        """
        env = _mcp_env()
        result = await _run_docker_mcp(
            ["docker", "mcp", "tools", "ls", "--format=json"],
            env=env,
            timeout=20,
        )
        if not result["success"]:
            logger.warning(f"MCPBridge: tools ls failed: {result.get('error', 'unknown')}")
            return

        raw = result["output"].strip()
        if not raw:
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"MCPBridge: could not parse tools ls output: {raw[:200]}")
            return

        # Normalise: data may be a list [{name, server, description}] or a dict
        tools_list: list[dict[str, Any]] = []
        if isinstance(data, list):
            tools_list = data
        elif isinstance(data, dict):
            # {server: {tools: [{name, description}]}}
            for server_name, server_data in data.items():
                for tool in server_data.get("tools") or []:
                    tools_list.append(
                        {
                            "name": tool.get("name", ""),
                            "server": server_name,
                            "description": tool.get("description", ""),
                        }
                    )

        for tool in tools_list:
            key = f"{tool.get('server', 'unknown')}_{tool.get('name', 'unknown')}"
            self._available_tools[key] = tool

        logger.info(f"MCPBridge: discovered {len(self._available_tools)} tools from docker mcp")

    # ------------------------------------------------------------------
    # Tool Invocation
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        agentop_tool_name: str,
        agent_id: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call an MCP tool through the Docker MCP Gateway CLI.

        Args:
            agentop_tool_name: Full Agentop tool name (e.g. 'mcp_github_create_issue')
            agent_id: Calling agent ID (for logging)
            args: Tool input arguments (dict)

        Returns:
            {success, result, error, tool, server, timestamp}
        """
        if not self._initialised:
            return _error_result(agentop_tool_name, "MCPBridge not yet initialised")

        if not self._enabled:
            return _error_result(agentop_tool_name, "MCP Gateway disabled (MCP_GATEWAY_ENABLED=false)")

        if not self._cli_available:
            return _error_result(
                agentop_tool_name,
                "docker CLI not available — install Docker to use MCP tools",
            )

        # Resolve to (server, mcp_tool_name)
        mapping = MCP_TOOL_MAP.get(agentop_tool_name)
        if not mapping:
            return _error_result(agentop_tool_name, f"No MCP mapping found for '{agentop_tool_name}'")

        server_name, mcp_tool_name = mapping

        # Sprint 2 S2.5 — fail-closed guard for GitNexus tools.
        # GitNexus tool calls must be blocked when the subsystem is not usable,
        # so agents cannot hallucinate results from a stale or missing index.
        if server_name == "gitnexus":
            from backend.mcp.gitnexus_health import get_gitnexus_health  # local import avoids circular

            gn_state = get_gitnexus_health()
            if not gn_state.usable:
                reason = gn_state.reason or "GitNexus is not usable (disabled, stale, or index missing)."
                return _error_result(
                    agentop_tool_name,
                    f"GitNexus unavailable — {reason}",
                )

        server_name, mcp_tool_name = mapping

        # Build the docker mcp tools call command.
        # The gateway accepts tool IDs as "{server}_{tool_name}" or optionally with a colon.
        # We try the underscore format first; the bridge handles alternative formats automatically.
        gateway_tool_id = f"{server_name}_{mcp_tool_name}"
        args_json = json.dumps(args) if args else "{}"

        env = _mcp_env()
        result = await _run_docker_mcp(
            ["docker", "mcp", "tools", "call", gateway_tool_id, args_json],
            env=env,
            timeout=MCP_TOOL_TIMEOUT,
        )

        timestamp = datetime.utcnow().isoformat()

        if result["success"]:
            logger.info(f"MCPBridge: {agent_id} called {gateway_tool_id} → success")
            return {
                "success": True,
                "result": _parse_tool_output(result["output"]),
                "tool": agentop_tool_name,
                "mcp_tool": gateway_tool_id,
                "server": server_name,
                "timestamp": timestamp,
            }
        else:
            logger.warning(f"MCPBridge: {agent_id} called {gateway_tool_id} → error: {result.get('error', '')}")
            return {
                "success": False,
                "error": result.get("error", "Unknown MCP error"),
                "tool": agentop_tool_name,
                "mcp_tool": gateway_tool_id,
                "server": server_name,
                "timestamp": timestamp,
            }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if the bridge can make real MCP calls."""
        return self._enabled and self._cli_available

    def get_status(self) -> dict[str, Any]:
        """Return bridge status for health/status endpoints."""
        return {
            "enabled": self._enabled,
            "cli_available": self._cli_available,
            "initialised": self._initialised,
            "discovered_tools": len(self._available_tools),
            "declared_tool_count": len(MCP_TOOL_MAP),
        }

    def list_available_tool_names(self) -> list[str]:
        """Return declared Agentop MCP tool names."""
        return list(MCP_TOOL_MAP.keys())


# ---------------------------------------------------------------------------
# Module-level singleton — imported by tools/__init__.py and server.py
# ---------------------------------------------------------------------------
mcp_bridge = MCPBridge()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mcp_env() -> dict[str, str]:
    """
    Build the environment dict for docker mcp subprocess calls.
    Sets DOCKER_MCP_IN_CONTAINER=1 to bypass Docker Desktop checks
    when running on Docker CE / Linux without Docker Desktop.
    """
    import os

    env = os.environ.copy()
    env["DOCKER_MCP_IN_CONTAINER"] = "1"
    # Point docker mcp at our project config directory
    env["DOCKER_MCP_CONFIG_DIR"] = str(MCP_CONFIG_DIR)
    return env


async def _run_docker_mcp(
    cmd: list[str],
    env: dict[str, str],
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Run a docker mcp CLI command asynchronously.

    Returns:
        {success, output, error}
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(PROJECT_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            return {"success": True, "output": out}
        else:
            return {"success": False, "output": out, "error": err or f"exit code {process.returncode}"}

    except TimeoutError:
        return {"success": False, "output": "", "error": f"Command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "docker binary not found"}
    except Exception as exc:
        return {"success": False, "output": "", "error": str(exc)}


def _parse_tool_output(raw: str) -> Any:
    """
    Try to parse tool output as JSON; fall back to raw string.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _error_result(tool_name: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "tool": tool_name,
        "timestamp": datetime.utcnow().isoformat(),
    }
