"""
Tool Layer — Guarded tool implementations with safety enforcement.
=================================================================
All tools MUST:
1. Log every execution (INV-7)
2. Declare modification type (READ_ONLY / STATE_MODIFY / ARCHITECTURAL_MODIFY)
3. If ARCHITECTURAL_MODIFY: enforce documentation update (INV-5)
4. Pass through DriftGuard middleware before execution

Tool Registry:
- safe_shell:    STATE_MODIFY          — Execute whitelisted shell commands
- file_reader:   READ_ONLY             — Read file contents safely
- doc_updater:   ARCHITECTURAL_MODIFY  — Update governance documentation
- system_info:   READ_ONLY             — Retrieve system information
- webhook_send:  STATE_MODIFY          — HTTP POST webhook
- git_ops:       READ_ONLY             — Read-only git operations
- health_check:  READ_ONLY             — HTTP endpoint health probe
- log_tail:      READ_ONLY             — Tail log file
- alert_dispatch: STATE_MODIFY         — Publish alert to shared events
- secret_scanner: READ_ONLY            — Detect credential patterns
- db_query:      READ_ONLY             — Read-only SQLite query
- process_restart: STATE_MODIFY        — Restart whitelisted process

MCP Gateway Tools (mcp_*):
- Routed through backend.mcp.MCPBridge → Docker MCP Gateway → MCP containers
- Pre-declared statically (INV-3: no dynamic registration)
- Per-agent permissions enforced via tool_permissions in AgentDefinition

Governance Notes:
- Tools CANNOT register new tools dynamically (INV-3)
- safe_shell has a whitelist/blacklist for commands
- doc_updater requires registry check before modifying /docs
- mcp_* tools require MCPBridge to be initialised
"""

from __future__ import annotations

import asyncio
import json
import os
import os as _os
import platform
import re
import shutil
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import (
    AGENT_REGISTRY_PATH,
    CHANGE_LOG_PATH,
    PROJECT_ROOT,
    SAFE_SHELL_BLACKLIST,
    SAFE_SHELL_WHITELIST,
    SHELL_DANGEROUS_CHARS,
    SOURCE_OF_TRUTH_PATH,
    SSRF_BLOCKED_PREFIXES,
)
from backend.middleware import drift_guard
from backend.models import (
    ChangeImpactLevel,
    ChangeLogEntry,
    ModificationType,
    ToolDefinition,
)
from backend.ocr import OCR_EXTENSIONS
from backend.ocr import extract_text as ocr_extract_text
from backend.ocr import is_supported as ocr_supported
from backend.utils import logger


# MCP Bridge — imported lazily to avoid circular imports at module load time
# Use get_mcp_bridge() to access the singleton safely.
def get_mcp_bridge():
    from backend.mcp import mcp_bridge  # noqa: PLC0415

    return mcp_bridge


# ---------------------------------------------------------------------------
# Tool Registry (static — INV-3: no dynamic registration)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "safe_shell": ToolDefinition(
        name="safe_shell",
        description="Execute whitelisted shell commands safely",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "file_reader": ToolDefinition(
        name="file_reader",
        description="Read file contents safely",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "doc_updater": ToolDefinition(
        name="doc_updater",
        description="Update governance documentation files",
        modification_type=ModificationType.ARCHITECTURAL_MODIFY,
        requires_doc_update=True,
    ),
    "system_info": ToolDefinition(
        name="system_info",
        description="Retrieve system information",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ---- New tools for expanded agent cluster ----
    "webhook_send": ToolDefinition(
        name="webhook_send",
        description="Send an HTTP POST notification to a registered webhook URL",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "git_ops": ToolDefinition(
        name="git_ops",
        description="Read-only git operations: log, status, diff",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "health_check": ToolDefinition(
        name="health_check",
        description="Check HTTP endpoint health and measure latency",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "log_tail": ToolDefinition(
        name="log_tail",
        description="Tail the last N lines of a log file",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "alert_dispatch": ToolDefinition(
        name="alert_dispatch",
        description="Dispatch a named alert event to the shared event log",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "secret_scanner": ToolDefinition(
        name="secret_scanner",
        description="Scan a file or directory for common secret / credential patterns",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "db_query": ToolDefinition(
        name="db_query",
        description="Execute a read-only SQLite SELECT query",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "process_restart": ToolDefinition(
        name="process_restart",
        description="Restart a whitelisted background process by name",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "folder_analyzer": ToolDefinition(
        name="folder_analyzer",
        description="Recursively index a folder — returns file tree, metadata, and content snippets for agent analysis",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "document_ocr": ToolDefinition(
        name="document_ocr",
        description=(
            "Extract clean Markdown from a PDF, image, or Office document via GLM-OCR "
            "(0.9B local model). Saves LLM tokens by pre-converting unstructured documents "
            "to structured text before agent processing."
        ),
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "k8s_control": ToolDefinition(
        name="k8s_control",
        description=(
            "Control Kubernetes cluster: create jobs, get pods/services, check status. "
            "Enables agents to deploy themselves and manage workloads autonomously."
        ),
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_control": ToolDefinition(
        name="browser_control",
        description=(
            "Drive a headed Chromium browser running in the browser-worker pod. "
            "Actions: navigate, click, fill, select, screenshot, evaluate, back, url. "
            "Watched live via noVNC at http://localhost:6080/vnc.html after port-forward."
        ),
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    # =========================================================
    # MCP Gateway Tools — routed through Docker MCP Gateway
    # Statically declared (INV-3). Executed via MCPBridge.
    # =========================================================
    # ── GitHub MCP Server ────────────────────────────────────
    "mcp_github_search_repositories": ToolDefinition(
        name="mcp_github_search_repositories",
        description="[MCP/GitHub] Search GitHub repositories by query",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_github_get_file_contents": ToolDefinition(
        name="mcp_github_get_file_contents",
        description="[MCP/GitHub] Get file contents from a GitHub repository",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_github_list_issues": ToolDefinition(
        name="mcp_github_list_issues",
        description="[MCP/GitHub] List issues in a GitHub repository",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_github_create_issue": ToolDefinition(
        name="mcp_github_create_issue",
        description="[MCP/GitHub] Create a new issue in a GitHub repository",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "mcp_github_search_code": ToolDefinition(
        name="mcp_github_search_code",
        description="[MCP/GitHub] Search code across GitHub repositories",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_github_list_pull_requests": ToolDefinition(
        name="mcp_github_list_pull_requests",
        description="[MCP/GitHub] List pull requests in a GitHub repository",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_github_get_pull_request": ToolDefinition(
        name="mcp_github_get_pull_request",
        description="[MCP/GitHub] Get details of a specific GitHub pull request",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Filesystem MCP Server ────────────────────────────────
    "mcp_filesystem_read_file": ToolDefinition(
        name="mcp_filesystem_read_file",
        description="[MCP/Filesystem] Read a file via the MCP filesystem server",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_filesystem_write_file": ToolDefinition(
        name="mcp_filesystem_write_file",
        description="[MCP/Filesystem] Write a file via the MCP filesystem server",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "mcp_filesystem_list_directory": ToolDefinition(
        name="mcp_filesystem_list_directory",
        description="[MCP/Filesystem] List directory contents via MCP filesystem server",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_filesystem_search_files": ToolDefinition(
        name="mcp_filesystem_search_files",
        description="[MCP/Filesystem] Search for files matching a pattern via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_filesystem_get_file_info": ToolDefinition(
        name="mcp_filesystem_get_file_info",
        description="[MCP/Filesystem] Get metadata (size, mtime) of a file via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Docker MCP Server ────────────────────────────────────
    "mcp_docker_list_containers": ToolDefinition(
        name="mcp_docker_list_containers",
        description="[MCP/Docker] List running and stopped Docker containers",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_docker_get_container_logs": ToolDefinition(
        name="mcp_docker_get_container_logs",
        description="[MCP/Docker] Retrieve recent logs from a Docker container",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_docker_inspect_container": ToolDefinition(
        name="mcp_docker_inspect_container",
        description="[MCP/Docker] Inspect detailed metadata of a Docker container",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_docker_restart_container": ToolDefinition(
        name="mcp_docker_restart_container",
        description="[MCP/Docker] Restart a Docker container by name or ID",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "mcp_docker_list_images": ToolDefinition(
        name="mcp_docker_list_images",
        description="[MCP/Docker] List locally available Docker images",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Time MCP Server ──────────────────────────────────────
    "mcp_time_get_current_time": ToolDefinition(
        name="mcp_time_get_current_time",
        description="[MCP/Time] Get current time in a given timezone",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_time_convert_time": ToolDefinition(
        name="mcp_time_convert_time",
        description="[MCP/Time] Convert a time between timezones",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Fetch MCP Server ─────────────────────────────────────
    "mcp_fetch_get": ToolDefinition(
        name="mcp_fetch_get",
        description="[MCP/Fetch] HTTP GET a URL and return the response body",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── SQLite MCP Server ────────────────────────────────────
    "mcp_sqlite_read_query": ToolDefinition(
        name="mcp_sqlite_read_query",
        description="[MCP/SQLite] Execute a read-only SQL query via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_sqlite_list_tables": ToolDefinition(
        name="mcp_sqlite_list_tables",
        description="[MCP/SQLite] List all tables in a SQLite database via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_sqlite_describe_table": ToolDefinition(
        name="mcp_sqlite_describe_table",
        description="[MCP/SQLite] Describe the schema of a SQLite table via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Slack MCP Server ─────────────────────────────────────
    "mcp_slack_post_message": ToolDefinition(
        name="mcp_slack_post_message",
        description="[MCP/Slack] Post a message to a Slack channel via MCP",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "mcp_slack_list_channels": ToolDefinition(
        name="mcp_slack_list_channels",
        description="[MCP/Slack] List available Slack channels via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "mcp_slack_get_channel_history": ToolDefinition(
        name="mcp_slack_get_channel_history",
        description="[MCP/Slack] Get message history from a Slack channel via MCP",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    # ── Browser Control (Sprint 4) ───────────────────────────
    "browser_open": ToolDefinition(
        name="browser_open",
        description="[Browser] Navigate to a URL in the agent's browser session (http/https only)",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_click": ToolDefinition(
        name="browser_click",
        description="[Browser] Click a page element by CSS selector",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_type": ToolDefinition(
        name="browser_type",
        description="[Browser] Type text into an input element by CSS selector",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_select": ToolDefinition(
        name="browser_select",
        description="[Browser] Select an option in a <select> element",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_snapshot": ToolDefinition(
        name="browser_snapshot",
        description="[Browser] Return the accessibility tree snapshot of the current page",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "browser_screenshot": ToolDefinition(
        name="browser_screenshot",
        description="[Browser] Capture a screenshot and save it under output/browser/",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_upload": ToolDefinition(
        name="browser_upload",
        description="[Browser] Upload a file via a file-input element",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "browser_close": ToolDefinition(
        name="browser_close",
        description="[Browser] Close the agent's browser session",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    # -----------------------------------------------------------------------
    # Sandbox tools (Sprint 8)
    # -----------------------------------------------------------------------
    "sandbox_exec": ToolDefinition(
        name="sandbox_exec",
        description="Execute a shell command inside the agent's Docker sandbox container (falls back to workspace directory when Docker is disabled)",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    # ── Higgsfield Browser Tools (routed to higgsfield_playwright_server:8812) ──
    "hf_login": ToolDefinition(
        name="hf_login",
        description="[Higgsfield] Restore or establish a Higgsfield.ai browser session from saved cookies",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "hf_navigate": ToolDefinition(
        name="hf_navigate",
        description="[Higgsfield] Navigate to a path on app.higgsfield.ai (blocks all billing/purchase URLs)",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "hf_create_soul_id": ToolDefinition(
        name="hf_create_soul_id",
        description="[Higgsfield] Upload a character reference image and create a Soul ID on Higgsfield.ai",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "hf_submit_video": ToolDefinition(
        name="hf_submit_video",
        description="[Higgsfield] Configure and queue a video generation job. Soul ID must be active first.",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
    "hf_poll_result": ToolDefinition(
        name="hf_poll_result",
        description="[Higgsfield] Poll a queued video job until it completes or times out",
        modification_type=ModificationType.READ_ONLY,
        requires_doc_update=False,
    ),
    "hf_log_evidence": ToolDefinition(
        name="hf_log_evidence",
        description="[Higgsfield] Capture a screenshot of current browser state and write a structured RAG log entry",
        modification_type=ModificationType.STATE_MODIFY,
        requires_doc_update=False,
    ),
}


def get_tool_definitions() -> list[ToolDefinition]:
    """Return all registered tool definitions."""
    return list(TOOL_REGISTRY.values())


def get_tool_definition(name: str) -> ToolDefinition | None:
    """Look up a tool definition by name."""
    return TOOL_REGISTRY.get(name)


def to_openai_schema(tool: ToolDefinition) -> dict[str, Any]:
    """
    Convert a ToolDefinition to an OpenAI-compatible tool spec dict.

    If the tool has a ``parameters`` JSON Schema attached, that schema is used
    directly. Otherwise a permissive catch-all object schema is emitted so
    the spec remains valid for any OpenAI-compatible endpoint.

    Returns a dict matching the OpenAI ``tools`` array entry format::

        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { ... },
            }
        }
    """
    parameters: dict[str, Any] = tool.parameters or {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        },
    }


def tools_to_openai_schemas(tool_names: list[str]) -> list[dict[str, Any]]:
    """
    Convert a list of tool names to OpenAI tool spec dicts.

    Silently skips any name not found in TOOL_REGISTRY.
    """
    schemas: list[dict[str, Any]] = []
    for name in tool_names:
        defn = TOOL_REGISTRY.get(name)
        if defn is not None:
            schemas.append(to_openai_schema(defn))
    return schemas


# ---------------------------------------------------------------------------
# safe_shell — Whitelisted command execution
# ---------------------------------------------------------------------------


async def safe_shell(command: str, agent_id: str) -> dict[str, Any]:
    """
    Execute a whitelisted shell command.

    Safety constraints (per DRIFT_GUARD.md):
    - Only whitelisted commands allowed
    - Shell metacharacters blocked (no chaining/injection)
    - Cannot install packages (PROH-7)
    - Cannot delete directories recursively (PROH-6)
    - Cannot modify /docs directly without registry update (PROH-8)
    - Cannot read sensitive system paths (/etc/, /proc/, /sys/)
    - Uses subprocess_exec (not shell) to prevent injection

    Args:
        command: The shell command to execute.
        agent_id: The calling agent's ID.

    Returns:
        Dict with stdout, stderr, return_code.
    """
    # 0. Block shell metacharacters (prevents chaining / injection)
    for char in SHELL_DANGEROUS_CHARS:
        if char in command:
            error = f"BLOCKED: Command contains dangerous character/sequence '{char}'"
            logger.warning(f"safe_shell BLOCKED for {agent_id}: {error}")
            return {"stdout": "", "stderr": error, "return_code": -1, "blocked": True}

    # 1. Validate against blacklist
    cmd_lower = command.lower()
    for pattern in SAFE_SHELL_BLACKLIST:
        if pattern in cmd_lower:
            error = f"BLOCKED: Command contains blacklisted pattern '{pattern}'"
            logger.warning(f"safe_shell BLOCKED for {agent_id}: {error}")
            return {"stdout": "", "stderr": error, "return_code": -1, "blocked": True}

    # 2. Validate against whitelist — command must start with a whitelisted command
    parts = command.strip().split()
    cmd_base = parts[0] if parts else ""
    if cmd_base not in SAFE_SHELL_WHITELIST:
        error = f"BLOCKED: Command '{cmd_base}' not in whitelist"
        logger.warning(f"safe_shell BLOCKED for {agent_id}: {error}")
        return {"stdout": "", "stderr": error, "return_code": -1, "blocked": True}

    # 3. Check if command targets /docs (PROH-8)
    if "/docs" in command or "docs/" in command:
        error = "BLOCKED: Cannot modify /docs via shell. Use doc_updater tool."
        logger.warning(f"safe_shell BLOCKED for {agent_id}: {error}")
        return {"stdout": "", "stderr": error, "return_code": -1, "blocked": True}

    # 4. Restrict path arguments to project directory
    for arg in parts[1:]:
        if arg.startswith("-"):
            continue  # skip flags
        try:
            if arg.startswith("/"):
                resolved = Path(os.path.normpath(str(arg)))
            else:
                resolved = Path(os.path.normpath(str(PROJECT_ROOT / arg)))
            if not str(resolved).startswith(str(PROJECT_ROOT)):
                error = f"BLOCKED: Path argument '{arg}' resolves outside project directory"
                logger.warning(f"safe_shell BLOCKED for {agent_id}: {error}")
                return {"stdout": "", "stderr": error, "return_code": -1, "blocked": True}
        except (ValueError, OSError):
            pass  # non-path arguments are fine

    # 5. Execute the command using subprocess_exec (NOT shell) for safety
    try:
        process = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        result = {
            "stdout": stdout.decode("utf-8", errors="replace")[:4096],
            "stderr": stderr.decode("utf-8", errors="replace")[:4096],
            "return_code": process.returncode,
            "blocked": False,
        }
        logger.info(f"safe_shell executed by {agent_id}: {command[:100]}")
        return result

    except TimeoutError:
        return {
            "stdout": "",
            "stderr": "Command timed out after 30 seconds",
            "return_code": -1,
            "blocked": False,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "blocked": False,
        }


# ---------------------------------------------------------------------------
# file_reader — Safe file reading
# ---------------------------------------------------------------------------


async def file_reader(file_path: str, agent_id: str) -> dict[str, Any]:
    """
    Read file contents safely.

    Restricts reading to the project directory.
    READ_ONLY — no modification, no doc update required.

    Args:
        file_path: Path to the file to read.
        agent_id: The calling agent's ID.

    Returns:
        Dict with content, size, exists.
    """
    try:
        path = Path(
            os.path.normpath(str(file_path) if Path(file_path).is_absolute() else str(PROJECT_ROOT / file_path))
        )

        # Security: restrict to project directory
        if not str(path).startswith(str(PROJECT_ROOT)):
            return {
                "content": "",
                "error": "Access denied: path outside project directory",
                "exists": False,
            }

        # Security: block symlinks that escape the project directory
        raw_path = Path(file_path)
        if raw_path.is_symlink():
            link_target = raw_path.resolve()
            if not str(link_target).startswith(str(PROJECT_ROOT)):
                return {
                    "content": "",
                    "error": "Access denied: symlink points outside project directory",
                    "exists": False,
                }

        if not path.exists():
            return {"content": "", "error": "File not found", "exists": False}

        if not path.is_file():
            return {"content": "", "error": "Path is not a file", "exists": True}

        # Route PDFs, images, and Office docs through GLM-OCR before the
        # binary-extension block.  Falls back to the normal text read if the
        # microservice is unavailable.
        if ocr_supported(str(path)):
            markdown = await ocr_extract_text(str(path))
            if markdown:
                logger.info(f"file_reader (ocr) by {agent_id}: {file_path}")
                return {
                    "content": markdown[:10000],
                    "size": path.stat().st_size,
                    "exists": True,
                    "source": "glmocr",
                }
            # Microservice down — fall through to normal read (text PDFs may
            # still work; binary images will hit the block below)

        content = path.read_text(errors="replace")[:10000]  # Limit size
        logger.info(f"file_reader by {agent_id}: {file_path}")
        return {
            "content": content,
            "size": path.stat().st_size,
            "exists": True,
        }

    except Exception as e:
        return {"content": "", "error": str(e), "exists": False}


# ---------------------------------------------------------------------------
# document_ocr — GLM-OCR document extraction
# ---------------------------------------------------------------------------


async def document_ocr(file_path: str, agent_id: str) -> dict[str, Any]:
    """
    Extract clean Markdown from a PDF, image, or Office document via GLM-OCR.

    Agents should call this instead of file_reader when they need structured
    content from a document — it produces far fewer tokens than raw text dumps.

    READ_ONLY — no modification, no doc update required.

    Supported: .pdf .png .jpg .jpeg .tiff .tif .webp .bmp .doc .docx

    Args:
        file_path: Absolute or project-relative path to the document.
        agent_id: The calling agent's ID.

    Returns:
        Dict with markdown content, page estimates, and glmocr metadata.
    """
    try:
        path = Path(
            os.path.normpath(str(file_path) if Path(file_path).is_absolute() else str(PROJECT_ROOT / file_path))
        )

        if not str(path).startswith(str(PROJECT_ROOT)):
            return {"content": "", "error": "Access denied: path outside project directory"}

        if not path.exists():
            return {"content": "", "error": "File not found"}

        if not path.is_file():
            return {"content": "", "error": "Path is not a file"}

        suffix = path.suffix.lower()
        if suffix not in OCR_EXTENSIONS:
            return {
                "content": "",
                "error": (f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(OCR_EXTENSIONS))}"),
            }

        markdown = await ocr_extract_text(str(path))
        if markdown is None:
            return {
                "content": "",
                "error": ("GLM-OCR microservice unavailable. Start it with: python -m glmocr.server"),
            }

        logger.info(f"document_ocr by {agent_id}: {file_path} ({len(markdown):,} chars)")
        return {
            "content": markdown,
            "char_count": len(markdown),
            "size": path.stat().st_size,
            "source": "glmocr",
        }

    except Exception as e:
        return {"content": "", "error": str(e)}


# ---------------------------------------------------------------------------
# doc_updater — Governance documentation update tool
# ---------------------------------------------------------------------------


async def doc_updater(
    target: str,
    content: str,
    agent_id: str,
    reason: str,
    impacted_subsystems: list[str] | None = None,
) -> dict[str, Any]:
    """
    Update governance documentation files.

    ARCHITECTURAL_MODIFY — requires change log entry.
    This is the ONLY sanctioned way to modify /docs (PROH-8).

    Supported targets:
    - "source_of_truth": Append to SOURCE_OF_TRUTH.md
    - "change_log": Append to CHANGE_LOG.md
    - "agent_registry": Append to AGENT_REGISTRY.md

    Args:
        target: Which document to update.
        content: Content to append.
        agent_id: The calling agent's ID.
        reason: Why the update is needed.
        impacted_subsystems: List of affected subsystems.

    Returns:
        Dict with success status and message.
    """
    target_map: dict[str, Path] = {
        "source_of_truth": SOURCE_OF_TRUTH_PATH,
        "change_log": CHANGE_LOG_PATH,
        "agent_registry": AGENT_REGISTRY_PATH,
    }

    if target not in target_map:
        return {
            "success": False,
            "message": f"Unknown target: {target}. Valid: {list(target_map.keys())}",
        }

    target_path = target_map[target]

    # First, log the change in CHANGE_LOG (INV-5: documentation precedes mutation)
    entry = ChangeLogEntry(
        agent_id=agent_id,
        files_modified=[str(target_path.relative_to(PROJECT_ROOT))],
        reason=reason,
        risk_assessment=ChangeImpactLevel.MEDIUM,
        impacted_subsystems=impacted_subsystems or ["documentation"],
        documentation_updated=True,
    )
    await drift_guard.append_change_log(entry)

    # Now append content to the target document
    try:
        with open(target_path, "a") as f:
            f.write(f"\n{content}\n")

        logger.info(f"doc_updater: {target} updated by {agent_id}")
        return {
            "success": True,
            "message": f"Updated {target_path.name}",
            "change_log_entry": entry.model_dump(mode="json"),
        }

    except Exception as e:
        error_msg = f"Failed to update {target}: {e}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg}


# ---------------------------------------------------------------------------
# system_info — System information retrieval
# ---------------------------------------------------------------------------


async def system_info(agent_id: str) -> dict[str, Any]:
    """
    Retrieve system information.

    READ_ONLY — no modification, no doc update required.

    Args:
        agent_id: The calling agent's ID.

    Returns:
        Dict with system information.
    """
    try:
        disk = shutil.disk_usage("/")
        info = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0],
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"system_info retrieved by {agent_id}")
        return info

    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# webhook_send — HTTP POST notification
# ---------------------------------------------------------------------------


async def webhook_send(url: str, payload: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """
    Send an HTTP POST to a webhook URL with a JSON payload.

    STATE_MODIFY — records the outbound call in the event log.
    URL must use http or https scheme only.
    """
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "URL must start with http:// or https://"}

    # SSRF protection: block requests to internal/private networks
    url_lower = url.lower()
    for prefix in SSRF_BLOCKED_PREFIXES:
        if url_lower.startswith(prefix):
            return {"success": False, "error": "BLOCKED: URL targets a restricted internal address"}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Agentop/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            body = resp.read(2048).decode("utf-8", errors="replace")
        logger.info(f"webhook_send by {agent_id}: POST {url} → {status}")
        return {"success": True, "status_code": status, "response_body": body}
    except urllib.error.URLError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# git_ops — Read-only git operations
# ---------------------------------------------------------------------------

_GIT_ALLOWED_SUBCMDS = {"log", "status", "diff", "show", "branch", "tag", "remote"}


async def git_ops(subcommand: str, agent_id: str) -> dict[str, Any]:
    """
    Execute a read-only git sub-command.

    READ_ONLY — never modifies the repository.
    Only a whitelist of safe sub-commands is permitted.
    """
    parts = subcommand.strip().split()
    if not parts or parts[0] not in _GIT_ALLOWED_SUBCMDS:
        return {
            "stdout": "",
            "stderr": f"Sub-command '{parts[0] if parts else ''}' not allowed. Allowed: {sorted(_GIT_ALLOWED_SUBCMDS)}",
            "return_code": -1,
        }

    cmd = ["git"] + parts
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        logger.info(f"git_ops by {agent_id}: git {subcommand[:80]}")
        return {
            "stdout": stdout.decode("utf-8", errors="replace")[:4096],
            "stderr": stderr.decode("utf-8", errors="replace")[:1024],
            "return_code": process.returncode,
        }
    except TimeoutError:
        return {"stdout": "", "stderr": "git command timed out", "return_code": -1}
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "return_code": -1}


# ---------------------------------------------------------------------------
# health_check — HTTP endpoint health probe
# ---------------------------------------------------------------------------


async def health_check(url: str, agent_id: str) -> dict[str, Any]:
    """
    Perform an HTTP GET health check and return status + latency.

    READ_ONLY — makes no changes.
    """
    if not url.startswith(("http://", "https://")):
        return {"reachable": False, "error": "URL must start with http:// or https://"}

    # SSRF protection: block requests to internal/private networks
    url_lower = url.lower()
    for prefix in SSRF_BLOCKED_PREFIXES:
        if url_lower.startswith(prefix):
            return {"reachable": False, "error": "BLOCKED: URL targets a restricted internal address"}

    import time

    start = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "Agentop-HealthCheck/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            status = resp.getcode()
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            logger.info(f"health_check by {agent_id}: {url} → {status} ({latency_ms}ms)")
            return {
                "reachable": True,
                "status_code": status,
                "latency_ms": latency_ms,
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"reachable": True, "status_code": exc.code, "latency_ms": latency_ms, "url": url}
    except urllib.error.URLError as exc:
        return {"reachable": False, "error": str(exc), "url": url}
    except Exception as exc:
        return {"reachable": False, "error": str(exc), "url": url}


# ---------------------------------------------------------------------------
# log_tail — Tail log file contents
# ---------------------------------------------------------------------------


async def log_tail(file_path: str, lines: int, agent_id: str) -> dict[str, Any]:
    """
    Return the last N lines of a log file.

    READ_ONLY — restricted to project directory.
    """
    try:
        path = Path(
            os.path.normpath(str(file_path) if Path(file_path).is_absolute() else str(PROJECT_ROOT / file_path))
        )
        if not str(path).startswith(str(PROJECT_ROOT)):
            return {"content": "", "error": "Access denied: path outside project directory"}
        if not path.exists() or not path.is_file():
            return {"content": "", "error": "File not found or not a regular file"}

        all_lines = path.read_text(errors="replace").splitlines()
        tail_lines = all_lines[-max(1, min(int(lines), 500)) :]
        logger.info(f"log_tail by {agent_id}: {file_path} ({len(tail_lines)} lines)")
        return {"content": "\n".join(tail_lines), "total_lines": len(all_lines), "returned_lines": len(tail_lines)}
    except Exception as exc:
        return {"content": "", "error": str(exc)}


# ---------------------------------------------------------------------------
# alert_dispatch — Publish alert to shared event log
# ---------------------------------------------------------------------------


async def alert_dispatch(
    level: str,
    title: str,
    message: str,
    agent_id: str,
) -> dict[str, Any]:
    """
    Dispatch a named alert to the shared events log.

    STATE_MODIFY — appends to shared events (via memory_store, respecting INV-9).
    """
    from backend.memory import memory_store as _ms

    level_normalised = level.upper()
    if level_normalised not in {"INFO", "WARNING", "ERROR", "CRITICAL"}:
        level_normalised = "INFO"

    event: dict[str, Any] = {
        "type": "ALERT",
        "level": level_normalised,
        "title": title,
        "message": message,
        "source_agent": agent_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    _ms.append_shared_event(event)
    logger.info(f"alert_dispatch [{level_normalised}] by {agent_id}: {title}")
    return {"dispatched": True, "level": level_normalised, "title": title}


# ---------------------------------------------------------------------------
# secret_scanner — Detect credential/secret patterns in source files
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("API Key (generic)", re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private Key Header", re.compile(r"-----BEGIN\s+(RSA|EC|OPENSSH)\s+PRIVATE KEY-----")),
    ("Password in code", re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}")),
    ("Bearer token", re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-_\.]{20,}")),
    ("JWT", re.compile(r"eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Database URL", re.compile(r"(?i)(mysql|postgres|mongodb|redis)://[^@]+:[^@]+@")),
]


async def secret_scanner(target_path: str, agent_id: str) -> dict[str, Any]:
    """
    Recursively scan a file or directory for common secret patterns.

    READ_ONLY — makes no changes, reports findings.
    """
    target = Path(
        os.path.normpath(str(target_path) if Path(target_path).is_absolute() else str(PROJECT_ROOT / target_path))
    )
    if not str(target).startswith(str(PROJECT_ROOT)):
        return {"findings": [], "error": "Access denied: path outside project directory"}
    if not target.exists():
        return {"findings": [], "error": "Path does not exist"}

    _skip_dirs = {".git", "__pycache__", "node_modules", ".next", "dist", "build", "venv", ".venv"}
    _skip_exts = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".zip", ".bin"}
    # .env files are the designated secrets location — scanning them always
    # produces findings and is a known false positive. They are gitignored.
    _skip_names = {".env", ".env.local", ".env.development", ".env.production", ".env.test"}

    findings: list[dict[str, Any]] = []
    files_scanned = 0
    files: list[Path] = []
    if target.is_file() and target.name not in _skip_names:
        files = [target]

    if target.is_dir():
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if any(part in _skip_dirs for part in f.parts):
                continue
            if f.suffix.lower() in _skip_exts:
                continue
            if f.name in _skip_names:
                continue
            files.append(f)

    for file in files[:200]:  # cap to 200 files per scan
        try:
            text = file.read_text(errors="replace")
            files_scanned += 1
            for pattern_name, pattern in _SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    # Redact the actual secret — show only pattern type and location
                    raw = match.group(0)
                    redacted = raw[:8] + "****" if len(raw) > 8 else "****"
                    findings.append(
                        {
                            "file": str(file.relative_to(PROJECT_ROOT)),
                            "line": line_no,
                            "pattern": pattern_name,
                            "snippet": redacted,
                        }
                    )
                    if len(findings) >= 50:
                        break
                if len(findings) >= 50:
                    break
        except Exception:
            continue

    logger.info(f"secret_scanner by {agent_id}: {target_path} — {files_scanned} files, {len(findings)} findings")
    return {"findings": findings, "files_scanned": files_scanned, "target": str(target.relative_to(PROJECT_ROOT))}


# ---------------------------------------------------------------------------
# db_query — Read-only SQLite query
# ---------------------------------------------------------------------------


async def db_query(db_path: str, query: str, agent_id: str) -> dict[str, Any]:
    """
    Execute a read-only SELECT query against a SQLite database.

    READ_ONLY — only SELECT statements allowed.
    """
    query_stripped = query.strip().upper()
    if not query_stripped.startswith("SELECT") and not query_stripped.startswith("PRAGMA"):
        return {"rows": [], "error": "Only SELECT and PRAGMA queries are permitted"}

    path = Path(os.path.normpath(str(db_path) if Path(db_path).is_absolute() else str(PROJECT_ROOT / db_path)))
    if not str(path).startswith(str(PROJECT_ROOT)):
        return {"rows": [], "error": "Access denied: path outside project directory"}
    if not path.exists():
        return {"rows": [], "error": "Database file not found"}

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query)
        rows = [dict(r) for r in cur.fetchmany(200)]
        conn.close()
        logger.info(f"db_query by {agent_id}: {db_path} — {len(rows)} rows")
        return {"rows": rows, "count": len(rows)}
    except sqlite3.OperationalError as exc:
        return {"rows": [], "error": str(exc)}
    except Exception as exc:
        return {"rows": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# process_restart — Restart a whitelisted process
# ---------------------------------------------------------------------------

_RESTARTABLE_PROCESSES: dict[str, list[str]] = {
    "backend": ["pkill", "-f", "uvicorn"],
    "frontend": ["pkill", "-f", "next dev"],
    "ollama": ["pkill", "-f", "ollama serve"],
}


async def process_restart(
    process_name: str,
    agent_id: str,
    confirm: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """
    Send SIGTERM to a whitelisted process by logical name.

    STATE_MODIFY — terminates a running process (service manager restarts it).
    Only names declared in _RESTARTABLE_PROCESSES are allowed.

    Callers MUST pass confirm=True and a non-empty reason string or the call
    is rejected. This prevents runaway restart loops during dev sessions.
    """
    if not confirm or not reason:
        logger.warning(f"[process_restart] BLOCKED — no confirm payload. agent={agent_id} process={process_name}")
        return {"success": False, "error": "confirm payload required (pass confirm=True and reason='...')"}

    if process_name not in _RESTARTABLE_PROCESSES:
        return {
            "success": False,
            "error": f"Process '{process_name}' not in restart whitelist. "
            f"Allowed: {list(_RESTARTABLE_PROCESSES.keys())}",
        }

    cmd = _RESTARTABLE_PROCESSES[process_name]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=10)
        logger.info(f"process_restart by {agent_id}: {process_name}")
        return {"success": True, "process": process_name, "return_code": process.returncode}
    except TimeoutError:
        return {"success": False, "error": "Restart command timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# folder_analyzer — Recursive folder indexing for agent analysis
# ---------------------------------------------------------------------------

_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".scss",
    ".sh",
    ".bash",
    ".zsh",
    ".env",
    ".env.example",
    ".gitignore",
    ".dockerfile",
    ".conf",
    ".xml",
    ".csv",
    ".sql",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".lua",
    ".r",
    ".jl",
    ".ex",
    ".exs",
    ".erl",
}

_SKIP_DIRS_ANALYZE = {
    ".git",
    "__pycache__",
    "node_modules",
    ".next",
    "dist",
    "build",
    "venv",
    ".venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "target",
    "bin",
    "obj",
    ".idea",
    ".vscode",
}

_SKIP_EXTS_ANALYZE = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".bmp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".mp4",
    ".avi",
    ".wav",
    ".flac",
    ".pyc",
    ".o",
    ".a",
    ".class",
}


async def folder_analyzer(
    folder_path: str,
    agent_id: str,
    max_files: int = 200,
    snippet_lines: int = 30,
    include_content: bool = True,
) -> dict[str, Any]:
    """
    Recursively index a folder and return structured analysis data.

    Returns a file tree with metadata (size, extension, line count)
    and optional content snippets for each text file.

    READ_ONLY — makes no modifications.
    Restricted to PROJECT_ROOT for security.

    Args:
        folder_path: Absolute or project-relative path to analyse.
        agent_id: The calling agent's ID.
        max_files: Maximum files to index (default 200).
        snippet_lines: Lines of content to include per file (default 30).
        include_content: Whether to include file content snippets.

    Returns:
        Dict with tree, file_count, dir_count, total_size, and files list.
    """
    try:
        raw = Path(folder_path)
        if raw.is_absolute():
            root = Path(os.path.normpath(str(raw)))
        else:
            root = Path(os.path.normpath(str(PROJECT_ROOT / raw)))

        # Security: restrict to project directory
        if not str(root).startswith(str(PROJECT_ROOT)):
            return {"error": "Access denied: path outside project directory", "files": []}

        if not root.exists():
            return {"error": f"Path does not exist: {folder_path}", "files": []}
        if not root.is_dir():
            return {"error": f"Path is not a directory: {folder_path}", "files": []}

        files_data: list[dict[str, Any]] = []
        dir_count = 0
        total_size = 0
        tree_lines: list[str] = [f"{root.name}/"]

        def _walk(directory: Path, prefix: str = "") -> None:
            nonlocal dir_count, total_size

            try:
                entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                return

            for i, entry in enumerate(entries):
                if len(files_data) >= max_files:
                    return

                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                extension = "    " if is_last else "│   "

                name = entry.name
                if entry.is_dir():
                    if name in _SKIP_DIRS_ANALYZE:
                        continue
                    if entry.is_symlink():
                        continue  # skip symlinked dirs for security
                    dir_count += 1
                    tree_lines.append(f"{prefix}{connector}{name}/")
                    _walk(entry, prefix + extension)
                elif entry.is_file():
                    suffix = entry.suffix.lower()
                    if suffix in _SKIP_EXTS_ANALYZE:
                        continue
                    if entry.is_symlink():
                        target = entry.resolve()
                        if not str(target).startswith(str(PROJECT_ROOT)):
                            continue  # skip symlinks escaping project

                    try:
                        stat = entry.stat()
                    except (PermissionError, OSError):
                        continue

                    size = stat.st_size
                    total_size += size
                    tree_lines.append(f"{prefix}{connector}{name}")

                    file_info: dict[str, Any] = {
                        "path": str(entry.relative_to(PROJECT_ROOT)),
                        "name": name,
                        "extension": suffix,
                        "size_bytes": size,
                        "is_text": suffix in _TEXT_EXTENSIONS or suffix == "",
                    }

                    # Read content snippet for text files
                    if include_content and file_info["is_text"] and size < 512_000:
                        try:
                            text = entry.read_text(errors="replace")
                            lines = text.splitlines()
                            file_info["line_count"] = len(lines)
                            file_info["content_snippet"] = "\n".join(lines[:snippet_lines])
                            if len(lines) > snippet_lines:
                                file_info["content_snippet"] += f"\n... ({len(lines) - snippet_lines} more lines)"
                        except Exception:
                            file_info["line_count"] = 0
                            file_info["content_snippet"] = "(read error)"
                    else:
                        file_info["line_count"] = None
                        file_info["content_snippet"] = None

                    files_data.append(file_info)

        _walk(root)

        # Build summary stats
        ext_counts: dict[str, int] = {}
        for f in files_data:
            ext = f["extension"] or "(none)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        logger.info(
            f"folder_analyzer by {agent_id}: {folder_path} — "
            f"{len(files_data)} files, {dir_count} dirs, {total_size} bytes"
        )

        return {
            "folder": str(root.relative_to(PROJECT_ROOT)),
            "file_count": len(files_data),
            "dir_count": dir_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 4),
            "extension_summary": ext_counts,
            "tree": "\n".join(tree_lines[:500]),  # cap tree output
            "files": files_data,
            "truncated": len(files_data) >= max_files,
        }

    except Exception as e:
        return {"error": str(e), "files": []}


# ---------------------------------------------------------------------------
# k8s_control — Kubernetes cluster management
# ---------------------------------------------------------------------------


async def k8s_control(
    action: str,
    agent_id: str,
    job_name: str = "",
    image: str = "",
    command: str = "",
    namespace: str = "agent-ops",
) -> dict[str, Any]:
    """
    Control Kubernetes cluster for autonomous agent deployment.

    STATE_MODIFY — creates/deletes K8s resources.

    Supported actions:
    - list_pods: Get all pods in namespace
    - list_jobs: Get all jobs in namespace
    - create_job: Create a new job (requires job_name, image, command)
    - delete_job: Delete a job by name
    - get_logs: Get logs from most recent pod

    Args:
        action: The K8s operation to perform.
        agent_id: The calling agent's ID.
        job_name: Name for job operations.
        image: Container image (e.g., 'python:3.11', 'busybox').
        command: Shell command to run in job.
        namespace: K8s namespace (default: agent-ops).

    Returns:
        Dict with output, success status, and metadata.

    Example:
        # List all pods
        await k8s_control("list_pods", "devops_agent", namespace="agent-ops")

        # Deploy a monitoring agent
        await k8s_control(
            "create_job",
            "devops_agent",
            job_name="network-monitor",
            image="python:3.11",
            command="pip install scapy && python monitor.py",
            namespace="agent-ops"
        )
    """
    logger.info(f"k8s_control called by {agent_id}: action={action}, namespace={namespace}")

    try:
        if action == "list_pods":
            process = await asyncio.create_subprocess_exec(
                "kubectl",
                "get",
                "pods",
                "-n",
                namespace,
                "-o",
                "wide",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8", errors="replace"),
                    "action": action,
                }

            return {
                "success": True,
                "output": stdout.decode("utf-8", errors="replace"),
                "action": action,
                "namespace": namespace,
            }

        elif action == "list_jobs":
            process = await asyncio.create_subprocess_exec(
                "kubectl",
                "get",
                "jobs",
                "-n",
                namespace,
                "-o",
                "wide",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8", errors="replace"),
                    "action": action,
                }

            return {
                "success": True,
                "output": stdout.decode("utf-8", errors="replace"),
                "action": action,
                "namespace": namespace,
            }

        elif action == "create_job":
            if not job_name or not image or not command:
                return {
                    "success": False,
                    "error": "create_job requires job_name, image, and command",
                    "action": action,
                }

            # Security: sanitize job name (K8s naming rules)
            safe_name = re.sub(r"[^a-z0-9-]", "-", job_name.lower())[:63]

            process = await asyncio.create_subprocess_exec(
                "kubectl",
                "create",
                "job",
                safe_name,
                f"--image={image}",
                "-n",
                namespace,
                "--",
                "/bin/sh",
                "-c",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8", errors="replace"),
                    "action": action,
                }

            logger.info(f"k8s_control: Job '{safe_name}' created by {agent_id}")
            return {
                "success": True,
                "output": stdout.decode("utf-8", errors="replace"),
                "action": action,
                "job_name": safe_name,
                "namespace": namespace,
            }

        elif action == "delete_job":
            if not job_name:
                return {
                    "success": False,
                    "error": "delete_job requires job_name",
                    "action": action,
                }

            process = await asyncio.create_subprocess_exec(
                "kubectl",
                "delete",
                "job",
                job_name,
                "-n",
                namespace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode("utf-8", errors="replace"),
                    "action": action,
                }

            logger.info(f"k8s_control: Job '{job_name}' deleted by {agent_id}")
            return {
                "success": True,
                "output": stdout.decode("utf-8", errors="replace"),
                "action": action,
                "job_name": job_name,
            }

        elif action == "get_logs":
            # Get logs from most recent pod in namespace
            process = await asyncio.create_subprocess_exec(
                "kubectl",
                "logs",
                "-n",
                namespace,
                "--tail=100",
                "-l",
                "app=agentop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

            return {
                "success": process.returncode == 0,
                "output": stdout.decode("utf-8", errors="replace"),
                "error": stderr.decode("utf-8", errors="replace") if process.returncode != 0 else None,
                "action": action,
            }

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Supported: list_pods, list_jobs, create_job, delete_job, get_logs",
                "action": action,
            }

    except TimeoutError:
        return {
            "success": False,
            "error": f"kubectl {action} timed out after 15 seconds",
            "action": action,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "action": action,
        }


# ---------------------------------------------------------------------------
# browser_control — Drive browser-worker pod via HTTP
# ---------------------------------------------------------------------------

_BROWSER_WORKER_URL = _os.environ.get(
    "BROWSER_WORKER_URL",
    "http://browser-worker.agent-ops.svc.cluster.local:8080",
)

_BROWSER_ACTIONS = {"navigate", "click", "fill", "select", "screenshot", "evaluate", "back", "url"}


async def browser_control(
    action: str,
    agent_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """HTTP proxy to the browser-worker pod.

    Supported actions: navigate, click, fill, select, screenshot, evaluate, back, url.
    """
    import httpx

    if action not in _BROWSER_ACTIONS:
        return {
            "success": False,
            "error": f"Unknown action '{action}'. Supported: {sorted(_BROWSER_ACTIONS)}",
        }

    endpoint = f"{_BROWSER_WORKER_URL}/{action}"

    # Build payload — screenshot/back/url take no body
    payload: dict[str, Any] = {}
    if action == "navigate":
        payload = {"url": kwargs.get("url", "")}
    elif action == "click":
        payload = {"selector": kwargs.get("selector", ""), "timeout_ms": int(kwargs.get("timeout_ms", 10000))}
    elif action == "fill":
        payload = {
            "selector": kwargs.get("selector", ""),
            "value": kwargs.get("value", ""),
            "field_name": kwargs.get("field_name", "value"),
            "timeout_ms": int(kwargs.get("timeout_ms", 10000)),
        }
    elif action == "select":
        payload = {
            "selector": kwargs.get("selector", ""),
            "option_value": kwargs.get("option_value", ""),
            "timeout_ms": int(kwargs.get("timeout_ms", 10000)),
        }
    elif action == "evaluate":
        payload = {"expression": kwargs.get("expression", "")}

    method = "GET" if action == "url" else "POST"

    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            if method == "GET":
                resp = await client.get(endpoint)
            else:
                resp = await client.post(endpoint, json=payload if payload else None)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"browser_control [{action}] by {agent_id}: {data}")
        return {"success": True, "action": action, **data}
    except httpx.ConnectError:
        return {
            "success": False,
            "error": "Cannot reach browser-worker pod. Is it deployed and port-forwarded?",
            "hint": "kubectl port-forward -n agent-ops svc/browser-worker 8082:8080",
        }
    except httpx.HTTPStatusError as exc:
        return {"success": False, "error": f"browser-worker returned {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool Executor — Routes tool calls through DriftGuard middleware
# ---------------------------------------------------------------------------


async def execute_tool(
    tool_name: str,
    agent_id: str,
    allowed_tools: list[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute a tool with full governance enforcement.

    This is the SINGLE entry point for all tool executions.
    It enforces:
    1. Tool exists in registry (INV-3)
    2. Agent has permission to use the tool
    3. DriftGuard middleware passes
    4. Execution is logged (INV-7)

    Args:
        tool_name: Name of the tool to execute.
        agent_id: ID of the invoking agent.
        allowed_tools: List of tools the agent is permitted to use.
        **kwargs: Tool-specific arguments.

    Returns:
        The tool's return value.
    """
    # 1. Check tool exists (INV-3: no dynamic tools)
    tool_def = get_tool_definition(tool_name)
    if tool_def is None:
        logger.warning(f"Unknown tool requested: {tool_name} by {agent_id}")
        return {"error": f"Tool '{tool_name}' not found in registry"}

    # 2. Check agent permission
    if not drift_guard.validate_agent_tool_access(agent_id, tool_name, allowed_tools):
        return {"error": f"Agent '{agent_id}' not authorized for tool '{tool_name}'"}

    # 3. Route to the correct tool function
    tool_functions: dict[str, Any] = {
        "safe_shell": lambda: safe_shell(kwargs.get("command", ""), agent_id),
        "file_reader": lambda: file_reader(kwargs.get("file_path", ""), agent_id),
        "doc_updater": lambda: doc_updater(
            target=kwargs.get("target", ""),
            content=kwargs.get("content", ""),
            agent_id=agent_id,
            reason=kwargs.get("reason", ""),
            impacted_subsystems=kwargs.get("impacted_subsystems"),
        ),
        "system_info": lambda: system_info(agent_id),
        # New tools
        "webhook_send": lambda: webhook_send(
            url=kwargs.get("url", ""),
            payload=kwargs.get("payload", {}),
            agent_id=agent_id,
        ),
        "git_ops": lambda: git_ops(kwargs.get("subcommand", "status"), agent_id),
        "health_check": lambda: health_check(kwargs.get("url", ""), agent_id),
        "log_tail": lambda: log_tail(
            file_path=kwargs.get("file_path", ""),
            lines=int(kwargs.get("lines", 50)),
            agent_id=agent_id,
        ),
        "alert_dispatch": lambda: alert_dispatch(
            level=kwargs.get("level", "INFO"),
            title=kwargs.get("title", ""),
            message=kwargs.get("message", ""),
            agent_id=agent_id,
        ),
        "secret_scanner": lambda: secret_scanner(kwargs.get("target_path", "."), agent_id),
        "db_query": lambda: db_query(
            db_path=kwargs.get("db_path", ""),
            query=kwargs.get("query", ""),
            agent_id=agent_id,
        ),
        "process_restart": lambda: process_restart(kwargs.get("process_name", ""), agent_id),
        "folder_analyzer": lambda: folder_analyzer(
            folder_path=kwargs.get("folder_path", "."),
            agent_id=agent_id,
            max_files=int(kwargs.get("max_files", 200)),
            snippet_lines=int(kwargs.get("snippet_lines", 30)),
            include_content=str(kwargs.get("include_content", "true")).lower() != "false",
        ),
        "document_ocr": lambda: document_ocr(
            file_path=kwargs.get("file_path", ""),
            agent_id=agent_id,
        ),
        "k8s_control": lambda: k8s_control(
            action=kwargs.get("action", ""),
            agent_id=agent_id,
            job_name=kwargs.get("job_name", ""),
            image=kwargs.get("image", ""),
            command=kwargs.get("command", ""),
            namespace=kwargs.get("namespace", "agent-ops"),
        ),
        "browser_control": lambda: browser_control(
            action=kwargs.get("action", ""),
            agent_id=agent_id,
            url=kwargs.get("url", ""),
            selector=kwargs.get("selector", ""),
            value=kwargs.get("value", ""),
            field_name=kwargs.get("field_name", "value"),
            option_value=kwargs.get("option_value", ""),
            expression=kwargs.get("expression", ""),
            timeout_ms=kwargs.get("timeout_ms", 10000),
        ),
    }

    tool_fn = tool_functions.get(tool_name)

    # Browser tools — routed through BrowserSessionRegistry (Sprint 4)
    if tool_name.startswith("browser_"):
        from backend.browser.tooling import (
            browser_click,
            browser_close,
            browser_open,
            browser_screenshot,
            browser_select,
            browser_snapshot,
            browser_type,
            browser_upload,
        )

        _browser_map: dict[str, Any] = {
            "browser_open": lambda: browser_open(url=kwargs.get("url", ""), agent_id=agent_id),
            "browser_click": lambda: browser_click(selector=kwargs.get("selector", ""), agent_id=agent_id),
            "browser_type": lambda: browser_type(
                selector=kwargs.get("selector", ""), text=kwargs.get("text", ""), agent_id=agent_id
            ),
            "browser_select": lambda: browser_select(
                selector=kwargs.get("selector", ""), value=kwargs.get("value", ""), agent_id=agent_id
            ),
            "browser_snapshot": lambda: browser_snapshot(agent_id=agent_id),
            "browser_screenshot": lambda: browser_screenshot(path=kwargs.get("path", ""), agent_id=agent_id),
            "browser_upload": lambda: browser_upload(
                selector=kwargs.get("selector", ""), file_path=kwargs.get("file_path", ""), agent_id=agent_id
            ),
            "browser_close": lambda: browser_close(agent_id=agent_id),
        }
        tool_fn = _browser_map.get(tool_name)

    # Higgsfield tools — forwarded to higgsfield_playwright_server on port 8812
    if tool_name.startswith("hf_"):
        import httpx

        from backend.config import HF_MCP_PORT  # type: ignore[attr-defined]

        _hf_endpoint = f"http://127.0.0.1:{HF_MCP_PORT}/tools/{tool_name}"
        _hf_body = {k: v for k, v in kwargs.items() if k not in ("agent_id", "allowed_tools")}

        async def _hf_call(
            _url: str = _hf_endpoint,
            _body: dict[str, Any] = _hf_body,
        ) -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=960) as client:
                resp = await client.post(_url, json=_body)
                return resp.json()

        tool_fn = _hf_call

    # MCP Gateway tools — route through MCPBridge
    if tool_name.startswith("mcp_"):
        bridge = get_mcp_bridge()
        # Strip non-serialisable kwargs keys
        mcp_args = {k: v for k, v in kwargs.items() if k not in ("agent_id", "allowed_tools")}

        def tool_fn():
            return bridge.call_tool(tool_name, agent_id, mcp_args)

    # Sandbox exec — route through SandboxSession.exec_in_container (Sprint 8)
    if tool_name == "sandbox_exec":
        from backend.config import PROJECT_ROOT
        from sandbox.session_manager import SandboxSession

        _session_id: str = str(kwargs.get("session_id") or "")
        _command: list[str] = list(kwargs.get("command") or [])
        _timeout: int = int(kwargs.get("timeout") or 30)
        if not _session_id:

            async def _err_sid() -> dict[str, Any]:
                return {"error": "sandbox_exec requires 'session_id'"}

            tool_fn = _err_sid
        elif not _command:

            async def _err_cmd() -> dict[str, Any]:
                return {"error": "sandbox_exec requires 'command' (non-empty list)"}

            tool_fn = _err_cmd
        else:
            _sandbox = SandboxSession(
                project_root=PROJECT_ROOT,
                task="exec",
                model="",
                session_id=_session_id,
            )

            async def _sandbox_exec_inner(
                _sb: Any = _sandbox,
                _cmd: list[str] = _command,
                _to: int = _timeout,
            ) -> dict[str, Any]:
                return _sb.exec_in_container(command=_cmd, timeout=_to)

            tool_fn = _sandbox_exec_inner

    if tool_fn is None:
        return {"error": f"Tool '{tool_name}' registered but not implemented"}

    # 4. Execute through DriftGuard middleware
    result = await drift_guard.guard_tool_execution(
        tool_name=tool_name,
        agent_id=agent_id,
        modification_type=tool_def.modification_type,
        tool_fn=tool_fn,
    )

    return result
