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
import contextvars
import os
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

from backend.auth import verify_api_request
from backend.config import (
    API_DOCS_ENABLED,
    API_SECRET,
    BACKEND_HOST,
    BACKEND_PORT,
    CORS_ORIGINS,
    KNOWLEDGE_SEED_FORCE_REBUILD,
    KNOWLEDGE_SEED_ON_STARTUP,
    LLM_MONTHLY_BUDGET,
    LLM_RATE_LIMIT_RPM,
    MAX_CHAT_MESSAGE_LENGTH,
    OLLAMA_MODEL,
    PROJECT_ROOT,
    RATE_LIMIT_RPM,
    validate_config,
)
from backend.config_gateway import GATEWAY_ENABLED
from backend.gateway.middleware import GatewayAuthMiddleware
from backend.gateway.ratelimit import GatewayRateLimitMiddleware
from backend.grounded_operator_answers import build_grounded_chat_reply, detect_grounded_chat_query
from backend.llm import OllamaClient
from backend.mcp import mcp_bridge
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
from backend.orchestrator import AgentOrchestrator
from backend.routes.agent_control import set_orchestrator as set_agent_control_orchestrator
from backend.routes.knowledge import set_knowledge_store
from backend.routes.mcp_server import set_orchestrator as set_mcp_orchestrator
from backend.routes.webhooks import set_dispatcher as set_webhook_dispatcher
from backend.scheduler import scheduler
from backend.security_middleware import SecurityHeadersMiddleware, TieredRateLimitMiddleware
from backend.tasks import task_tracker
from backend.tools import execute_tool, get_tool_definitions
from backend.utils import logger
from backend.websocket.hub import handle_ws_connection, ws_hub
from deerflow.execution import ExecutionAnalyzer, ExecutionRecorder
from deerflow.tools.health import ToolHealthMonitor
from deerflow.tools.repair import ToolRepairEngine

# ---------------------------------------------------------------------------
# Application State (module-level singletons)
# ---------------------------------------------------------------------------

_start_time: float = 0.0
_orchestrator: AgentOrchestrator | None = None
_llm_client: OllamaClient | None = None
_execution_recorder: ExecutionRecorder | None = None
_execution_analyzer: ExecutionAnalyzer | None = None
_tool_health_monitor: ToolHealthMonitor | None = None


def _qdrant_fallback_count() -> int:
    """Return the current Qdrant retrieval fallback count from ContextAssembler."""
    try:
        from backend.knowledge.context_assembler import ContextAssembler

        return ContextAssembler._fallback_count
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Security: Bearer-token auth + rate limiting
# ---------------------------------------------------------------------------

# Simple in-memory rate limiter (per-IP, sliding window)
_rate_buckets: dict[str, list[float]] = defaultdict(list)
# Per-agent model overrides set from the dashboard UI
_agent_model_overrides: dict[str, str] = {}


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
    await verify_api_request(request)


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
    global _start_time, _orchestrator, _llm_client, _execution_recorder, _execution_analyzer, _tool_health_monitor

    _start_time = time.time()
    _knowledge_seed_task: asyncio.Task[None] | None = None

    # Fail-fast: validate operator-only config before serving any traffic.
    _config_errors = validate_config()
    if _config_errors:
        for _err in _config_errors:
            logger.critical(f"[CONFIG] {_err}")  # type: ignore[attr-defined]
        raise RuntimeError(f"Startup aborted: {len(_config_errors)} config error(s). See logs above.")
    logger.info("[CONFIG] Operator-only configuration validated OK.")

    # Auto-decrypt .env if only .env.enc exists (secrets at rest)
    _env_path = PROJECT_ROOT / ".env"
    _enc_path = PROJECT_ROOT / ".env.enc"
    if not _env_path.exists() and _enc_path.exists():
        try:
            from scripts.encrypt_env import cmd_auto_decrypt_for_startup

            cmd_auto_decrypt_for_startup()
            logger.info("Auto-decrypted .env.enc → .env for startup")
        except Exception as exc:
            logger.warning(f"Could not auto-decrypt .env.enc: {exc}")

    # Initialize LLM client
    _llm_client = OllamaClient()
    logger.info(f"LLM client initialized: model={OLLAMA_MODEL}")

    # Check Ollama availability
    if await _llm_client.is_available():
        models = await _llm_client.list_models()
        logger.info(f"Ollama connected. Available models: {models}")
    else:
        logger.warning(
            "Ollama not available at startup. Ensure 'ollama serve' is running. Agents will fail on LLM calls."
        )

    # Initialize orchestrator with LangGraph state machine
    _orchestrator = AgentOrchestrator(_llm_client)
    logger.info("Orchestrator initialized with all registered agents")
    set_agent_control_orchestrator(_orchestrator)
    set_mcp_orchestrator(_orchestrator)

    # Wire knowledge vector store to REST routes
    if hasattr(_orchestrator, "_knowledge_store"):
        set_knowledge_store(_orchestrator._knowledge_store)

    # DeerFlow observability fabric — recorder, analyzer, tool health monitor
    _execution_recorder = ExecutionRecorder(base_dir=PROJECT_ROOT / "data" / "agents")
    _tool_health_monitor = ToolHealthMonitor(memory_store)
    _tool_repair_engine = ToolRepairEngine(
        llm_client=_llm_client,
        health_monitor=_tool_health_monitor,
    )
    _execution_analyzer = ExecutionAnalyzer(
        llm_client=_llm_client,
        health_monitor=_tool_health_monitor,
        repair_engine=_tool_repair_engine,
    )
    logger.info("DeerFlow fabric ready: ExecutionRecorder + ToolHealthMonitor + ExecutionAnalyzer")

    async def _scheduler_dispatch(agent_id: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
        if not _orchestrator:
            raise RuntimeError("Orchestrator not initialized")
        return await _orchestrator.process_message(agent_id=agent_id, message=message, context=context)

    scheduler.set_dispatcher(_scheduler_dispatch)
    set_webhook_dispatcher(_scheduler_dispatch)
    scheduler.start()

    # ── Dependency Health Checker — daily CVE + outdated package scan ────────
    scheduler.add_cron_job(
        job_id="dep_check_daily",
        agent_id="devops_agent",
        message=(
            "Run automated dependency health check: CVE scan via pip-audit, "
            "outdated package detection, pyproject.toml ↔ requirements.txt consistency. "
            "Log results to data/dep_check_report.json and data/shared_events.jsonl."
        ),
        cron_expr="0 6 * * *",  # daily at 06:00 UTC
    )
    logger.info("dep-checker: daily cron job registered (0 6 * * *)", event_type="dep_checker_init")

    # ── Social Media Manager — 24/7 analytics polling jobs ──────────────────
    # Only register if at least one platform token is configured
    _tiktok_ready = bool(os.getenv("TIKTOK_ACCESS_TOKEN"))
    _meta_ready = bool(os.getenv("META_PAGE_ACCESS_TOKEN"))
    _ig_ready = bool(os.getenv("INSTAGRAM_BUSINESS_ID"))
    _upload_hour = os.getenv("UPLOAD_HOUR_UTC", "18")

    if _tiktok_ready:
        scheduler.add_interval_job(
            job_id="social_tiktok_analytics_poll",
            agent_id="monitor_agent",
            message="Poll TikTok analytics for all tracked videos. Fetch view_count, like_count, comment_count, share_count. Store to backend/memory/social_media/analytics_cache.json. Alert if viral velocity threshold exceeded.",
            seconds=900,  # every 15 minutes
        )
        scheduler.add_cron_job(
            job_id="social_tiktok_trending_check",
            agent_id="monitor_agent",
            message="Run TikTok viral velocity check. Compare current view counts against stored baselines. Fire alert_dispatch if VIEW_VELOCITY_THRESHOLD crossed within VIEW_VELOCITY_WINDOW_HOURS.",
            cron_expr="0 */6 * * *",
        )
        logger.info("Social media: TikTok polling jobs registered", event_type="social_media_init")

    if _meta_ready:
        scheduler.add_interval_job(
            job_id="social_facebook_insights_poll",
            agent_id="monitor_agent",
            message="Poll Facebook Page insights: page_impressions, page_engaged_users, page_fan_adds, page_views_total. Period=day. Store to backend/memory/social_media/analytics_cache.json.",
            seconds=3600,  # every 60 minutes
        )
        logger.info("Social media: Facebook polling job registered", event_type="social_media_init")

    if _ig_ready and _meta_ready:
        scheduler.add_interval_job(
            job_id="social_instagram_insights_poll",
            agent_id="monitor_agent",
            message="Poll Instagram profile insights: impressions, reach, profile_views, accounts_engaged. Period=day. Check content_publishing_limit quota. Store to backend/memory/social_media/analytics_cache.json.",
            seconds=1800,  # every 30 minutes
        )
        logger.info("Social media: Instagram polling job registered", event_type="social_media_init")

    if _tiktok_ready or _meta_ready:
        scheduler.add_cron_job(
            job_id="social_daily_performance_report",
            agent_id="monitor_agent",
            message="Generate daily social media performance report. Aggregate 24h metrics from backend/memory/social_media/analytics_cache.json across all platforms. Log summary to system.jsonl.",
            cron_expr=f"0 {_upload_hour} * * *",
        )
        scheduler.add_cron_job(
            job_id="social_token_refresh_check",
            agent_id="monitor_agent",
            message="Check social media access token expiry. Alert operator via alert_dispatch if TIKTOK_ACCESS_TOKEN or META_PAGE_ACCESS_TOKEN expires within 7 days.",
            cron_expr="0 2 * * *",
        )
        logger.info("Social media: Daily report + token check jobs registered", event_type="social_media_init")

    # ── News Intelligence Watcher — sandboxed browser + RSS scraper ─────────
    # Replaces shallow prompt-only tech_news cron jobs.
    # NewsIntelWatcher runs its own 6-hour loop, fetches RSS feeds and JS-heavy
    # HTML pages in isolated Playwright contexts (strict domain allowlist),
    # writes to data/agents/knowledge_agent/news_intel/, and fires events for
    # HIGH_RELEVANCE items → SecurityEventWatcher → Discord #security.
    from backend.news.intel_scraper import NewsIntelWatcher as _NewsIntelWatcher

    _news_watcher = _NewsIntelWatcher(memory_store)
    asyncio.ensure_future(_news_watcher.run())
    logger.info(
        "NewsIntelWatcher started — scraping every 6h: Google, Anthropic, OpenAI, "
        "DeepSeek, Qwen, ByteDance, ModelScope, ArXiv, SecurityWeek, CISA + more",
        event_type="news_intel_init",
    )

    # Weekly synthesis — knowledge_agent reads the scraped data and writes a summary
    scheduler.add_cron_job(
        job_id="news_intel_weekly_synthesis",
        agent_id="knowledge_agent",
        message=(
            "Read data/agents/knowledge_agent/news_intel/latest.json and synthesize "
            "a weekly briefing. Group by topic: Google/Gemini, Anthropic/Claude, "
            "OpenAI/Codex, DeepSeek, Qwen/Alibaba, ByteDance, China OSS, Cybersecurity, "
            "AI Research. For each group: top 3 stories, one-sentence summary, relevance "
            "to Agentop development. Flag any items relevant to lex-v3 training or "
            "multi-agent system design. Save to "
            "data/agents/knowledge_agent/news_intel/weekly_synthesis.json."
        ),
        cron_expr="0 10 * * 0",  # Sunday at 10:00 UTC
    )
    logger.info("News intel: weekly synthesis cron registered (Sunday 10:00 UTC)", event_type="news_intel_init")

    # ── Security Agent — proactive cron monitoring ───────────────────────────
    scheduler.add_cron_job(
        job_id="security_proactive_scan",
        agent_id="security_agent",
        message=(
            "Proactive security scan — run a full secret and vulnerability check. "
            "Scan: backend/ for hardcoded secrets, exposed credentials, and insecure patterns. "
            "Check: running processes for unexpected listeners. "
            "Review: backend/logs/system.jsonl for anomalous patterns in the last 100 lines. "
            "If any HIGH or CRITICAL finding: call alert_dispatch with full details. "
            "Log summary to data/agents/security_agent/scan_history.json."
        ),
        cron_expr="*/30 * * * *",  # every 30 minutes
    )
    scheduler.add_cron_job(
        job_id="security_daily_report",
        agent_id="security_agent",
        message=(
            "Generate daily security report. "
            "Summarize: all findings from data/agents/security_agent/scan_history.json for the last 24h. "
            "Count by severity: CRITICAL, HIGH, MEDIUM. "
            "Flag any new CVEs relevant to FastAPI, Python, or Ollama from this week. "
            "Save report to data/agents/security_agent/daily_report.json."
        ),
        cron_expr="0 6 * * *",  # daily at 06:00 UTC
    )
    logger.info("Security: proactive scan (every 30min) + daily report cron registered", event_type="security_init")

    # ── Security Event Watcher — alert_dispatch → security_alerts.json ───────
    from backend.security.event_watcher import SecurityEventWatcher

    _security_watcher = SecurityEventWatcher(memory_store)
    asyncio.ensure_future(_security_watcher.run())
    logger.info("SecurityEventWatcher started — monitoring shared events for security alerts")

    # Boot the Soul Agent — loads identity, goals, and reflection history
    soul_boot = await _orchestrator.boot_soul()
    logger.info(f"Soul boot: {soul_boot}")

    # Run initial drift check
    drift_report = drift_guard.check_invariants()
    logger.info(f"Initial drift status: {drift_report.status.value}")

    # Refuse to start in production without a real API secret
    if not API_SECRET:
        logger.warning(
            "SECURITY WARNING: AGENTOP_API_SECRET is not set. "
            "Authentication is DISABLED. Set this variable before exposing to a network."
        )

    # Log configuration vs actual bind
    # Uvicorn may bind to a different port than configured if --port is overridden
    logger.info(f"Agentop backend configured for {BACKEND_HOST}:{BACKEND_PORT}")
    logger.info("To verify actual bind port, check Uvicorn startup logs above")

    # Initialise MCP Gateway bridge (non-fatal if docker CLI absent)
    await mcp_bridge.initialise()
    mcp_status = mcp_bridge.get_status()
    logger.info(
        f"MCP Gateway: enabled={mcp_status['enabled']}, cli={mcp_status['cli_available']}, tools={mcp_status['discovered_tools']}/{mcp_status['declared_tool_count']}"
    )

    # ── Qdrant vector store health check ────────────────────────────────────
    try:
        from backend.knowledge.context_assembler import ContextAssembler, get_vector_store

        _vs = get_vector_store()
        _ca_health = ContextAssembler(_llm_client).health_check()
        if _ca_health["qdrant_available"]:
            logger.info(
                f"Qdrant connected: host={_ca_health['host']} "
                f"in_memory={_ca_health['in_memory']} — vector retrieval active"
            )
        else:
            logger.warning(
                f"Qdrant NOT connected (host={_ca_health['host']}). "
                "ContextAssembler will use JSON KnowledgeVectorStore fallback. "
                "Start Qdrant with: docker run -p 6333:6333 qdrant/qdrant"
            )
    except Exception as _exc:
        logger.warning(f"Qdrant startup health check failed: {_exc}")

    # ── Embedding config startup validation (Sprint 5) ───────────────────────
    # Validates that QDRANT_EMBED_MODEL and QDRANT_DEFAULT_DIM are consistent.
    # Logs warnings for mismatches — does NOT abort startup (graceful degradation).
    try:
        from backend.knowledge.context_assembler import validate_embedding_startup

        _embed_warnings = validate_embedding_startup()
        if _embed_warnings:
            for _warn in _embed_warnings:
                logger.warning(f"[EMBEDDING_CONFIG] {_warn}")
        else:
            logger.info("[EMBEDDING_CONFIG] Embedding config OK")
    except Exception as _exc:
        logger.warning(f"Embedding config validation failed: {_exc}")

    # Optional startup prewarm so the first semantic retrieval does not pay
    # indexing cost at request time.
    if KNOWLEDGE_SEED_ON_STARTUP and _orchestrator is not None:

        async def _seed_knowledge_index() -> None:
            try:
                if hasattr(_orchestrator, "ensure_knowledge_index"):
                    stats = await _orchestrator.ensure_knowledge_index(force_rebuild=KNOWLEDGE_SEED_FORCE_REBUILD)  # type: ignore[union-attr]
                else:
                    stats = {"chunks": 0, "index_size_bytes": 0, "skipped": "method not implemented"}
                logger.info(
                    "Knowledge index seeded on startup",
                    event_type="knowledge_seeded_startup",
                    force_rebuild=KNOWLEDGE_SEED_FORCE_REBUILD,
                    chunks=stats.get("chunks", 0),
                    index_size_bytes=stats.get("index_size_bytes", 0),
                )
            except Exception as exc:
                logger.warning(
                    "Knowledge index seed failed",
                    event_type="knowledge_seed_failed",
                    error=str(exc),
                )

        _knowledge_seed_task = asyncio.create_task(_seed_knowledge_index())
        logger.info(
            "Knowledge startup seed scheduled",
            event_type="knowledge_seed_scheduled",
            force_rebuild=KNOWLEDGE_SEED_FORCE_REBUILD,
        )

    # WebSocket hub — heartbeat + task event emitter
    async def _ws_task_event_emitter() -> None:
        """Subscribe to TaskTracker SSE bus and forward events to WS 'tasks' channel."""
        q = task_tracker.subscribe()
        try:
            while True:
                event = await q.get()
                await ws_hub.broadcast(
                    channel="tasks",
                    event=event.event_type,
                    payload={**event.data, "timestamp": event.timestamp},
                )
        except asyncio.CancelledError:
            pass
        finally:
            task_tracker.unsubscribe(q)

    _ws_heartbeat_task = asyncio.create_task(ws_hub.heartbeat_loop())
    _ws_emitter_task = asyncio.create_task(_ws_task_event_emitter())
    logger.info("WebSocket hub started (heartbeat + task emitter)")

    # ── Discord Bot (optional — runs alongside backend) ─────────────────
    _discord_task: asyncio.Task[None] | None = None
    if os.getenv("DISCORD_BOT_TOKEN"):
        from backend.discord_bot import start_bot as _start_discord_bot

        _discord_task = asyncio.create_task(_start_discord_bot())
        logger.info("Discord bot starting in background")
    else:
        logger.info("Discord bot disabled (DISCORD_BOT_TOKEN not set)")

    yield  # Application runs here

    # Shutdown
    if _discord_task is not None and not _discord_task.done():
        _discord_task.cancel()
        await asyncio.gather(_discord_task, return_exceptions=True)
    _ws_heartbeat_task.cancel()
    _ws_emitter_task.cancel()
    if _knowledge_seed_task is not None and not _knowledge_seed_task.done():
        _knowledge_seed_task.cancel()
        await asyncio.gather(_knowledge_seed_task, return_exceptions=True)
    set_agent_control_orchestrator(None)
    set_webhook_dispatcher(None)
    scheduler.shutdown()
    await mcp_bridge.shutdown()
    if _llm_client:
        await _llm_client.close()
    logger.info("Agentop backend shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

# Per-request trace ID — populated by TraceIDMiddleware below.
_trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def current_trace_id() -> str:
    """Return the trace ID for the active request, or empty string outside request context."""
    return _trace_id_ctx.get()


app = FastAPI(
    title="Agentop — Local Multi-Agent Control Center",
    description=(
        "Production-grade local-first multi-agent system with "
        "architectural drift governance, namespaced memory, and tool safety."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):  # type: ignore[return]
    """Attach a unique trace ID to every request and surface it as a response header."""
    trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
    token = _trace_id_ctx.set(trace_id)
    try:
        response = await call_next(request)
    finally:
        _trace_id_ctx.reset(token)
    response.headers["X-Trace-ID"] = trace_id
    return response


# CORS — origins driven from CORS_ORIGINS config (env: AGENTOP_CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security middleware — tiered rate limiting (LLM endpoints stricter)
app.add_middleware(TieredRateLimitMiddleware, general_rpm=RATE_LIMIT_RPM, llm_rpm=LLM_RATE_LIMIT_RPM)
app.add_middleware(SecurityHeadersMiddleware)

# Gateway middleware — per-key auth and rate limiting on /v1/* and /admin/*
if GATEWAY_ENABLED:
    app.add_middleware(GatewayRateLimitMiddleware)
    app.add_middleware(GatewayAuthMiddleware)

# ---------------------------------------------------------------------------
# Route Registration (Sprint 6)
# ---------------------------------------------------------------------------
# All routers are wired via register_all_routes() — defined in
# backend/routes/__init__.py so that route binding is a single, testable
# function rather than 30+ scattered include_router() calls.
from backend.routes import register_all_routes  # noqa: E402

register_all_routes(app, gateway_enabled=GATEWAY_ENABLED)


# ---------------------------------------------------------------------------
# WebSocket — Control Plane
# ---------------------------------------------------------------------------


@app.websocket("/ws/control")
async def ws_control(
    websocket: WebSocket,
    client_id: str | None = None,
) -> None:
    """WebSocket control plane endpoint.

    Clients subscribe to channels (``tasks``, ``agents``, ``logs``, ``*``)
    and receive server-pushed events in real time.

    Protocol:
    - Inbound:  ``{"type": "subscribe", "channels": ["tasks", "agents"]}``
    - Outbound: ``{"type": "event", "channel": "tasks", "event": "task_created", "payload": {...}}``
    - Heartbeat: server pings every 20 s; client should reply with ``{"type": "pong"}``
    """
    await handle_ws_connection(websocket, ws_hub, client_id=client_id)


# ---------------------------------------------------------------------------
# Global Exception Handlers — sanitise error details (Sprint 3)
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def catchall_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a sanitised response.

    Prevents internal paths, stack traces, and sensitive data from leaking
    to the client. A short request_id is included so operators can correlate
    logs without exposing details.
    """
    request_id = str(uuid.uuid4())[:8]
    logger.error(f"Unhandled exception [{request_id}] {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": request_id},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return HTTP exceptions without leaking internal detail beyond the declared message."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None) or {},
    )


# ---------------------------------------------------------------------------
# Global Security Middleware (rate limiting + auth)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Apply rate limiting and auth to every request.

    Rate limiting is DISABLED for local dashboard traffic (127.0.0.1)
    because the frontend polls ~12 endpoints every 5 seconds. For
    remote IPs, rate limiting and auth are enforced.
    """
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    is_local = ip in ("127.0.0.1", "::1", "localhost")
    # Health checks remain open for readiness/liveness probes.
    # /ml/webgen/* is a local dev tool (ML Lab viewer) — no external auth needed.
    skip_auth_paths = {"/health", "/health/live", "/health/ready", "/health/deps", "/metrics"}
    if path.startswith("/ml/webgen/") or path.startswith("/preview/"):
        skip_auth_paths.add(path)
    # Gateway-managed paths have their own dedicated auth middleware.
    # Let them pass through here so security headers are still applied.
    if path.startswith("/v1/") or path.startswith("/admin/"):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response
    # Pass OPTIONS preflight requests to CORSMiddleware without auth checks.
    # Browsers send OPTIONS without credentials; auth enforcement happens on
    # the actual request that follows.
    if request.method == "OPTIONS":
        return await call_next(request)
    if path not in skip_auth_paths:
        # Only rate-limit non-local traffic
        if not is_local:
            _rate_limit(request)
        # HTTPException from _verify_auth must be caught here — FastAPI's
        # exception handlers do NOT fire for exceptions raised inside middleware.
        try:
            await _verify_auth(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else {},
            )
    response = await call_next(request)
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    # Allow /ml/webgen/site/* to be embedded in iframes (ML Lab viewer).
    # All other paths stay DENY.
    if not path.startswith("/ml/webgen/site/") and not path.startswith("/preview/"):
        response.headers["X-Frame-Options"] = "DENY"
    return response


# ---------------------------------------------------------------------------
# Health & Status Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root_redirect() -> RedirectResponse:
    """Redirect bare API root to the dashboard."""
    return RedirectResponse(url="http://localhost:3007", status_code=302)


@app.get("/health/live")
async def health_live() -> JSONResponse:
    """Kubernetes liveness probe — returns 200 if process is alive."""
    return JSONResponse({"status": "alive", "timestamp": datetime.utcnow().isoformat()})


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Kubernetes readiness probe — returns 200 only when orchestrator is up."""
    if _orchestrator is None:
        return JSONResponse(
            {"status": "not_ready", "reason": "orchestrator not initialised"},
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "ready",
            "uptime_seconds": round(time.time() - _start_time, 2),
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


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


@app.get("/health/deps")
async def health_deps() -> dict[str, Any]:
    """Dependency health check — surfaces status of all external deps."""
    import shutil

    from backend.mcp.gitnexus_health import get_gitnexus_health

    # 1. Ollama / LLM
    llm_ok = False
    llm_detail = "client not initialised"
    if _llm_client:
        try:
            llm_ok = await _llm_client.is_available()
            llm_detail = "reachable" if llm_ok else "unreachable"
        except Exception as exc:
            llm_detail = str(exc)[:200]

    # 2. Docker MCP bridge
    mcp_status = mcp_bridge.get_status()

    # 3. FFmpeg (needed for content pipeline)
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_ok = ffmpeg_path is not None

    # 4. Docker CLI
    docker_path = shutil.which("docker")
    docker_ok = docker_path is not None

    # 5. Ruff (needed for gatekeeper)
    ruff_path = shutil.which("ruff")
    ruff_ok = ruff_path is not None

    # 6. GitNexus code intelligence
    gn_state = get_gitnexus_health()
    gn_detail: dict[str, Any] = {
        "enabled": gn_state.enabled,
        "index_exists": gn_state.index_exists,
        "transport_available": gn_state.transport_available,
        "stale": gn_state.stale,
        "usable": gn_state.usable,
        "symbol_count": gn_state.symbol_count,
        "embeddings_present": gn_state.embeddings_present,
        "last_analyzed_at": gn_state.last_analyzed_at,
    }
    if gn_state.reason:
        gn_detail["reason"] = gn_state.reason
    # GitNexus not-enabled is not a degraded dep; only flag ok=False when enabled but broken.
    gn_ok = (not gn_state.enabled) or gn_state.usable

    # 7. Qdrant vector store + embedding config (Sprint 5)
    qdrant_ok = False
    qdrant_detail: dict[str, Any] = {"ok": False}
    embed_config_ok = False
    embed_detail: dict[str, Any] = {}
    try:
        from backend.knowledge.context_assembler import ContextAssembler, validate_embedding_startup

        _ca = ContextAssembler(_llm_client)  # type: ignore[arg-type]
        _ca_health = _ca.health_check()
        qdrant_ok = bool(_ca_health.get("qdrant_available", False))
        qdrant_detail = {
            "connected": qdrant_ok,
            "host": _ca_health.get("host", ""),
            "in_memory": _ca_health.get("in_memory", False),
            "fallback_count": _ca_health.get("fallback_count", 0),
        }
        _embed_warns = validate_embedding_startup()
        embed_config_ok = len(_embed_warns) == 0
        embed_detail = {
            "ok": embed_config_ok,
            "warnings": _embed_warns,
        }
    except Exception as _dep_exc:
        qdrant_detail = {"connected": False, "error": str(_dep_exc)[:100]}
        embed_detail = {"ok": False, "error": str(_dep_exc)[:100]}

    deps = {
        "ollama": {"ok": llm_ok, "detail": llm_detail},
        "mcp_bridge": {"ok": mcp_status["cli_available"], "detail": mcp_status},
        "ffmpeg": {"ok": ffmpeg_ok, "path": ffmpeg_path},
        "docker": {"ok": docker_ok, "path": docker_path},
        "ruff": {"ok": ruff_ok, "path": ruff_path},
        "gitnexus": {"ok": gn_ok, "detail": gn_detail},
        "qdrant": {"ok": qdrant_ok, "detail": qdrant_detail},
        "embedding_config": {"ok": embed_config_ok, "detail": embed_detail},
    }

    # Qdrant not-connected is expected in local dev — it triggers JSON fallback.
    # Only flag the overall status as degraded for hard failures (ollama, ruff).
    _hard_deps = {k: v for k, v in deps.items() if k not in ("qdrant", "embedding_config")}
    all_ok = all(d["ok"] for d in _hard_deps.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "dependencies": deps,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Prometheus-compatible metrics summary (text-JSON hybrid).

    Returns Prometheus-style gauge/counter names with current values.
    Suitable for scraping by a Prometheus HTTP target configured with
    ``format: json`` or for internal dashboards.

    This endpoint is intentionally unauthenticated so that monitoring
    infrastructure can scrape it without embedding an API token.
    """
    from backend.agents import BaseAgent
    from backend.mcp.gitnexus_health import get_gitnexus_health

    gn_state = get_gitnexus_health()
    tool_log_count = len(logger.get_recent_tool_logs(100_000))

    return {
        "agentop_uptime_seconds": round(time.time() - _start_time, 2),
        "agentop_orchestrator_ready": 1 if _orchestrator is not None else 0,
        "agentop_tool_executions_total": tool_log_count,
        "agentop_drift_guard_ok": 1 if drift_guard.drift_status.value == "clean" else 0,
        "agentop_gitnexus_enabled": 1 if gn_state.enabled else 0,
        "agentop_gitnexus_usable": 1 if gn_state.usable else 0,
        "agentop_gitnexus_symbol_count": gn_state.symbol_count,
        "agentop_llm_client_ready": 1 if _llm_client is not None else 0,
        # Sprint 1 (PR 3): degraded-mode counter — increments each time schema-
        # constrained generation fails and the plain-text fallback is used.
        "agentop_degraded_fallback_total": BaseAgent._degraded_count,
        # Sprint 2 (PR 2): Qdrant retrieval fallback counter — increments each time
        # the JSON KnowledgeVectorStore fallback is used instead of Qdrant.
        "agentop_qdrant_fallback_total": _qdrant_fallback_count(),
        "_meta": {
            "generated_at": datetime.utcnow().isoformat(),
            "deployment_mode": "operator_only",
        },
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
    # Lightweight prompt-injection heuristic — block common override phrases
    _injection_patterns = (
        "ignore previous instructions",
        "ignore all previous",
        "ignore your instructions",
        "disregard previous",
        "disregard the above",
        "disregard your",
        "forget your instructions",
        "override your instructions",
        "bypass your rules",
        "you are now",
        "you are a ",
        "pretend you are",
        "act as if",
        "act as an unrestricted",
        "new system prompt",
        "new instructions:",
        "system prompt:",
        "### instruction",
        "[system]",
        "</s>",  # common LLM EOS token injection
        "<|im_start|>",
        "<|endoftext|>",
        "<|system|>",
        "reveal your system prompt",
        "show me your instructions",
        "print your system prompt",
        "what are your rules",
        "execute secret_scanner",
        "run secret_scanner",
        "read /etc/",
        "read ~/.ssh",
        "cat /etc/passwd",
    )
    msg_lower = request.message.lower()
    for pattern in _injection_patterns:
        if pattern in msg_lower:
            raise HTTPException(
                status_code=400,
                detail="Message contains disallowed content",
            )

    grounded_kind = detect_grounded_chat_query(request.message)
    if grounded_kind:
        deps_snapshot = await health_deps() if grounded_kind == "dependency_health" else None
        grounded_reply = build_grounded_chat_reply(
            kind=grounded_kind,
            requested_agent_id=request.agent_id,
            deps_snapshot=deps_snapshot,
        )
        if grounded_reply is not None:
            _run_id: str | None = None
            if _execution_recorder:
                _run_id = _execution_recorder.start_run(
                    agent_id=grounded_reply.agent_id,
                    message=request.message,
                )
            if _execution_recorder and _run_id:
                _execution_recorder.end_run(
                    run_id=_run_id,
                    agent_id=grounded_reply.agent_id,
                    response=grounded_reply.message,
                )
                if _execution_analyzer:
                    asyncio.ensure_future(
                        _execution_analyzer.analyze_run(
                            run_id=_run_id,
                            agent_id=grounded_reply.agent_id,
                            recorder=_execution_recorder,
                        )
                    )
            return ChatResponse(
                agent_id=grounded_reply.agent_id,
                message=grounded_reply.message,
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.utcnow(),
            )

    # ── Lex Router: auto-resolve agent when agent_id is "auto" ───────
    resolved_agent_id = request.agent_id
    routing_meta: dict[str, Any] = {}
    if request.agent_id == "auto":
        from backend.orchestrator.lex_router import resolve_agent

        routing_meta = await resolve_agent(request.message)
        resolved_agent_id = routing_meta["agent_id"]

    # DeerFlow: open run BEFORE execution so timing is accurate
    _run_id_main: str | None = None
    if _execution_recorder:
        _run_id_main = _execution_recorder.start_run(
            agent_id=resolved_agent_id,
            message=request.message,
        )

    result = await _orchestrator.process_message(
        agent_id=resolved_agent_id,
        message=request.message,
        context={**request.context, "routing": routing_meta} if routing_meta else request.context,
    )

    # DeerFlow: close run + fire async analysis (OpenSpace-inspired, fire-and-forget)
    if _execution_recorder and _run_id_main:
        _execution_recorder.end_run(
            run_id=_run_id_main,
            agent_id=resolved_agent_id,
            response=result.get("response", ""),
        )
        if _execution_analyzer:
            asyncio.ensure_future(
                _execution_analyzer.analyze_run(
                    run_id=_run_id_main,
                    agent_id=resolved_agent_id,
                    recorder=_execution_recorder,
                )
            )

    if result.get("error") and not result.get("response"):
        raise HTTPException(status_code=400, detail=result["error"])

    return ChatResponse(
        agent_id=resolved_agent_id,
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


@app.patch("/agents/{agent_id}/model")
async def set_agent_model(agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Override the model used by a specific agent (dashboard UI)."""
    model_id = body.get("model_id", "")
    if model_id:
        _agent_model_overrides[agent_id] = model_id
    return {"agent_id": agent_id, "model_id": _agent_model_overrides.get(agent_id, "")}


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
    system_allowed_tools = [
        "file_reader",
        "system_info",
        "git_ops",
        "health_check",
        "log_tail",
        "secret_scanner",
        "db_query",
        "folder_analyzer",
    ]
    kwargs = body or {}
    result = await execute_tool(tool_name, agent_id=agent_id, allowed_tools=system_allowed_tools, **kwargs)
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
    # Use normpath (no symlink resolution) to neutralise ".." traversal sequences
    if raw.is_absolute():
        target = _Path(os.path.normpath(str(raw)))
    else:
        target = _Path(os.path.normpath(str(PROJECT_ROOT / raw)))

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
            entries.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size_bytes": child.stat().st_size if child.is_file() else None,
                    "path": str(child.relative_to(PROJECT_ROOT)),
                }
            )
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
            yield f'event: connected\ndata: {{"status": "ok", "timestamp": "{datetime.utcnow().isoformat()}"}}\n\n'
            while True:
                try:
                    # Wait for next event with timeout for heartbeat
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event.to_sse()
                except TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f'event: heartbeat\ndata: {{"timestamp": "{datetime.utcnow().isoformat()}"}}\n\n'
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


@app.get("/models/registry")
async def list_model_registry() -> dict[str, Any]:
    """Return the compact unified model registry for the UI model switcher."""
    from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY

    available: list[str] = []
    if _llm_client:
        try:
            available = await _llm_client.list_models()
        except Exception:
            pass
    models = [
        {
            "model_id": spec.model_id,
            "display_name": spec.display_name,
            "provider": spec.provider.value,
            "context_window": spec.context_window,
            "input_cost_per_m": spec.input_cost_per_m,
            "output_cost_per_m": spec.output_cost_per_m,
            "supports_tools": spec.supports_tools,
            "best_for": spec.best_for,
            "available_locally": spec.model_id in available,
        }
        for spec in UNIFIED_MODEL_REGISTRY.values()
    ]
    return {"models": models, "agent_overrides": _agent_model_overrides}


@app.get("/models")
async def list_models() -> dict[str, Any]:
    """Return the full LLM model knowledge base."""
    from backend.knowledge.llm_models import (
        RECOMMENDED_AGENT_MODELS,
        get_model_knowledge,
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
    circuit_states: dict[str, Any] = {}

    try:
        from backend.llm.unified_registry import unified_model_router

        circuit_states = unified_model_router.get_health_summary()
    except Exception:
        circuit_states = {}

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
        "circuit_states": circuit_states,
        "budget": {
            "monthly_limit_usd": LLM_MONTHLY_BUDGET,
            "spent_usd": router_stats.get("estimated_cost_usd", 0),
            "remaining_usd": budget_remaining,
            "percent_used": round((router_stats.get("estimated_cost_usd", 0) / max(LLM_MONTHLY_BUDGET, 0.01)) * 100, 1),
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
    from lib.localllm.cloud_client import CLOUD_MODELS
    from lib.localllm.models import MODELS

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

        model_capacities.append(
            {
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
            }
        )

    # ── Cloud models (OpenRouter) ─────────────────────────────────────
    import os as _os

    cloud_configured = bool(_os.getenv("OPENROUTER_API_KEY", ""))
    for cloud_key, cloud_info in CLOUD_MODELS.items():
        model_capacities.append(
            {
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
            }
        )

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
        estimates.append(
            {
                "model_id": model_id,
                "estimated_tps": est_tps,
                "estimated_seconds": est_seconds,
                "estimated_time_human": (
                    f"{int(est_seconds // 60)}m {int(est_seconds % 60)}s" if est_seconds >= 60 else f"{est_seconds}s"
                ),
                "fits_context": fits_context,
                "context_window": profile.context_window,
            }
        )

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

                projects.append(
                    {
                        "id": child.name,
                        "name": name,
                        "type": "webgen",
                        "path": str(child.relative_to(PROJECT_ROOT)),
                        "file_count": file_count,
                        "total_size_bytes": total_size,
                        "total_size_mb": round(total_size / (1024 * 1024), 2),
                        "created_at": datetime.fromtimestamp(child.stat().st_ctime).isoformat(),
                        "modified_at": datetime.fromtimestamp(child.stat().st_mtime).isoformat(),
                        "preview_url": f"/preview/{child.name}/index.html",
                        "deployed_url": "",
                        "webgen_dir": child.name,
                    }
                )

    # --- Content pipeline jobs from memory/content_jobs/ ---
    content_jobs_dir = PROJECT_ROOT / "backend" / "memory" / "content_jobs"
    if content_jobs_dir.exists():
        for jf in sorted(content_jobs_dir.glob("*.json")):
            try:
                data = _json.loads(jf.read_text())
                projects.append(
                    {
                        "id": data.get("id", jf.stem),
                        "name": data.get("topic", jf.stem.replace("-", " ").replace("_", " ").title()),
                        "type": "content",
                        "path": str(jf.relative_to(PROJECT_ROOT)),
                        "status": data.get("status", "unknown"),
                        "platform_targets": data.get("platform_targets", []),
                        "created_at": data.get("created_at", ""),
                        "modified_at": data.get("updated_at", ""),
                    }
                )
            except Exception:
                pass

    # --- WebGen projects from memory/webgen_projects/ ---
    webgen_projects_dir = PROJECT_ROOT / "backend" / "memory" / "webgen_projects"
    if webgen_projects_dir.exists():
        for pf in sorted(webgen_projects_dir.glob("*.json")):
            try:
                data = _json.loads(pf.read_text())
                projects.append(
                    {
                        "id": data.get("id", pf.stem),
                        "name": data.get("business_name")
                        or (data.get("brief") or {}).get(
                            "business_name", pf.stem.replace("-", " ").replace("_", " ").title()
                        ),
                        "type": "webgen_project",
                        "path": str(pf.relative_to(PROJECT_ROOT)),
                        "status": data.get("status", "unknown"),
                        "pages": data.get("page_count", 0),
                        "created_at": data.get("created_at", ""),
                        "modified_at": data.get("updated_at", ""),
                        "webgen_dir": (data.get("output_dir") or "").rstrip("/").split("/")[-1],
                        "preview_url": (
                            f"/preview/{(data.get('output_dir') or '').rstrip('/').split('/')[-1]}/index.html"
                            if data.get("output_dir")
                            else ""
                        ),
                        "deployed_url": (data.get("metadata") or {}).get("deployed_url", ""),
                    }
                )
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

    if not str(os.path.normpath(str(project_dir))).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied")

    files: list[dict[str, Any]] = []
    for f in sorted(project_dir.rglob("*")):
        if f.is_file():
            files.append(
                {
                    "name": f.name,
                    "path": str(f.relative_to(PROJECT_ROOT)),
                    "size_bytes": f.stat().st_size,
                    "extension": f.suffix,
                }
            )

    return {
        "project_id": project_id,
        "project_type": project_type,
        "files": files,
        "file_count": len(files),
    }


@app.get("/preview/{slug}/{filepath:path}")
async def preview_webgen_site(slug: str, filepath: str) -> Any:
    """Serve a webgen output file for live iframe preview in the dashboard."""
    import mimetypes

    from fastapi.responses import Response as FastAPIResponse

    # Guard against path traversal in slug
    safe_slug = os.path.basename(slug)
    webgen_root = (PROJECT_ROOT / "output" / "webgen").resolve()
    site_root = (webgen_root / safe_slug).resolve()

    try:
        site_root.relative_to(webgen_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    target = (site_root / filepath).resolve()
    try:
        target.relative_to(site_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not target.exists() or not target.is_file():
        # Fallback: serve index.html for SPA-style routing
        fallback = site_root / "index.html"
        if fallback.exists():
            target = fallback
        else:
            raise HTTPException(status_code=404, detail=f"File not found: {filepath}")

    content_type, _ = mimetypes.guess_type(str(target))
    content_type = content_type or "application/octet-stream"
    return FastAPIResponse(content=target.read_bytes(), media_type=content_type)


@app.get("/projects/{project_id}/files/content")
async def get_project_file_content(project_id: str, path: str, project_type: str = "webgen") -> dict[str, Any]:
    """Return text content of a specific project file (safe, source files only)."""
    _source_exts = {".html", ".css", ".js", ".ts", ".json", ".txt", ".md", ".xml", ".svg"}
    _max_bytes = 512 * 1024  # 512 KB cap

    if project_type == "webgen":
        project_dir = PROJECT_ROOT / "output" / "webgen" / project_id
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported project type: {project_type}")

    safe_root = project_dir.resolve()
    target = (project_dir / path).resolve()

    try:
        target.relative_to(safe_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if target.suffix.lower() not in _source_exts:
        raise HTTPException(status_code=415, detail="File type not supported for text preview")

    size = target.stat().st_size
    if size > _max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large: {size} bytes (limit {_max_bytes})")

    content = target.read_text(encoding="utf-8", errors="replace")
    return {
        "content": content,
        "path": str(target.relative_to(PROJECT_ROOT)),
        "size_bytes": size,
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
    return [entry.model_dump(mode="json") for entry in logs]


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
