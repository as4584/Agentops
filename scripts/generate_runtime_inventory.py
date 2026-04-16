#!/usr/bin/env python3
"""
Runtime inventory generator — Sprint 3.

Produces a machine-readable JSON artifact enumerating:
- Native tools (from TOOL_REGISTRY)
- MCP tools (from MCP_TOOL_MAP, grouped by server)
- GitNexus tools (subset of MCP tools)
- Agent-to-tool permissions (from ALL_AGENT_DEFINITIONS)
- Deployment mode (from config)
- GitNexus health snapshot

Output is written to reports/runtime_inventory.json.

Usage:
    python scripts/generate_runtime_inventory.py [--stdout]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import AGENTOP_DEPLOYMENT_MODE, GITNEXUS_REPO_NAME
from backend.mcp import MCP_TOOL_MAP
from backend.mcp.gitnexus_health import get_gitnexus_health
from backend.tools import TOOL_REGISTRY

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_OUTPUT_PATH = _REPORTS_DIR / "runtime_inventory.json"

# GitNexus tools are a named subset of MCP tools
_GITNEXUS_TOOL_NAMES = {k for k, v in MCP_TOOL_MAP.items() if v[0] == "gitnexus"}

# Native tools are those not prefixed with "mcp_" and not browser/k8s/sandbox aliases
_NATIVE_TOOL_NAMES = [
    name for name in TOOL_REGISTRY
    if not name.startswith("mcp_")
]

# All MCP tools (including GitNexus)
_MCP_TOOL_NAMES = [name for name in TOOL_REGISTRY if name.startswith("mcp_")]

# Group MCP tools by server
_mcp_by_server: dict[str, list[str]] = {}
for _tool_name, (_server, _) in MCP_TOOL_MAP.items():
    _mcp_by_server.setdefault(_server, []).append(_tool_name)


def _build_agent_permissions() -> dict[str, list[str]]:
    from backend.agents import ALL_AGENT_DEFINITIONS
    return {
        agent_id: list(defn.tool_permissions)
        for agent_id, defn in ALL_AGENT_DEFINITIONS.items()
    }


def generate_inventory() -> dict:
    gn_state = get_gitnexus_health()
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "deployment_mode": AGENTOP_DEPLOYMENT_MODE,
        "gitnexus_repo": GITNEXUS_REPO_NAME,
        "native_tools": sorted(_NATIVE_TOOL_NAMES),
        "native_tool_count": len(_NATIVE_TOOL_NAMES),
        "mcp_tools": sorted(_MCP_TOOL_NAMES),
        "mcp_tool_count": len(_MCP_TOOL_NAMES),
        "mcp_tools_by_server": {k: sorted(v) for k, v in sorted(_mcp_by_server.items())},
        "gitnexus_tools": sorted(_GITNEXUS_TOOL_NAMES),
        "gitnexus_health": {
            "enabled": gn_state.enabled,
            "usable": gn_state.usable,
            "index_exists": gn_state.index_exists,
            "symbol_count": gn_state.symbol_count,
            "embeddings_present": gn_state.embeddings_present,
            "stale": gn_state.stale,
            "reason": gn_state.reason,
        },
        "agent_tool_permissions": _build_agent_permissions(),
    }


def main() -> int:
    stdout_only = "--stdout" in sys.argv
    inventory = generate_inventory()
    payload = json.dumps(inventory, indent=2)
    if stdout_only:
        print(payload)
    else:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_PATH.write_text(payload, encoding="utf-8")
        print(f"Runtime inventory written to {_OUTPUT_PATH}")
        print(f"  native_tools : {inventory['native_tool_count']}")
        print(f"  mcp_tools    : {inventory['mcp_tool_count']}")
        print(f"  gitnexus     : {inventory['gitnexus_health']['usable']}")
        print(f"  agents       : {len(inventory['agent_tool_permissions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
