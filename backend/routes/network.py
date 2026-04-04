"""
Network Node Management — Register and manage Agentop nodes on your LAN.
=========================================================================
Allows you to:
1. Register machines on your network as agent execution nodes
2. Health-check nodes (SSH reachability + Ollama/Agentop service checks)
3. Dispatch agent work to specific nodes via the orchestrator's remote_dispatch
4. List and remove nodes from the fleet

All node metadata is persisted to data/agents/network_nodes.json.
SSH key auth is expected (no passwords stored).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import MEMORY_DIR
from backend.utils import logger

router = APIRouter(prefix="/network", tags=["network"])

_NODES_PATH = MEMORY_DIR / "network_nodes.json"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class NetworkNode(BaseModel):
    """A machine on the LAN that can run Agentop agents."""

    host: str = Field(..., min_length=1, description="IP or hostname")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port")
    username: str = Field(default="root", min_length=1)
    label: str = Field(default="", description="Human-friendly name")
    roles: list[str] = Field(
        default_factory=list,
        description="Agent IDs this node is designated for (empty = any)",
    )
    ollama_port: int = Field(default=11434, description="Ollama port on the node")
    agentop_port: int = Field(default=8000, description="Agentop backend port on the node")
    enabled: bool = True
    last_health_check: float | None = None
    healthy: bool = False


class NodeRegisterRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="root")
    label: str = ""
    roles: list[str] = Field(default_factory=list)
    ollama_port: int = 11434
    agentop_port: int = 8000


class NodeDispatchRequest(BaseModel):
    host: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1, max_length=4096)
    agent_id: str = Field(default="devops_agent")
    timeout: int = Field(default=30, ge=5, le=300)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _load_nodes() -> dict[str, NetworkNode]:
    if _NODES_PATH.exists():
        try:
            data = json.loads(_NODES_PATH.read_text())
            return {k: NetworkNode(**v) for k, v in data.items()}
        except Exception:
            return {}
    return {}


def _save_nodes(nodes: dict[str, NetworkNode]) -> None:
    _NODES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NODES_PATH.write_text(json.dumps({k: v.model_dump() for k, v in nodes.items()}, indent=2))


# ---------------------------------------------------------------------------
# Health checking
# ---------------------------------------------------------------------------


async def _check_node_health(node: NetworkNode) -> dict[str, Any]:
    """Check if a node is reachable via SSH and if services are running."""
    results: dict[str, Any] = {
        "host": node.host,
        "ssh_reachable": False,
        "ollama_running": False,
        "agentop_running": False,
        "latency_ms": 0.0,
    }

    start = time.monotonic()

    # SSH reachability (quick connection test)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-p",
            str(node.port),
            f"{node.username}@{node.host}",
            "echo",
            "ok",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        results["ssh_reachable"] = b"ok" in stdout
    except (TimeoutError, FileNotFoundError):
        results["ssh_reachable"] = False

    if not results["ssh_reachable"]:
        results["latency_ms"] = (time.monotonic() - start) * 1000
        return results

    # Check Ollama
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-p",
            str(node.port),
            f"{node.username}@{node.host}",
            f"curl -sf http://localhost:{node.ollama_port}/api/tags",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        results["ollama_running"] = proc.returncode == 0
    except (TimeoutError, FileNotFoundError):
        pass

    # Check Agentop backend
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-p",
            str(node.port),
            f"{node.username}@{node.host}",
            f"curl -sf http://localhost:{node.agentop_port}/health",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        results["agentop_running"] = proc.returncode == 0
    except (TimeoutError, FileNotFoundError):
        pass

    results["latency_ms"] = (time.monotonic() - start) * 1000
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/nodes")
async def list_nodes() -> list[dict[str, Any]]:
    """List all registered network nodes."""
    nodes = _load_nodes()
    return [v.model_dump() for v in nodes.values()]


@router.post("/nodes")
async def register_node(req: NodeRegisterRequest) -> dict[str, Any]:
    """Register a new node on the network."""
    nodes = _load_nodes()
    key = f"{req.host}:{req.port}"
    node = NetworkNode(
        host=req.host,
        port=req.port,
        username=req.username,
        label=req.label or req.host,
        roles=req.roles,
        ollama_port=req.ollama_port,
        agentop_port=req.agentop_port,
    )
    nodes[key] = node
    _save_nodes(nodes)
    logger.info(f"Network node registered: {key} label={node.label}")
    return {"status": "registered", "node": node.model_dump()}


@router.delete("/nodes/{host}")
async def remove_node(host: str, port: int = 22) -> dict[str, str]:
    """Remove a node from the fleet."""
    nodes = _load_nodes()
    key = f"{host}:{port}"
    if key not in nodes:
        raise HTTPException(status_code=404, detail=f"Node {key} not found")
    del nodes[key]
    _save_nodes(nodes)
    return {"status": "removed", "node": key}


@router.post("/nodes/{host}/health")
async def check_node_health(host: str, port: int = 22) -> dict[str, Any]:
    """Health-check a specific node."""
    nodes = _load_nodes()
    key = f"{host}:{port}"
    node = nodes.get(key)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {key} not registered")

    result = await _check_node_health(node)
    node.last_health_check = time.time()
    node.healthy = result["ssh_reachable"]
    nodes[key] = node
    _save_nodes(nodes)
    return result


@router.post("/health-all")
async def check_all_nodes_health() -> list[dict[str, Any]]:
    """Health-check all registered nodes concurrently."""
    nodes = _load_nodes()
    if not nodes:
        return []

    tasks = [_check_node_health(node) for node in nodes.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: list[dict[str, Any]] = []
    for (key, node), result in zip(nodes.items(), results):
        if isinstance(result, BaseException):
            output.append({"host": node.host, "error": str(result)})
        else:
            node.last_health_check = time.time()
            node.healthy = result.get("ssh_reachable", False)
            nodes[key] = node
            output.append(result)

    _save_nodes(nodes)
    return output


@router.post("/dispatch")
async def dispatch_to_node(req: NodeDispatchRequest) -> dict[str, Any]:
    """Execute a command on a remote node via the orchestrator's remote_dispatch."""
    from backend.routes.agent_control import _require_orchestrator

    orchestrator = _require_orchestrator()
    result = await orchestrator.remote_dispatch(  # type: ignore[attr-defined]
        agent_id=req.agent_id,
        host=req.host,
        command=req.command,
        timeout=req.timeout,
    )
    return result


@router.get("/topology")
async def network_topology() -> dict[str, Any]:
    """Overview of the entire agent network — nodes, roles, health."""
    nodes = _load_nodes()
    healthy = sum(1 for n in nodes.values() if n.healthy)
    roles_map: dict[str, list[str]] = {}
    for node in nodes.values():
        for role in node.roles or ["any"]:
            roles_map.setdefault(role, []).append(node.host)

    return {
        "total_nodes": len(nodes),
        "healthy_nodes": healthy,
        "unhealthy_nodes": len(nodes) - healthy,
        "roles": roles_map,
        "nodes": [
            {
                "host": n.host,
                "label": n.label,
                "healthy": n.healthy,
                "roles": n.roles,
                "enabled": n.enabled,
            }
            for n in nodes.values()
        ],
    }
