"""
FastAPI Server — Main application entry point.
===============================================
Provides REST API for:
- Agent message processing
- System status & dashboard data
- Drift monitoring
- Agent and tool information

All routes serve the Next.js dashboard and are CORS-enabled for local dev.
The dashboard is READ-ONLY (INV-8) — it cannot mutate backend state
except through sanctioned message endpoints.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from backend.config import (
    BACKEND_HOST, BACKEND_PORT, OLLAMA_MODEL,
    API_SECRET, MAX_CHAT_MESSAGE_LENGTH, RATE_LIMIT_RPM,
)
from backend.llm import OllamaClient
from backend.memory import memory_store
from backend.middleware import drift_guard
from backend.models import (
    CampaignGenerateRequest,
    CampaignGenerateResponse,
    ChatRequest,
    ChatResponse,
    DriftReport,
    DriftStatus,
    IntakeAnswerRequest,
    IntakeStartRequest,
    IntakeStartResponse,
    IntakeStatusResponse,
    SystemStatus,
)
from backend.mcp import mcp_bridge
from backend.orchestrator import AgentOrchestrator
from backend.tasks import task_tracker
from backend.tools import execute_tool, get_tool_definitions
from backend.utils import logger
from backend.config import PROJECT_ROOT, LLM_MONTHLY_BUDGET


# ---------------------------------------------------------------------------
# Application State (module-level singletons)
# ---------------------------------------------------------------------------

_start_time: float = 0.0
_orchestrator: AgentOrchestrator | None = None
_llm_client: OllamaClient | None = None


# ---------------------------------------------------------------------------
# Security: Bearer-token auth + rate limiting
# ---------------------------------------------------------------------------

# Simple in-memory rate limiter (per-IP, sliding window)
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _rate_limit(request: Request) -> None:
    """Enforce per-IP rate limiting if RATE_LIMIT_RPM > 0."""
    if RATE_LIMIT_RPM <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _rate_buckets[ip]
    # Purge entries older than 60 s
    _rate_buckets[ip] = [t for t in window if now - t < 60]
    if len(_rate_buckets[ip]) >= RATE_LIMIT_RPM:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_buckets[ip].append(now)


async def _verify_auth(request: Request) -> None:
    """
    Verify Bearer token when API_SECRET is configured.
    If API_SECRET is empty, authentication is disabled (dev mode).
    """
    if not API_SECRET:
        return  # auth disabled
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Lifespan Management
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.
    Initializes LLM client, orchestrator, and governance checks on startup.
    Cleans up resources on shutdown.
    """
    global _start_time, _orchestrator, _llm_client

    _start_time = time.time()

    # Initialize LLM client
    _llm_client = OllamaClient()
    logger.info(f"LLM client initialized: model={OLLAMA_MODEL}")

    # Check Ollama availability
    if await _llm_client.is_available():
        models = await _llm_client.list_models()
        logger.info(f"Ollama connected. Available models: {models}")
    else:
        logger.warning(
            "Ollama not available at startup. "
            "Ensure 'ollama serve' is running. Agents will fail on LLM calls."
        )

    # Initialize orchestrator with LangGraph state machine
    _orchestrator = AgentOrchestrator(_llm_client)
    logger.info("Orchestrator initialized with all registered agents")

    # Boot the Soul Agent — loads identity, goals, and reflection history
    soul_boot = await _orchestrator.boot_soul()
    logger.info(f"Soul boot: {soul_boot}")

    # Run initial drift check
    drift_report = drift_guard.check_invariants()
    logger.info(f"Initial drift status: {drift_report.status.value}")

    logger.info(f"Agentop backend started on {BACKEND_HOST}:{BACKEND_PORT}")

    # Initialise MCP Gateway bridge (non-fatal if docker CLI absent)
    await mcp_bridge.initialise()
    mcp_status = mcp_bridge.get_status()
    logger.info(f"MCP Gateway: enabled={mcp_status['enabled']}, cli={mcp_status['cli_available']}, tools={mcp_status['discovered_tools']}/{mcp_status['declared_tool_count']}")

    yield  # Application runs here

    # Shutdown
    await mcp_bridge.shutdown()
    if _llm_client:
        await _llm_client.close()
    logger.info("Agentop backend shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agentop — Local Multi-Agent Control Center",
    description=(
        "Production-grade local-first multi-agent system with "
        "architectural drift governance, namespaced memory, and tool safety."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for local Next.js dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3007", "http://127.0.0.1:3007"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Security Middleware (rate limiting + auth)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Apply rate limiting and auth to every request (except /health and /docs)."""
    path = request.url.path
    # Skip auth for health check and OpenAPI docs
    skip_auth_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
    if path not in skip_auth_paths:
        _rate_limit(request)
        await _verify_auth(request)
    response = await call_next(request)
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Health & Status Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Basic health check endpoint."""
    llm_available = await _llm_client.is_available() if _llm_client else False
    return {
        "status": "healthy",
        "llm_available": llm_available,
        "drift_status": drift_guard.drift_status.value,
        "uptime_seconds": round(time.time() - _start_time, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/status", response_model=SystemStatus)
async def system_status() -> SystemStatus:
    """
    Full system status for the dashboard.
    Returns agents, drift report, recent logs.
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    return SystemStatus(
        agents=_orchestrator.get_agent_states(),
        drift_report=_orchestrator.get_drift_report(),
        recent_logs=logger.get_recent_tool_logs(50),
        total_tool_executions=len(logger.get_recent_tool_logs(10000)),
        uptime_seconds=round(time.time() - _start_time, 2),
    )


# ---------------------------------------------------------------------------
# Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Send a message to an agent through the orchestrator.

    The message flows through:
    1. Orchestrator router
    2. Target agent processing
    3. Governance check
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    # Input validation
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(request.message) > MAX_CHAT_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Message too long ({len(request.message)} bytes, max {MAX_CHAT_MESSAGE_LENGTH})",
        )

    result = await _orchestrator.process_message(
        agent_id=request.agent_id,
        message=request.message,
        context=request.context,
    )

    if result.get("error") and not result.get("response"):
        raise HTTPException(status_code=400, detail=result["error"])

    return ChatResponse(
        agent_id=request.agent_id,
        message=result.get("response", ""),
        drift_status=DriftStatus(result.get("drift_status", "GREEN")),
        timestamp=datetime.utcnow(),
    )


@app.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    """Return all registered agents for the dashboard."""
    if not _orchestrator:
        return []
    return [d.model_dump() for d in _orchestrator.get_all_agent_definitions()]


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    """Return a specific agent's definition and state."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    all_defs = {d.agent_id: d for d in _orchestrator.get_all_agent_definitions()}
    definition = all_defs.get(agent_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    all_states = {s.agent_id: s for s in _orchestrator.get_agent_states()}
    state = all_states.get(agent_id)
    return {
        "definition": definition.model_dump(),
        "state": state.model_dump() if state else None,
    }


@app.post("/intake/start", response_model=IntakeStartResponse)
async def intake_start(request: IntakeStartRequest) -> IntakeStartResponse:
    """Start or resume the structured business intake interview."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    state = await _orchestrator.start_intake(request.business_id)
    return IntakeStartResponse(**state)


@app.post("/intake/answer", response_model=IntakeStatusResponse)
async def intake_answer(request: IntakeAnswerRequest) -> IntakeStatusResponse:
    """Submit one intake answer and return updated progress/next question."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    status = await _orchestrator.submit_intake_answer(
        business_id=request.business_id,
        answer=request.answer,
    )
    return IntakeStatusResponse(**status)


@app.get("/intake/{business_id}", response_model=IntakeStatusResponse)
async def intake_status(business_id: str) -> IntakeStatusResponse:
    """Get current intake progress and collected answers for a business."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    status = _orchestrator.get_intake_status(business_id)
    return IntakeStatusResponse(**status)


@app.post("/campaign/generate", response_model=CampaignGenerateResponse)
async def campaign_generate(request: CampaignGenerateRequest) -> CampaignGenerateResponse:
    """Generate a campaign payload using completed intake + semantic business context."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    try:
        result = await _orchestrator.generate_campaign(
            business_id=request.business_id,
            platform=request.platform,
            objective=request.objective,
            format_type=request.format_type,
            duration_seconds=request.duration_seconds,
        )
        return CampaignGenerateResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Tool Endpoints
# ---------------------------------------------------------------------------

@app.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    """Return all registered tool definitions."""
    tools = get_tool_definitions()
    return [t.model_dump() for t in tools]


@app.post("/tools/{tool_name}")
async def run_tool(
    tool_name: str,
    body: dict[str, Any] | None = None,
    agent_id: str = "system",
) -> dict[str, Any]:
    """
    Execute a named tool directly.

    Security note: This endpoint is gated by API_SECRET auth.
    It enforces the same permission checks as agent execution —
    system user gets a restricted toolset (read-only tools only).
    """
    # System user is restricted to read-only tools for safety
    SYSTEM_ALLOWED_TOOLS = [
        "file_reader", "system_info", "git_ops", "health_check",
        "log_tail", "secret_scanner", "db_query", "folder_analyzer",
    ]
    kwargs = body or {}
    result = await execute_tool(
        tool_name, agent_id=agent_id, allowed_tools=SYSTEM_ALLOWED_TOOLS, **kwargs
    )
    return result if isinstance(result, dict) else {"result": result}


@app.get("/mcp/status")
async def mcp_status() -> dict[str, Any]:
    """Return MCP Gateway bridge availability and discovered tool count."""
    return mcp_bridge.get_status()


# ---------------------------------------------------------------------------
# Folder Analysis Endpoints
# ---------------------------------------------------------------------------

@app.get("/folders/browse")
async def browse_folders(path: str = ".") -> dict[str, Any]:
    """
    Browse the project directory tree — returns immediate children (dirs + files).
    The dashboard uses this for the folder picker UI.
    Only browsable within PROJECT_ROOT.
    """
    from pathlib import Path as _Path
    raw = _Path(path)
    target = raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()

    if not str(target).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied: outside project directory")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    _skip = {".git", "__pycache__", "node_modules", ".next", "dist", "build", "venv", ".venv"}
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if child.name in _skip:
                continue
            if child.name.startswith(".") and child.name not in {".env.example", ".gitignore"}:
                continue
            entries.append({
                "name": child.name,
                "is_dir": child.is_dir(),
                "size_bytes": child.stat().st_size if child.is_file() else None,
                "path": str(child.relative_to(PROJECT_ROOT)),
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {
        "current": str(target.relative_to(PROJECT_ROOT)) if target != PROJECT_ROOT else ".",
        "parent": str(target.parent.relative_to(PROJECT_ROOT)) if target != PROJECT_ROOT else None,
        "entries": entries,
    }


@app.post("/folders/analyze")
async def analyze_folder(body: dict[str, Any]) -> dict[str, Any]:
    """
    Analyse a folder using the folder_analyzer tool and optionally
    dispatch results to a specific agent for further processing.

    Body:
        folder_path: str — Path relative to project root
        agent_id: str (optional) — Agent to process the analysis
        max_files: int (optional, default 200)
        include_content: bool (optional, default true)
    """
    folder_path = body.get("folder_path", ".")
    agent_id = body.get("agent_id")
    max_files = int(body.get("max_files", 200))
    include_content = body.get("include_content", True)

    # Run the folder analyzer tool
    from backend.tools import folder_analyzer as _fa
    analysis = await _fa(
        folder_path=folder_path,
        agent_id=agent_id or "system",
        max_files=max_files,
        include_content=include_content,
    )

    if analysis.get("error"):
        raise HTTPException(status_code=400, detail=analysis["error"])

    result: dict[str, Any] = {"analysis": analysis}

    # Optionally dispatch to an agent for processing
    if agent_id and _orchestrator:
        summary = (
            f"Folder analysis of '{folder_path}': "
            f"{analysis.get('file_count', 0)} files, {analysis.get('dir_count', 0)} dirs, "
            f"{analysis.get('total_size_mb', 0)} MB. "
            f"Extensions: {analysis.get('extension_summary', {})}. "
            f"Please analyse this codebase and provide insights."
        )
        # Truncate file details for the prompt
        file_summaries = "\n".join(
            f"- {f['path']} ({f['size_bytes']} bytes, {f.get('line_count', '?')} lines)"
            for f in analysis.get("files", [])[:50]
        )
        full_prompt = f"{summary}\n\nFiles:\n{file_summaries}"
        agent_result = await _orchestrator.process_message(
            agent_id=agent_id,
            message=full_prompt[:MAX_CHAT_MESSAGE_LENGTH],
        )
        result["agent_response"] = agent_result.get("response", "")

    return result


# ---------------------------------------------------------------------------
# Task Activity Endpoints
# ---------------------------------------------------------------------------

@app.get("/tasks")
async def list_tasks(limit: int = 50, status: str | None = None) -> dict[str, Any]:
    """Return recent tasks for the Task Activity Panel."""
    tasks = task_tracker.get_tasks(limit=limit, status=status)
    stats = task_tracker.get_stats()
    return {"tasks": tasks, "stats": stats}


# ---------------------------------------------------------------------------
# Live Activity Stream (Server-Sent Events)
# ---------------------------------------------------------------------------

@app.get("/stream/activity")
async def stream_activity():
    """
    SSE endpoint for real-time agent activity.

    The dashboard connects via EventSource and receives events as they happen:
    - task_created / task_started / task_completed / task_failed
    - tool_start / tool_end
    - llm_response
    - agent_active / agent_idle

    Events are formatted as standard SSE (event: <type>\ndata: <json>\n\n).
    A heartbeat ping is sent every 15 seconds to keep the connection alive.
    """
    queue = task_tracker.subscribe()

    async def event_generator():
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {{\"status\": \"ok\", \"timestamp\": \"{datetime.utcnow().isoformat()}\"}}\n\n"
            while True:
                try:
                    # Wait for next event with timeout for heartbeat
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"event: heartbeat\ndata: {{\"timestamp\": \"{datetime.utcnow().isoformat()}\"}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            task_tracker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# LLM Model Knowledge Endpoints
# ---------------------------------------------------------------------------

@app.get("/models")
async def list_models() -> dict[str, Any]:
    """Return the full LLM model knowledge base."""
    from backend.knowledge.llm_models import (
        get_model_knowledge,
        RECOMMENDED_AGENT_MODELS,
    )
    models = get_model_knowledge()
    # Also check which models are actually available in Ollama right now
    available: list[str] = []
    if _llm_client:
        try:
            available = await _llm_client.list_models()
        except Exception:
            pass
    return {
        "models": models,
        "available_locally": available,
        "total_known": len(models),
        "agent_recommendations": RECOMMENDED_AGENT_MODELS,
    }


@app.get("/models/recommend/{agent_id}")
async def recommend_model(agent_id: str) -> dict[str, Any]:
    """Return recommended models for a specific agent."""
    from backend.knowledge.llm_models import get_agent_model_recommendation
    recs = get_agent_model_recommendation(agent_id)
    return {"agent_id": agent_id, "recommendations": recs}


@app.get("/models/{model_id:path}")
async def get_model(model_id: str) -> dict[str, Any]:
    """Return details for a specific model."""
    from backend.knowledge.llm_models import get_model_by_id
    model = get_model_by_id(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not in knowledge base")
    return model


@app.post("/knowledge/reindex")
async def knowledge_reindex() -> dict[str, Any]:
    """Force rebuild of the local knowledge vector index."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    result = await _orchestrator.reindex_knowledge()
    return {
        "success": True,
        "message": "Knowledge index rebuilt",
        **result,
    }


# ---------------------------------------------------------------------------
# LLM Token Usage & Capacity Endpoints
# ---------------------------------------------------------------------------

@app.get("/llm/stats")
async def llm_stats() -> dict[str, Any]:
    """
    Return LLM token usage stats, cost tracking, and routing breakdown.
    Draws from the LLMRouter's RouterStats if available, otherwise
    provides estimated stats from the local OllamaClient.
    """
    from lib.localllm.router import LLMRouter

    # Try to get stats from the router.
    # The router lives on HybridClient._router or on _llm_client._router
    # depending on how the system was initialized.
    router_stats: dict[str, Any] = {
        "total_requests": 0,
        "local_requests": 0,
        "cloud_requests": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "avg_latency_ms": 0.0,
        "cost_per_request_avg": 0.0,
    }
    cost_log: list[dict[str, Any]] = []
    budget_remaining = LLM_MONTHLY_BUDGET

    # Look for a router on the llm_client (HybridClient) or orchestrator
    router_obj: LLMRouter | None = None
    if _llm_client and hasattr(_llm_client, "router"):
        router_obj = getattr(_llm_client, "router", None)
    elif _llm_client and hasattr(_llm_client, "_router"):
        router_obj = getattr(_llm_client, "_router", None)
    elif _orchestrator and hasattr(_orchestrator, "llm_client"):
        inner = getattr(_orchestrator, "llm_client", None)
        if inner and hasattr(inner, "router"):
            router_obj = getattr(inner, "router", None)

    if router_obj is not None:
        try:
            router_stats = router_obj.get_stats()
            cost_log = router_obj.get_cost_log(50)
            spent = router_stats.get("estimated_cost_usd", 0)
            budget_remaining = round(LLM_MONTHLY_BUDGET - spent, 2)
        except Exception:
            pass

    return {
        "stats": router_stats,
        "cost_log": cost_log,
        "budget": {
            "monthly_limit_usd": LLM_MONTHLY_BUDGET,
            "spent_usd": router_stats.get("estimated_cost_usd", 0),
            "remaining_usd": budget_remaining,
            "percent_used": round(
                (router_stats.get("estimated_cost_usd", 0) / max(LLM_MONTHLY_BUDGET, 0.01)) * 100, 1
            ),
        },
        "tokens": {
            "total_in": router_stats.get("tokens_in", 0),
            "total_out": router_stats.get("tokens_out", 0),
            "total": router_stats.get("tokens_in", 0) + router_stats.get("tokens_out", 0),
        },
    }


@app.get("/llm/capacity")
async def llm_capacity() -> dict[str, Any]:
    """
    Return LLM capacity info: available models, VRAM estimates,
    context window sizes, and throughput estimates.
    Includes both local (Ollama) and cloud (OpenRouter) models.
    """
    from lib.localllm.models import MODELS
    from lib.localllm.cloud_client import CLOUD_MODELS

    available: list[str] = []
    if _llm_client:
        try:
            available = await _llm_client.list_models()
        except Exception:
            pass

    model_capacities = []

    # ── Local Ollama models ───────────────────────────────
    for model_id, profile in MODELS.items():
        is_available = any(model_id in m for m in available)
        # Derive speed/quality tier from parameter count
        param_str = profile.parameters.upper().replace("B", "")
        try:
            param_val = float(param_str)
        except ValueError:
            param_val = 7.0
        if param_val <= 3:
            speed_tier, quality_tier = "fast", "basic"
        elif param_val <= 8:
            speed_tier, quality_tier = "medium", "good"
        elif param_val <= 14:
            speed_tier, quality_tier = "slow", "high"
        else:
            speed_tier, quality_tier = "very_slow", "premium"
        # Estimate tokens per second based on speed tier
        tps_estimates = {"fast": 40, "medium": 25, "slow": 15, "very_slow": 8}
        est_tps = tps_estimates.get(speed_tier, 20)

        model_capacities.append({
            "model_id": model_id,
            "family": profile.family,
            "parameters": profile.parameters,
            "vram_gb": profile.vram_gb,
            "context_window": profile.context_window,
            "speed_tier": speed_tier,
            "quality_tier": quality_tier,
            "available": is_available,
            "estimated_tokens_per_second": est_tps,
            "best_for": profile.best_for,
            "provider": "local",
        })

    # ── Cloud models (OpenRouter) ─────────────────────────────────────
    import os as _os
    cloud_configured = bool(_os.getenv("OPENROUTER_API_KEY", ""))
    for cloud_key, cloud_info in CLOUD_MODELS.items():
        model_capacities.append({
            "model_id": cloud_key,
            "family": cloud_info.get("name", cloud_key),
            "parameters": "cloud",
            "vram_gb": 0,
            "context_window": cloud_info.get("context_window", 128000),
            "speed_tier": "fast",
            "quality_tier": "premium",
            "available": cloud_configured,
            "estimated_tokens_per_second": 80,
            "best_for": cloud_info.get("strengths", []),
            "provider": "cloud",
            "cost_per_m_in": cloud_info.get("input_cost_per_m", 0),
            "cost_per_m_out": cloud_info.get("output_cost_per_m", 0),
        })

    return {
        "available_models": available,
        "total_known_models": len(MODELS) + len(CLOUD_MODELS),
        "model_capacities": model_capacities,
    }


@app.get("/llm/estimate")
async def llm_estimate(prompt_tokens: int = 500, max_tokens: int = 2048) -> dict[str, Any]:
    """
    Estimate completion time and token capacity for a given input size.
    Useful for the dashboard to show time-remaining predictions.
    """
    from lib.localllm.models import MODELS

    available: list[str] = []
    if _llm_client:
        try:
            available = await _llm_client.list_models()
        except Exception:
            pass

    # Base estimates per speed tier
    tps_estimates = {"fast": 40, "medium": 25, "slow": 15, "very_slow": 8}

    estimates = []
    for model_id, profile in MODELS.items():
        is_available = any(model_id in m for m in available)
        if not is_available:
            continue
        # Derive speed tier from parameter count
        param_str = profile.parameters.upper().replace("B", "")
        try:
            param_val = float(param_str)
        except ValueError:
            param_val = 7.0
        if param_val <= 3:
            speed_tier = "fast"
        elif param_val <= 8:
            speed_tier = "medium"
        elif param_val <= 14:
            speed_tier = "slow"
        else:
            speed_tier = "very_slow"
        est_tps = tps_estimates.get(speed_tier, 20)
        total_tokens = prompt_tokens + max_tokens
        fits_context = total_tokens <= profile.context_window
        est_seconds = round(max_tokens / max(est_tps, 1), 1)
        estimates.append({
            "model_id": model_id,
            "estimated_tps": est_tps,
            "estimated_seconds": est_seconds,
            "estimated_time_human": (
                f"{int(est_seconds // 60)}m {int(est_seconds % 60)}s"
                if est_seconds >= 60
                else f"{est_seconds}s"
            ),
            "fits_context": fits_context,
            "context_window": profile.context_window,
        })

    return {
        "prompt_tokens": prompt_tokens,
        "max_tokens": max_tokens,
        "estimates": estimates,
    }


# ---------------------------------------------------------------------------
# Projects / Outputs Endpoints
# ---------------------------------------------------------------------------

@app.get("/projects")
async def list_projects() -> dict[str, Any]:
    """
    List all output projects (webgen sites, content jobs, etc.)
    with proper human-readable names.
    """
    import json as _json

    projects: list[dict[str, Any]] = []

    # --- WebGen projects from output/webgen/ ---
    webgen_output = PROJECT_ROOT / "output" / "webgen"
    if webgen_output.exists():
        for child in sorted(webgen_output.iterdir()):
            if child.is_dir():
                # Try to read a project manifest or index.html for better naming
                name = child.name.replace("-", " ").replace("_", " ").title()
                file_count = sum(1 for _ in child.rglob("*") if _.is_file())
                total_size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                # Check for index.html title
                index_html = child / "index.html"
                if index_html.exists():
                    try:
                        content = index_html.read_text(errors="ignore")[:2000]
                        import re
                        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
                        if title_match:
                            name = title_match.group(1).strip()
                    except Exception:
                        pass

                projects.append({
                    "id": child.name,
                    "name": name,
                    "type": "webgen",
                    "path": str(child.relative_to(PROJECT_ROOT)),
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                    "total_size_mb": round(total_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(child.stat().st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(child.stat().st_mtime).isoformat(),
                })

    # --- Content pipeline jobs from memory/content_jobs/ ---
    content_jobs_dir = PROJECT_ROOT / "backend" / "memory" / "content_jobs"
    if content_jobs_dir.exists():
        for jf in sorted(content_jobs_dir.glob("*.json")):
            try:
                data = _json.loads(jf.read_text())
                projects.append({
                    "id": data.get("id", jf.stem),
                    "name": data.get("topic", jf.stem.replace("-", " ").replace("_", " ").title()),
                    "type": "content",
                    "path": str(jf.relative_to(PROJECT_ROOT)),
                    "status": data.get("status", "unknown"),
                    "platform_targets": data.get("platform_targets", []),
                    "created_at": data.get("created_at", ""),
                    "modified_at": data.get("updated_at", ""),
                })
            except Exception:
                pass

    # --- WebGen projects from memory/webgen_projects/ ---
    webgen_projects_dir = PROJECT_ROOT / "backend" / "memory" / "webgen_projects"
    if webgen_projects_dir.exists():
        for pf in sorted(webgen_projects_dir.glob("*.json")):
            try:
                data = _json.loads(pf.read_text())
                projects.append({
                    "id": data.get("id", pf.stem),
                    "name": data.get("business_name", pf.stem.replace("-", " ").replace("_", " ").title()),
                    "type": "webgen_project",
                    "path": str(pf.relative_to(PROJECT_ROOT)),
                    "status": data.get("status", "unknown"),
                    "pages": data.get("page_count", 0),
                    "created_at": data.get("created_at", ""),
                    "modified_at": data.get("updated_at", ""),
                })
            except Exception:
                pass

    return {
        "projects": projects,
        "total": len(projects),
        "types": {
            "webgen": sum(1 for p in projects if p["type"] == "webgen"),
            "content": sum(1 for p in projects if p["type"] == "content"),
            "webgen_project": sum(1 for p in projects if p["type"] == "webgen_project"),
        },
    }


@app.get("/projects/{project_id}/files")
async def list_project_files(project_id: str, project_type: str = "webgen") -> dict[str, Any]:
    """List files in a specific project output folder."""
    if project_type == "webgen":
        project_dir = PROJECT_ROOT / "output" / "webgen" / project_id
    elif project_type == "content":
        project_dir = PROJECT_ROOT / "backend" / "memory" / "content_jobs"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown project type: {project_type}")

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if not str(project_dir.resolve()).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied")

    files: list[dict[str, Any]] = []
    for f in sorted(project_dir.rglob("*")):
        if f.is_file():
            files.append({
                "name": f.name,
                "path": str(f.relative_to(PROJECT_ROOT)),
                "size_bytes": f.stat().st_size,
                "extension": f.suffix,
            })

    return {
        "project_id": project_id,
        "project_type": project_type,
        "files": files,
        "file_count": len(files),
    }


# ---------------------------------------------------------------------------
# Drift & Governance Endpoints
# ---------------------------------------------------------------------------

@app.get("/drift", response_model=DriftReport)
async def drift_status() -> DriftReport:
    """Return current drift report."""
    return drift_guard.check_invariants()


@app.get("/drift/events")
async def drift_events() -> list[dict[str, Any]]:
    """Return recent drift events."""
    events = logger.get_drift_events(50)
    return [e.model_dump(mode="json") for e in events]


# ---------------------------------------------------------------------------
# Log Endpoints
# ---------------------------------------------------------------------------

@app.get("/logs")
async def get_logs(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent tool execution logs."""
    logs = logger.get_recent_tool_logs(limit)
    return [l.model_dump(mode="json") for l in logs]


@app.get("/logs/general")
async def get_general_logs(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent general system logs."""
    return logger.get_general_logs(limit)


# ---------------------------------------------------------------------------
# Memory Endpoints (read-only for dashboard — INV-8)
# ---------------------------------------------------------------------------

@app.get("/memory")
async def list_memory_namespaces() -> dict[str, Any]:
    """List all memory namespaces and their sizes."""
    namespaces = memory_store.list_namespaces()
    return {
        "namespaces": {
            ns: {
                "size_bytes": memory_store.get_namespace_size(ns),
                "size_mb": round(memory_store.get_namespace_size(ns) / (1024 * 1024), 4),
            }
            for ns in namespaces
        },
        "shared_events_count": len(memory_store.get_shared_events()),
    }


@app.get("/memory/agents")
async def list_agent_memory_usage() -> dict[str, Any]:
    """Return per-agent memory usage with explicit MB values."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    agents = _orchestrator.get_agent_memory_usage()
    total_bytes = sum(a["size_bytes"] for a in agents)
    return {
        "agents": agents,
        "total_size_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 * 1024), 4),
    }


@app.get("/memory/{namespace}")
async def get_memory(namespace: str) -> dict[str, Any]:
    """Read all data from a memory namespace (dashboard read-only access)."""
    data = memory_store.read_all(namespace)
    size_bytes = memory_store.get_namespace_size(namespace)
    return {
        "namespace": namespace,
        "data": data,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 4),
    }


@app.get("/events")
async def get_shared_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return shared events from the orchestrator."""
    return memory_store.get_shared_events(limit)


# ---------------------------------------------------------------------------
# Soul Agent Endpoints
# ---------------------------------------------------------------------------

@app.post("/soul/reflect")
async def soul_reflect(trigger: str = "manual") -> dict[str, Any]:
    """Trigger a Soul Agent self-reflection and return the result."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    reflection = await _orchestrator.soul_reflect(trigger=trigger)
    return {"reflection": reflection, "trigger": trigger, "timestamp": datetime.utcnow().isoformat()}


@app.get("/soul/goals")
async def soul_goals() -> dict[str, Any]:
    """Return the Soul Agent's active goals."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    goals = _orchestrator.soul_get_goals()
    return {"goals": goals, "count": len(goals)}


@app.post("/soul/goals")
async def soul_add_goal(request: dict[str, Any]) -> dict[str, Any]:
    """Add a new goal to the Soul Agent."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    title = str(request.get("title", "")).strip()
    description = str(request.get("description", "")).strip()
    priority = str(request.get("priority", "MEDIUM")).upper()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    goal = _orchestrator.soul_set_goal(title, description, priority)
    return goal


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.server:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        reload=True,
    )
