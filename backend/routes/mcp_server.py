"""
MCP Server — Model Context Protocol over SSE for VS Code Copilot.
=================================================================
Exposes Agentop's local agents as MCP tools that VS Code GitHub Copilot
can call directly. Copilot acts as the manager/judge; local Ollama agents
do the generation grunt work; Copilot grades results and retries on failure.

Transport: SSE (Server-Sent Events) + JSON-RPC 2.0
Protocol:  MCP 2024-11-05

Endpoints:
  GET  /mcp/sse              — SSE stream (Copilot subscribes here)
  POST /mcp/messages         — JSON-RPC inbound (session-keyed)

Tools exposed:
  agentop_chat              — Route message to any Agentop agent
  agentop_webgen            — Generate a website via WebGenPipeline
  agentop_content_draft     — Draft a content script (TikTok/IG/YT)
  agentop_security_scan     — Run secret + vulnerability scan on a path
  agentop_research          — Search the knowledge vector store

Wire-up (server.py):
    from backend.routes.mcp_server import router as mcp_router, set_orchestrator as set_mcp_orchestrator
    set_mcp_orchestrator(_orchestrator)
    app.include_router(mcp_router)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger("agentop.mcp")

router = APIRouter(prefix="/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# Orchestrator reference (set by server.py after init)
# ---------------------------------------------------------------------------

_orchestrator: Any = None


def set_orchestrator(orch: Any) -> None:
    global _orchestrator
    _orchestrator = orch


# ---------------------------------------------------------------------------
# Session store — one asyncio.Queue per connected SSE client
# ---------------------------------------------------------------------------

_sessions: dict[str, asyncio.Queue[str | None]] = {}


# ---------------------------------------------------------------------------
# MCP Tool Definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "agentop_chat",
        "description": (
            "Send a message to an Agentop local agent running on Ollama. "
            "Use this for: research, code review, devops tasks, security checks, "
            "knowledge lookups, and anything a specialist agent can handle locally. "
            "Saves Copilot tokens — Ollama does the work for free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The instruction or question to send",
                },
                "agent_id": {
                    "type": "string",
                    "description": (
                        "Target agent. Use 'auto' for automatic routing. "
                        "Options: soul_core, devops_agent, monitor_agent, "
                        "security_agent, code_review_agent, knowledge_agent, "
                        "data_agent, comms_agent, cs_agent, it_agent"
                    ),
                    "default": "auto",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "agentop_webgen",
        "description": (
            "Generate a complete website using the local WebGen pipeline. "
            "Runs: SitePlanner → PageGenerator → SEO → AEO → QA. "
            "Returns project ID and output path. Long-running (30-120s). "
            "Use for: building client sites, portfolio pages, landing pages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string", "description": "Name of the business"},
                "business_type": {
                    "type": "string",
                    "description": "Type: restaurant, saas, portfolio, ecommerce, agency, medical, custom",
                    "default": "custom",
                },
                "description": {"type": "string", "description": "Brief description of the business"},
                "services": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of services or features to highlight",
                },
                "tone": {
                    "type": "string",
                    "description": "Brand tone: professional, playful, bold, minimal, luxury",
                    "default": "professional",
                },
                "target_audience": {"type": "string", "description": "Who the site is for"},
            },
            "required": ["business_name"],
        },
    },
    {
        "name": "agentop_content_draft",
        "description": (
            "Draft a content script using local Ollama. "
            "Produces: hook, body, CTA, caption, hashtags. "
            "Optimised per platform (TikTok hook in 3s, LinkedIn insight-led, etc.). "
            "Use before expensive video generation to validate the concept first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What the content is about"},
                "platform": {
                    "type": "string",
                    "description": "Target platform: tiktok, instagram_reels, youtube_shorts, linkedin, twitter",
                    "default": "tiktok",
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "Target video duration in seconds",
                    "default": 30,
                },
                "style": {
                    "type": "string",
                    "description": "Content style: educational, entertaining, documentary, testimonial, demo",
                    "default": "educational",
                },
                "brand_voice": {
                    "type": "string",
                    "description": "Optional: describe the creator's voice/persona",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "agentop_security_scan",
        "description": (
            "Run a security scan on a file or directory using Agentop's secret scanner. "
            "Detects: API keys, tokens, passwords, private keys in 8 pattern categories. "
            "Use before any commit, deploy, or PR that touches config or env files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to scan (file or directory)",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Scan subdirectories recursively",
                    "default": True,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "agentop_research",
        "description": (
            "Search Agentop's local knowledge vector store. "
            "Contains: architecture docs, skill packs, domain knowledge, agent patterns. "
            "Use for: answering questions about the system, finding relevant patterns, "
            "checking documented decisions before making changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Executors
# ---------------------------------------------------------------------------


async def _exec_chat(args: dict) -> str:
    if not _orchestrator:
        return "Orchestrator not available — backend is starting up."
    message = args.get("message", "")
    agent_id = args.get("agent_id", "auto")
    if agent_id == "auto":
        from backend.orchestrator.lex_router import resolve_agent

        routing = await resolve_agent(message)
        agent_id = routing.get("agent_id", "soul_core")
    try:
        result = await asyncio.wait_for(
            _orchestrator.process_message(agent_id=agent_id, message=message),
            timeout=60.0,
        )
        return result.get("response", str(result))
    except TimeoutError:
        return f"Agent {agent_id} timed out after 60s."
    except Exception as exc:
        return f"Agent error: {exc}"


async def _exec_webgen(args: dict) -> str:
    try:
        from backend.llm import OllamaClient
        from backend.webgen.models import BusinessType, ClientBrief
        from backend.webgen.pipeline import WebGenPipeline

        brief = ClientBrief(
            business_name=args["business_name"],
            business_type=BusinessType(args.get("business_type", "custom")),
            tagline="",
            description=args.get("description", ""),
            services=args.get("services", []),
            target_audience=args.get("target_audience", ""),
            tone=args.get("tone", "professional"),
        )
        pipeline = WebGenPipeline(llm=OllamaClient())
        project = await asyncio.wait_for(
            pipeline.quick_generate(brief, export=True),
            timeout=180.0,
        )
        pages = [p.slug for p in project.pages]
        ux_scores = project.metadata.get("ux_scores", {})
        avg_ux = round(sum(ux_scores.values()) / len(ux_scores), 1) if ux_scores else 0
        return (
            f"WebGen complete.\n"
            f"Project ID: {project.id}\n"
            f"Output: {project.output_dir}\n"
            f"Pages: {', '.join(pages)}\n"
            f"Avg UX score: {avg_ux}/100\n"
            f"Status: {project.status.value}\n"
            f"To publish: use the Vercel publish button in the Agentop dashboard."
        )
    except TimeoutError:
        return "WebGen timed out after 180s. Check backend/logs/system.jsonl for progress."
    except Exception as exc:
        return f"WebGen error: {exc}"


async def _exec_content_draft(args: dict) -> str:
    topic = args.get("topic", "")
    platform = args.get("platform", "tiktok")
    duration = args.get("duration_seconds", 30)
    style = args.get("style", "educational")
    brand_voice = args.get("brand_voice", "conversational and direct")

    platform_rules = {
        "tiktok": f"9:16 vertical, {duration}s max, hook MUST stop scroll in first 2s, captions mandatory, creator voice",
        "instagram_reels": f"9:16 vertical, {duration}s, trending audio cue, text overlays, strong CTA",
        "youtube_shorts": f"9:16 vertical, {duration}s, story arc with subscribe CTA, face optional",
        "linkedin": f"16:9, {duration}s, insight-led opening, professional tone, no flashy effects",
        "twitter": f"16:9, {duration}s, punchy, opinion-driven, single key insight",
    }
    rules = platform_rules.get(platform, platform_rules["tiktok"])

    prompt = (
        f"Write a {style} content script about: {topic}\n\n"
        f"Platform rules: {rules}\n"
        f"Brand voice: {brand_voice}\n\n"
        f"Format your response as:\n"
        f"HOOK (first 3 seconds): [text]\n"
        f"BODY: [script broken into 5-second segments]\n"
        f"CTA: [call to action]\n"
        f"CAPTION: [full post caption]\n"
        f"HASHTAGS: [5-8 relevant hashtags]\n\n"
        f"Rules:\n"
        f"- Never start with 'Welcome to' or 'Hello everyone'\n"
        f"- Hook must be a pattern interrupt — question, bold claim, or unexpected fact\n"
        f"- Total word count must fit {duration}s at natural speaking pace (~130 words/min)\n"
        f"- One clear idea only — no listicles unless the format demands it"
    )

    if not _orchestrator:
        return "Orchestrator not available."
    try:
        result = await asyncio.wait_for(
            _orchestrator.process_message(agent_id="soul_core", message=prompt),
            timeout=45.0,
        )
        return result.get("response", "No response generated.")
    except TimeoutError:
        return "Content draft timed out. Try a shorter duration or simpler topic."
    except Exception as exc:
        return f"Content draft error: {exc}"


async def _exec_security_scan(args: dict) -> str:
    from backend.tools import execute_tool

    path = args.get("path", ".")
    try:
        result = await execute_tool(
            "secret_scanner",
            "security_agent",
            ["secret_scanner"],
            path=path,
            recursive=args.get("recursive", True),
        )
        findings = result.get("findings", [])
        if not findings:
            return f"Security scan of '{path}': No secrets detected. Clean."
        lines = [f"Security scan of '{path}': {len(findings)} finding(s) detected.\n"]
        for f in findings[:20]:
            lines.append(
                f"  [{f.get('severity', 'UNKNOWN')}] {f.get('file', '?')}:{f.get('line', '?')} — {f.get('pattern', '?')}"
            )
        if len(findings) > 20:
            lines.append(f"  ... and {len(findings) - 20} more. Run full scan for complete list.")
        return "\n".join(lines)
    except Exception as exc:
        return f"Security scan error: {exc}"


async def _exec_research(args: dict) -> str:
    query = args.get("query", "")
    limit = args.get("limit", 5)
    if not _orchestrator:
        return "Orchestrator not available."
    prompt = f"Search the knowledge base and answer: {query}\nReturn the top {limit} most relevant findings with source context."
    try:
        result = await asyncio.wait_for(
            _orchestrator.process_message(agent_id="knowledge_agent", message=prompt),
            timeout=30.0,
        )
        return result.get("response", "No knowledge found.")
    except TimeoutError:
        return "Research timed out after 30s."
    except Exception as exc:
        return f"Research error: {exc}"


_TOOL_EXECUTORS = {
    "agentop_chat": _exec_chat,
    "agentop_webgen": _exec_webgen,
    "agentop_content_draft": _exec_content_draft,
    "agentop_security_scan": _exec_security_scan,
    "agentop_research": _exec_research,
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Handler
# ---------------------------------------------------------------------------


async def _handle_jsonrpc(payload: dict, session_id: str) -> dict | None:
    """Process one JSON-RPC 2.0 message. Returns response dict or None for notifications."""
    method = payload.get("method", "")
    req_id = payload.get("id")
    params = payload.get("params", {})

    def ok(result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    # Notifications (no id) — no response needed
    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return ok(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentop-mcp", "version": "1.0.0"},
            }
        )

    if method == "tools/list":
        return ok({"tools": TOOL_DEFINITIONS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        executor = _TOOL_EXECUTORS.get(tool_name)
        if not executor:
            return err(-32601, f"Unknown tool: {tool_name}")
        try:
            text = await executor(tool_args)
            return ok(
                {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                }
            )
        except Exception as exc:
            return ok(
                {
                    "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                    "isError": True,
                }
            )

    if method == "ping":
        return ok({})

    return err(-32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# SSE Generator
# ---------------------------------------------------------------------------


async def _sse_generator(session_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE events for a connected Copilot client."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    _sessions[session_id] = queue

    # First event: tell client where to POST messages
    endpoint_url = f"/mcp/messages?sessionId={session_id}"
    yield f"event: endpoint\ndata: {endpoint_url}\n\n"
    logger.info(f"[MCP] Session opened: {session_id}")

    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                if msg is None:
                    break
                yield f"event: message\ndata: {msg}\n\n"
            except TimeoutError:
                # Keep-alive ping
                yield ": ping\n\n"
    finally:
        _sessions.pop(session_id, None)
        logger.info(f"[MCP] Session closed: {session_id}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/sse")
async def mcp_sse(request: Request) -> StreamingResponse:
    """SSE endpoint — VS Code Copilot connects here."""
    session_id = str(uuid.uuid4())[:12]
    return StreamingResponse(
        _sse_generator(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/messages")
async def mcp_messages(request: Request) -> dict:
    """JSON-RPC inbound — Copilot posts tool calls here."""
    session_id = request.query_params.get("sessionId", "")
    queue = _sessions.get(session_id)

    try:
        payload = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    # Handle batch requests
    if isinstance(payload, list):
        responses = []
        for item in payload:
            resp = await _handle_jsonrpc(item, session_id)
            if resp is not None:
                responses.append(resp)
        if queue and responses:
            for r in responses:
                await queue.put(json.dumps(r))
        return {"batch": True}

    response = await _handle_jsonrpc(payload, session_id)

    if response is not None and queue:
        await queue.put(json.dumps(response))

    return response or {}


@router.get("/health")
async def mcp_health() -> dict:
    """Health check — confirms MCP server is reachable."""
    return {
        "status": "ok",
        "protocol": "MCP 2024-11-05",
        "transport": "SSE",
        "tools": [t["name"] for t in TOOL_DEFINITIONS],
        "active_sessions": len(_sessions),
        "orchestrator_ready": _orchestrator is not None,
    }
