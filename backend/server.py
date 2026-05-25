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
import re
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

from backend.auth import verify_api_request
from backend.config import (
    ACTIVE_RUNTIME_PROFILE,
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
    NEWS_INTEL_ENABLED,
    OLLAMA_MODEL,
    PROJECT_ROOT,
    RATE_LIMIT_RPM,
    RETRIEVAL_MODE,
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
from backend.model_preferences import (
    EDITABLE_TEAM_AGENT_MAP,
    build_model_preferences_response,
    load_agent_model_overrides,
    load_team_model_preferences,
    resolve_model_selection,
    save_agent_model_overrides,
    save_team_model_preferences,
)
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
    OrdoTrace,
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
from backend.utils.chat_failure_log import write_chat_failure
from backend.websocket.hub import handle_ws_connection, ws_hub
from deerflow.execution import ExecutionAnalyzer, ExecutionRecorder
from deerflow.tools.health import ToolHealthMonitor
from deerflow.tools.repair import ToolRepairEngine

UTC_TZ = timezone.utc  # noqa: UP017

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
# Per-agent model overrides set from the dashboard UI — persisted to disk
_agent_model_overrides: dict[str, str] = load_agent_model_overrides()
_team_model_preferences: dict[str, str] = load_team_model_preferences(_agent_model_overrides)

# Discord/OpenClaw bot status — module-level so /discord/status can read it
_discord_bot_task: "asyncio.Task[None] | None" = None
_discord_last_message_at: str | None = None
_discord_last_routed_agent: str | None = None


def _set_discord_last_message(agent_id: str | None) -> None:
    """Called by the Discord bot when it routes a message to an agent."""
    global _discord_last_message_at, _discord_last_routed_agent
    from datetime import datetime as _dt
    _discord_last_message_at = _dt.now(UTC_TZ).isoformat()
    _discord_last_routed_agent = agent_id


def _resolve_chat_model_selection(agent_id: str, request_model: str | None) -> dict[str, Any]:
    return resolve_model_selection(
        agent_id=agent_id,
        request_model=request_model,
        team_models=_team_model_preferences,
        agent_overrides=_agent_model_overrides,
        fallback_model=OLLAMA_MODEL,
    )


def _merge_model_execution(
    result: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    execution = dict(result.get("model_execution") or {})
    selected_model = str(
        execution.get("selected_model")
        or selection.get("selected_model")
        or selection.get("requested_model")
        or ""
    )
    answering_model = str(
        execution.get("answering_model")
        or selection.get("requested_model")
        or selected_model
    )
    runtime_model = str(execution.get("runtime_model") or answering_model or selected_model)
    execution_role = execution.get("execution_role")
    model_source = str(execution.get("model_source") or selection.get("model_source") or "fallback")
    return {
        "selected_model": selected_model or None,
        "answering_model": answering_model or None,
        "runtime_model": runtime_model or None,
        "execution_role": execution_role or None,
        "model_source": model_source or None,
        "model_used": answering_model or None,
    }


def _emit_llm_response_event(
    agent_id: str,
    message: str,
    model_meta: dict[str, Any],
    routing_method: str | None,
) -> None:
    task_tracker.emit_activity(
        "llm_response",
        {
            "agent_id": agent_id,
            "detail": message[:120],
            "model": model_meta.get("answering_model"),
            "selected_model": model_meta.get("selected_model"),
            "answering_model": model_meta.get("answering_model"),
            "runtime_model": model_meta.get("runtime_model"),
            "execution_role": model_meta.get("execution_role"),
            "model_source": model_meta.get("model_source"),
            "routing_method": routing_method,
            "timestamp": datetime.now(UTC_TZ).isoformat(),
        },
    )
# Count of /chat requests currently being processed by the LLM executor.
# Scheduler jobs check this before dispatching to avoid competing with live users.
_active_user_requests: int = 0


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
    set_knowledge_store(None, _llm_client)

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
        # Skip scheduled task if a user request is currently holding the LLM.
        # This prevents background jobs from queuing behind live chat requests and
        # causing user-visible timeouts due to Ollama's single-request serialization.
        if _active_user_requests > 0:
            logger.info(
                f"Scheduler: skipping {agent_id} — {_active_user_requests} user request(s) in flight",
                event_type="scheduler_skipped_busy",
                agent_id=agent_id,
            )
            return {"skipped": True, "reason": "user_request_in_flight", "agent_id": agent_id}
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
    _meta_ready = bool(os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or os.getenv("META_PAGE_ACCESS_TOKEN"))
    _ig_ready = bool(os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or os.getenv("INSTAGRAM_BUSINESS_ID"))
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
    # Set NEWS_INTEL_ENABLED=false in .env to skip on low-RAM dev machines.
    if NEWS_INTEL_ENABLED:
        from backend.news.intel_scraper import NewsIntelWatcher as _NewsIntelWatcher

        _news_watcher = _NewsIntelWatcher(memory_store)
        asyncio.ensure_future(_news_watcher.run())
        logger.info(
            "NewsIntelWatcher started — scraping every 6h: Google, Anthropic, OpenAI, "
            "DeepSeek, Qwen, ByteDance, ModelScope, ArXiv, SecurityWeek, CISA + more",
            event_type="news_intel_init",
        )
    else:
        logger.info(
            "NewsIntelWatcher disabled (NEWS_INTEL_ENABLED=false) — skipping background browser scraper",
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
                "ContextAssembler will stay Qdrant-only unless JSON fallback is explicitly enabled. "
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

    # ── A2UI session GC — purge canvas state for idle sessions ─────────────
    # Runs every 30 minutes; removes sessions that haven't emitted in A2UI_SESSION_TTL_SECONDS.
    from backend.a2ui.bus import get_a2ui_bus as _get_a2ui_bus

    async def _a2ui_gc_loop() -> None:
        while True:
            await asyncio.sleep(1800)  # 30 minutes
            purged = _get_a2ui_bus().gc_stale_sessions()
            if purged:
                logger.info(f"A2UI GC: purged {purged} stale session(s)")

    _a2ui_gc_task = asyncio.create_task(_a2ui_gc_loop())
    logger.info("A2UI GC task started (30-min interval)")

    # ── Discord Bot (optional — runs alongside backend) ─────────────────
    global _discord_bot_task
    if os.getenv("DISCORD_BOT_TOKEN"):
        from backend.discord_bot import start_bot as _start_discord_bot

        _discord_bot_task = asyncio.create_task(_start_discord_bot())
        logger.info("Discord bot starting in background")
    else:
        logger.info("Discord bot disabled (DISCORD_BOT_TOKEN not set)")

    yield  # Application runs here

    # Shutdown
    if _discord_bot_task is not None and not _discord_bot_task.done():
        _discord_bot_task.cancel()
        await asyncio.gather(_discord_bot_task, return_exceptions=True)
    _ws_heartbeat_task.cancel()
    _ws_emitter_task.cancel()
    _a2ui_gc_task.cancel()
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

    # Persist failure record for /chat so it can be used as training negatives
    if request.url.path == "/chat":
        try:
            body_bytes = await request.body()
            import json as _json_fc
            _body = _json_fc.loads(body_bytes) if body_bytes else {}
        except Exception:
            _body = {}
        write_chat_failure(
            request_id=request_id,
            user_message=_body.get("message", ""),
            chosen_agent=_body.get("agent_id"),
            selected_model=_body.get("model"),
            last_live_step=None,
            ordo_trace=None,
            error_class=type(exc).__name__,
            error_detail=str(exc),
            route_path="/chat",
            pipeline_stage="unhandled_exception",
        )

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
    return JSONResponse({"status": "alive", "timestamp": datetime.now(UTC_TZ).isoformat()})


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
            "timestamp": datetime.now(UTC_TZ).isoformat(),
        }
    )


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Basic health check endpoint."""
    try:
        llm_available = (
            await asyncio.wait_for(_llm_client.is_available(), timeout=3.0)
            if _llm_client
            else False
        )
    except (asyncio.TimeoutError, Exception):
        llm_available = False
    return {
        "status": "healthy",
        "llm_available": llm_available,
        "drift_status": drift_guard.drift_status.value,
        "uptime_seconds": round(time.time() - _start_time, 2),
        "timestamp": datetime.now(UTC_TZ).isoformat(),
        "runtime_profile": ACTIVE_RUNTIME_PROFILE,
        "retrieval_mode": RETRIEVAL_MODE,
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
        "timestamp": datetime.now(UTC_TZ).isoformat(),
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
        "agentop_drift_guard_ok": 1 if drift_guard.drift_status == DriftStatus.GREEN else 0,
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
            "generated_at": datetime.now(UTC_TZ).isoformat(),
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
        runtime_profile=ACTIVE_RUNTIME_PROFILE,
        retrieval_mode=RETRIEVAL_MODE,
    )


# ---------------------------------------------------------------------------
# Agent Endpoints
# ---------------------------------------------------------------------------


@app.get("/discord/status")
async def discord_status() -> dict[str, Any]:
    """Live status of the Discord/OpenClaw bridge bot."""
    token_set = bool(os.getenv("DISCORD_BOT_TOKEN"))
    task_alive = (
        _discord_bot_task is not None
        and not _discord_bot_task.done()
    )
    pid: int | None = None
    pid_alive = False
    pid_file = PROJECT_ROOT / ".discord_bot.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)   # signal 0 = check if process alive, no-op
            pid_alive = True
        except (ProcessLookupError, PermissionError, ValueError):
            pid_alive = False
    connected = token_set and (task_alive or pid_alive)
    return {
        "enabled": token_set,
        "connected": connected,
        "token_set": token_set,
        "last_message_at": _discord_last_message_at,
        "last_routed_agent": _discord_last_routed_agent,
        "pid": pid,
    }


@app.get("/discord/channel-history")
async def discord_channel_history(
    channel: str = "news-intel",
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent posts logged to a Discord channel by the Agentop bot.

    Orchad uses this to answer questions like 'what's in #intel-news?'
    Channel names: news-intel, security-alerts, content-report, comment-farm.
    """
    try:
        from backend.discord_bot import get_discord_post_history as _gdph

        records = await asyncio.wait_for(
            asyncio.to_thread(_gdph, channel_name=channel, limit=limit),
            timeout=3.0,
        )
        # Normalise field names — log saves 'title', older code expected 'headline'
        for r in records:
            if "headline" not in r and "title" in r:
                r["headline"] = r["title"]
        return {"channel": channel, "count": len(records), "posts": records}
    except Exception as _exc:
        return {"channel": channel, "count": 0, "posts": [], "error": str(_exc)}


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

    # ── Fast-path: live data queries that don't need an LLM call ────────────
    # Detects common status/info queries and returns instant formatted responses
    # using live data from the orchestrator, task tracker, and tool registry.
    _msg_q = request.message.lower().strip()

    def _quick_reply(text: str, agent: str = "monitor_agent") -> ChatResponse:
        return ChatResponse(
            agent_id=agent,
            message=text,
            drift_status=DriftStatus.GREEN,
            timestamp=datetime.now(UTC_TZ),
            ordo_trace=None,
            conversation_id=None,
            run_id=None,
            message_id=None,
            sources=[],
            model_used=None,
            routing_method="fast_path",
        )

    _AGENT_STATUS_RE = re.compile(
        r'\b(what|which|list|show|get|tell me|status of)[\w\s]*(agent|agents)\b'
        r'|(who.?s\s*(running|active|online|alive))'
        r'|(agent\s*(list|status|state))'
        r'|(running\s*agents)',
        re.IGNORECASE,
    )
    _TASK_STATUS_RE = re.compile(
        r'\b(show|list|get|what|open|pending|current|active|queued)\b[\w\s]*(task|tasks|job|jobs|work)\b',
        re.IGNORECASE,
    )
    _HEALTH_RE = re.compile(
        r'\b(check\s*health|system\s*health|is\s*everything\s*(ok|fine|good|running|working|up)'
        r'|are\s*(all\s*)?services\s*(up|ok|running)'
        r'|health\s*status|everything\s*(ok|good|fine)'
        r'|system\s*status|how\s*(is|are)[\w\s]*(system|everything|things)\s*(doing|running)?)\b',
        re.IGNORECASE,
    )
    _TOOL_LIST_RE = re.compile(
        r'\b(list|show|get|what|available)\b[\w\s]*(tool|tools)\b',
        re.IGNORECASE,
    )
    _SKILL_LIST_RE = re.compile(
        r'\b(list|show|get|what)\b[\w\s]*(skill|skills)\b',
        re.IGNORECASE,
    )

    if _orchestrator and _AGENT_STATUS_RE.search(request.message):
        _states = _orchestrator.get_agent_states()
        _active = [s for s in _states if s.status == "ACTIVE"]
        _idle = [s for s in _states if s.status == "IDLE"]
        _lines = ["**Agent Status**\n"]
        for s in _states:
            _icon = "🟢" if s.status == "ACTIVE" else "⚪"
            _last = f" — last active {s.last_active.strftime('%H:%M:%S')}" if s.last_active else ""
            _lines.append(f"{_icon} `{s.agent_id}` ({s.status}){_last}")
        _lines.append(f"\n{len(_active)} active · {len(_idle)} idle · {len(_states)} total")
        return _quick_reply("\n".join(_lines))

    if _TASK_STATUS_RE.search(request.message):
        _recent_tasks = task_tracker.get_tasks(20)
        if not _recent_tasks:
            return _quick_reply("**Tasks** — No active or recent tasks.")
        _lines = ["**Recent Tasks**\n"]
        for t in _recent_tasks[:15]:
            _icon = {"RUNNING": "🔄", "DONE": "✅", "FAILED": "❌", "PENDING": "⏳", "COMPLETED": "✅", "QUEUED": "⏳"}.get(
                t.get("status", "?"), "•"
            )
            _detail = t.get("detail", "") or ""
            _lines.append(f"{_icon} `{t.get('agent_id', '?')}` — {_detail[:60]}")
        return _quick_reply("\n".join(_lines))

    if _HEALTH_RE.search(request.message):
        _up = round(time.time() - _start_time)
        _llm_ok = await _llm_client.is_available() if _llm_client else False
        _drift = _orchestrator.get_drift_report().status.value if _orchestrator else "UNKNOWN"
        _drift_icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(_drift, "•")
        _states = _orchestrator.get_agent_states() if _orchestrator else []
        _active_count = sum(1 for s in _states if s.status == "ACTIVE")
        return _quick_reply(
            f"**System Health**\n\n"
            f"{'✅' if _llm_ok else '❌'} Ollama: {'online' if _llm_ok else 'offline'}\n"
            f"{_drift_icon} Drift Guard: {_drift}\n"
            f"⏱ Uptime: {_up // 60}m {_up % 60}s\n"
            f"🤖 Agents: {len(_states)} registered, {_active_count} active\n"
            f"🛠 Tools: {len(logger.get_recent_tool_logs(10000))} executions logged"
        )

    if _TOOL_LIST_RE.search(request.message):
        from backend.tools import get_tool_definitions
        _tools = get_tool_definitions()
        _lines = [f"**Available Tools** ({len(_tools)} native + 26 MCP via Docker)\n"]
        for t in _tools:
            _lines.append(f"• `{t.name}` — {t.description[:60]}")
        return _quick_reply("\n".join(_lines))

    if _SKILL_LIST_RE.search(request.message):
        from backend.skills.registry import SkillRegistry
        _reg = SkillRegistry()
        _skills = _reg.list_skills()
        _enabled = [s for s in _skills if (s.get("enabled", True) if isinstance(s, dict) else getattr(s, "enabled", True))]
        _lines = [f"**Skills** ({len(_enabled)}/{len(_skills)} enabled)\n"]
        for s in _enabled[:20]:
            _lines.append(f"• `{s.get('id', s.get('skill_id', '?'))}` — {s.get('name', s.get('skill_name', '?'))}")
        return _quick_reply("\n".join(_lines), agent="knowledge_agent")

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
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=None,
                conversation_id=None,
                run_id=None,
                message_id=None,
                sources=[],
                model_used=None,
                routing_method="direct",
            )

    # ── Lex Router: auto-resolve agent when agent_id is "auto" ───────
    resolved_agent_id = request.agent_id
    routing_meta: dict[str, Any] = {}
    if request.agent_id == "auto":
        from backend.orchestrator.lex_router import resolve_agent

        routing_meta = await resolve_agent(request.message)
        resolved_agent_id = routing_meta["agent_id"]

    # ── WebGen intent: route any "build/make/create X website" to the pipeline ──
    import re as _re_wg
    _WEBGEN_RE = _re_wg.compile(
        r'\b(make|build|create|generate|design|develop|spin\s+up|code)\b'
        r'(?:\s+(?:me|us|a|an|the|my|our|their|one))?\s*'
        r'(?:[\w\s&\'\-]{0,40}?)\s*'
        r'(?:website|web\s*site|web\s*app|landing\s*page|homepage|web\s*page|site\b)',
        _re_wg.IGNORECASE,
    )
    # ── Agent-name guard: if the user names any agent, skip direct webgen ──
    # Source: 11 valid agent IDs from copilot-instructions.md
    _AGENT_NAME_RE = _re_wg.compile(
        r'\b(soul[\s_]core|devops[\s_]agent|monitor[\s_]agent|self[\s_]healer[\s_]?agent|'
        r'code[\s_]review[\s_]agent|security[\s_]agent|data[\s_]agent|comms[\s_]agent|'
        r'cs[\s_]agent|it[\s_]agent|knowledge[\s_]agent|ocr[\s_]agent|'
        r'(soul|devops|monitor|security|data|comms|cs|it|knowledge|ocr)\s+agent|'
        r'\w[\w\s]{1,30}agent(?!\s*(?:website|web|app|page|site)))\b',
        _re_wg.IGNORECASE,
    )
    # ── Clone intent: URL + clone/copy/remake verb → webgen pipeline ──
    _CLONE_INTENT_RE = _re_wg.compile(
        r'\b(clone|copy|remake|rebuild|reverse[\s\-]?engineer)\b[\s\S]*https?://',
        _re_wg.IGNORECASE,
    )
    # Also match the reverse order: URL then clone verb
    _CLONE_INTENT_REV_RE = _re_wg.compile(
        r'https?://[\S]+[\s\S]*\b(clone|copy|remake|rebuild|reverse[\s\-]?engineer)\b',
        _re_wg.IGNORECASE,
    )
    _msg_lower = request.message.lower()
    _is_webgen_intent = (
        _WEBGEN_RE.search(request.message)
        or _CLONE_INTENT_RE.search(request.message)
        or _CLONE_INTENT_REV_RE.search(request.message)
    )
    # Fire the webgen interceptor for the orchestrator surfaces (auto, soul_core/Orchad).
    # The Orchad chat panel posts agent_id="soul_core" directly, so previously this
    # branch was skipped and website requests fell through to a plain LLM reply.
    _ORCHESTRATOR_AGENTS = {"auto", "soul_core", "orchad"}
    if (
        request.agent_id in _ORCHESTRATOR_AGENTS
        and _is_webgen_intent
        and not _AGENT_NAME_RE.search(request.message)
    ):
        try:
            from backend.routes.webgen_builder import GenerateSiteRequest, _run_generate_site
            from backend.webgen.site_store import WebgenRunStore
            from backend.webgen.models import WebgenRunState, WebgenRunStatus
            import re as _re

            # ── Clone URL detection — "clone https://example.com" / "copy https://..." ──
            _clone_url: str | None = None
            _url_match = _re_wg.search(r'https?://[^\s"\']+', request.message)
            _clone_intent = bool(_re_wg.search(r'\b(clone|copy|remake|rebuild|reverse[\s\-]?engineer|like)\b', request.message, _re_wg.IGNORECASE))
            if _url_match and (_clone_intent or _CLONE_INTENT_RE.search(request.message) or _CLONE_INTENT_REV_RE.search(request.message)):
                _clone_url = _url_match.group(0).rstrip('.,;)')

            # Best-effort business name extraction from natural language
            _biz_name = "Business"
            # Pattern 1: "make/build a [NAME] website" → extract NAME
            _m1 = _re_wg.search(
                r'\b(?:make|build|create|generate|design)\b\s+(?:me\s+)?(?:(?:a|an|the|my|our)\s+)?'
                r'([\w][\w\s&\'\-]{1,39}?)\s+'
                r'(?:website|web\s*site|web\s*app|landing\s*page|homepage|site\b)',
                request.message,
                _re_wg.IGNORECASE,
            )
            if _m1:
                _biz_name = _m1.group(1).strip()
            else:
                # Pattern 2: "for a/the [NAME]" at natural break
                _m2 = _re_wg.search(
                    r'(?:for\s+(?:a|the|my|our)\s+|for\s+)([a-zA-Z0-9][\w\s&\'\-]{1,39}?)(?:\s+(?:and|to|using|https?)|\s*$|\s*[,.])',
                    request.message,
                    _re_wg.IGNORECASE,
                )
                if _m2:
                    _biz_name = _m2.group(1).strip()
                else:
                    # Pattern 3: fallback — grab word(s) after "website"
                    _m3 = _re_wg.search(r'website\s+(?:for\s+)?([\w][\w\s&\'\-]{1,39})', request.message, _re_wg.IGNORECASE)
                    if _m3:
                        _biz_name = _m3.group(1).strip()

            _wg_payload = GenerateSiteRequest(
                business_name=_biz_name,
                description=request.message[:300],
                tone="professional",
                clone_url=_clone_url,
            )

            # ── Run pipeline async so /chat returns immediately ──
            _wg_run_id = str(uuid.uuid4())[:12]
            _wg_run_store = WebgenRunStore()
            _initial_run = WebgenRunState(
                run_id=_wg_run_id,
                business_name=_biz_name,
                clone_url=_clone_url or "",
                current_phase="clone_recon" if _clone_url else "planning",
                total=8 if _clone_url else 6,
            )
            _wg_run_store.save(_initial_run)

            async def _run_webgen_bg(payload: GenerateSiteRequest, run_id: str, biz_name: str, clone_url_: str | None) -> None:
                _rs = _wg_run_store
                try:
                    result = await _run_generate_site(payload, run_id=run_id, run_store=_rs)
                    _run = _rs.load(run_id)
                    if _run:
                        _run.status = WebgenRunStatus.COMPLETED
                        _run.project_id = result.get("project_id", "")
                        _run.project_slug = result.get("project_slug", "")
                        _run.current_phase = "export"
                        _rs.save(_run)
                    task_tracker.emit_activity("WEBGEN_COMPLETE", {
                        "run_id": run_id,
                        "project_id": result.get("project_id", ""),
                        "project_slug": result.get("project_slug", ""),
                        "preview_file": result.get("preview_file", ""),
                        "pages": result.get("pages", []),
                        "business_name": biz_name,
                        "clone_url": clone_url_ or "",
                        "status": "success",
                        "timestamp": datetime.now(UTC_TZ).isoformat(),
                    })
                except Exception as exc:
                    logger.warning(f"[WebGen] Background pipeline failed: {exc}")
                    _run = _rs.load(run_id)
                    if _run:
                        _run.status = WebgenRunStatus.FAILED
                        _run.error = str(exc)[:300]
                        _rs.save(_run)
                    task_tracker.emit_activity("WEBGEN_COMPLETE", {
                        "run_id": run_id,
                        "status": "failed",
                        "error": str(exc)[:300],
                        "timestamp": datetime.now(UTC_TZ).isoformat(),
                    })

            asyncio.create_task(_run_webgen_bg(_wg_payload, _wg_run_id, _biz_name, _clone_url))

            return ChatResponse(
                agent_id="webgen",
                message=(
                    f"Building website for **{_biz_name}**…\n\n"
                    + (f"Cloning from: {_clone_url}\n" if _clone_url else "")
                    + f"Run ID: `{_wg_run_id}`\n\n"
                    "Follow progress in the live activity stream. "
                    "The result will appear automatically when the build completes."
                ),
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=None,
                conversation_id=None,
                run_id=_wg_run_id,
                message_id=None,
                sources=[],
                model_used=None,
                routing_method="webgen_intent",
            )
        except Exception as _wg_exc:
            logger.warning(f"[WebGen] Pipeline failed, falling through to agent: {_wg_exc}")

    # ── Discord channel query intent ─────────────────────────────────────────
    # Intercepts questions like "what's in #intel-news?" or "show discord news"
    # and returns the durable post history log directly — no Ollama needed.
    _DISCORD_CHANNEL_QUERY_RE = _re_wg.compile(
        r'\b(?:what(?:\'s| is| was| has)|show|get|fetch|read|list|tell me|summarize|latest)\b'
        r'.{0,40}'
        r'\b(?:intel.?news|news.?intel|discord.*news|security.?alerts?|content.?report|comment.?farm'
        r'|#intel|#news|discord\s+channel|posted\s+to\s+discord|in\s+discord)\b',
        _re_wg.IGNORECASE,
    )
    if (
        _DISCORD_CHANNEL_QUERY_RE.search(request.message)
        and request.agent_id in _ORCHESTRATOR_AGENTS
        and not _is_webgen_intent
    ):
        try:
            from backend.discord_bot import get_discord_post_history as _gdph

            # Detect which channel they're asking about
            _disc_channel = "news-intel"
            if _re_wg.search(r'security.?alert', request.message, _re_wg.IGNORECASE):
                _disc_channel = "security-alerts"
            elif _re_wg.search(r'content.?report', request.message, _re_wg.IGNORECASE):
                _disc_channel = "content-report"
            elif _re_wg.search(r'comment.?farm', request.message, _re_wg.IGNORECASE):
                _disc_channel = "comment-farm"

            _disc_records = await asyncio.wait_for(
                asyncio.to_thread(_gdph, channel_name=_disc_channel, limit=10),
                timeout=3.0,
            )

            if _disc_records:
                _disc_lines = []
                for _r in _disc_records[:8]:
                    _t = _r.get("title") or _r.get("headline") or _r.get("content", "")[:100]
                    _cat = _r.get("category", "")
                    _url = _r.get("source_url", "")
                    _ts = (_r.get("timestamp") or _r.get("logged_at", ""))[:10]
                    _line = f"• [{_cat}] {_t}" if _cat else f"• {_t}"
                    if _url:
                        _line += f" ({_url})"
                    if _ts:
                        _line += f" — {_ts}"
                    _disc_lines.append(_line)
                _disc_response = (
                    f"Here's what's been posted to **#{_disc_channel}** by the Agentop bot:\n\n"
                    + "\n".join(_disc_lines)
                )
            else:
                _disc_response = (
                    f"No posts found in **#{_disc_channel}** yet. "
                    "The news intel poller runs hourly — check back after the next poll cycle, "
                    "or trigger `/news` in Discord to push items now."
                )

            _disc_conv_id = task_tracker.create_or_attach_conversation(
                agent_id="comms_agent",
                conversation_id=request.conversation_id,
            )
            task_tracker.append_message(_disc_conv_id, "user", request.message, "comms_agent", None)
            task_tracker.append_message(_disc_conv_id, "assistant", _disc_response, "comms_agent", None)
            return ChatResponse(
                agent_id="comms_agent",
                message=_disc_response,
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=None,
                conversation_id=_disc_conv_id,
                routing_method="discord_channel_query",
            )
        except Exception as _disc_exc:
            logger.warning(f"[DiscordChannelQuery] Failed: {_disc_exc}")
            # Fall through to full orchestrator

    # ── Content pipeline intent: split into lightweight text path and heavy media path ──
    #
    # HEAVY path  — explicit video/media keywords only. Routes into ContentPipeline
    #               (long-running, blocks workers if subprocess not async).
    # LIGHTWEIGHT path — text, news, caption, carousel, plain "post". Returns quickly
    #                    via the lightweight social handler below. Does NOT enter
    #                    ContentPipeline so it cannot cause 504s on plain social requests.
    #
    # Both only fire on orchestrator surfaces and only when no agent name is mentioned.
    _HEAVY_MEDIA_INTENT_RE = _re_wg.compile(
        r'\b(?:make|create|produce|generate|do)\b\s*'
        r'(?:me\s+)?(?:a|an|the|some)?\s*'
        r'(tiktok\s+video|tik\s*tok\s+video|reel|reels|short(?:\s+video)?|shorts|'
        r'youtube\s*short|avatar\s+video|talking[- ]head|lip[- ]sync|'
        r'video(?:\s+clip)?|clip)\b',
        _re_wg.IGNORECASE,
    )
    _LIGHTWEIGHT_SOCIAL_INTENT_RE = _re_wg.compile(
        r'\b(?:make|create|produce|generate|post|publish|draft|write|do)\b\s*'
        r'(?:me\s+)?(?:a|an|the|some)?\s*'
        r'(?:(?:news\s+)?post|caption|carousel|ig\s+post|instagram\s+post|'
        r'piece\s+of\s+content|social\s+post|text\s+post)\b',
        _re_wg.IGNORECASE,
    )
    _heavy_media_match = _HEAVY_MEDIA_INTENT_RE.search(request.message) if request.agent_id in _ORCHESTRATOR_AGENTS else None
    _lightweight_social_match = (
        _LIGHTWEIGHT_SOCIAL_INTENT_RE.search(request.message)
        if request.agent_id in _ORCHESTRATOR_AGENTS and not _heavy_media_match
        else None
    )

    # ── Numeric continuation path — "1"…"5" follow-ups continuing a Social draft ──
    _LW_SOCIAL_CONTINUATION_RE = _re_wg.compile(r'^\s*[1-5]\s*$')
    _lw_continuation_match = (
        _LW_SOCIAL_CONTINUATION_RE.match(request.message)
        if request.agent_id in _ORCHESTRATOR_AGENTS
        and not _lightweight_social_match
        and not _heavy_media_match
        and request.conversation_id
        else None
    )
    if _lw_continuation_match and not _is_webgen_intent:
        try:
            _lw_choice = request.message.strip()
            _lw_history = task_tracker.get_messages(
                request.conversation_id,  # type: ignore[arg-type]
                limit=20,
            )
            # Find the last assistant message that contained numbered suggestions
            _lw_suggestion_msg: str | None = None
            for _lw_hist_item in reversed(_lw_history):
                if (
                    _lw_hist_item.get("role") == "assistant"
                    and _re_wg.search(r'[1-5][\.\)]\s', _lw_hist_item.get("content", ""))
                    and "reply with a number" in _lw_hist_item.get("content", "").lower()
                ):
                    _lw_suggestion_msg = _lw_hist_item["content"]
                    break
            if _lw_suggestion_msg:
                # Extract the chosen option text
                _lw_option_re = _re_wg.compile(
                    rf'(?:^|\n)\s*{_re_wg.escape(_lw_choice)}[\.\)]\s+(.+?)(?=\n\s*[1-5][\.\)]|\Z)',
                    _re_wg.DOTALL | _re_wg.MULTILINE,
                )
                _lw_option_m = _lw_option_re.search(_lw_suggestion_msg)
                _lw_option_text = _lw_option_m.group(1).strip() if _lw_option_m else f"option {_lw_choice}"
                _lw_continuation_prompt = (
                    f"The user chose option {_lw_choice} from the suggestions you just provided.\n"
                    f"Option {_lw_choice}: {_lw_option_text}\n\n"
                    f"Now write the FULL ready-to-post carousel (5–7 slides) for this topic. "
                    f"Each slide: bold headline + 1–2 sentence body. "
                    f"Output the content only — no preamble or explanations."
                )
            else:
                # No prior suggestion found — fall through to full orchestrator
                raise ValueError("No prior suggestion message found for continuation")

            _lw_cont_selection = _resolve_chat_model_selection("comms_agent", request.model)
            _lw_cont_ctx: dict[str, Any] = {
                **dict(request.context),
                "lightweight_social": True,
                "_model_selection": _lw_cont_selection,
                **(({"model": _lw_cont_selection.get("requested_model")}) if _lw_cont_selection.get("requested_model") else {}),
            }
            _lw_cont_result = await _orchestrator.process_message(
                agent_id="comms_agent",
                message=_lw_continuation_prompt,
                context=_lw_cont_ctx,
            )
            _lw_cont_raw = _lw_cont_result.get("response", "")
            try:
                import json as _json_c
                _lw_cont_parsed = _json_c.loads(_lw_cont_raw)
                _lw_cont_response = _lw_cont_parsed.get("content") or _lw_cont_raw
            except Exception:
                _lw_cont_response = _lw_cont_raw
            if isinstance(_lw_cont_response, str):
                _lw_cont_response = _lw_cont_response.replace("\\n", "\n")

            _lw_cont_ordo_raw = _lw_cont_result.get("ordo_trace")
            _lw_cont_ordo = OrdoTrace(**_lw_cont_ordo_raw) if isinstance(_lw_cont_ordo_raw, dict) else None
            _lw_cont_model_meta = _merge_model_execution(_lw_cont_result, _lw_cont_selection)
            _lw_cont_message_meta = {
                **_lw_cont_model_meta,
                "routing_method": "lightweight_social",
            }

            _lw_cont_conv_id = task_tracker.create_or_attach_conversation(
                agent_id="comms_agent",
                conversation_id=request.conversation_id,
            )
            task_tracker.append_message(
                _lw_cont_conv_id,
                "user",
                request.message,
                "comms_agent",
                None,
                message_meta=_lw_cont_message_meta,
            )
            task_tracker.append_message(
                _lw_cont_conv_id,
                "assistant",
                _lw_cont_response,
                "comms_agent",
                None,
                ordo_trace=_lw_cont_ordo_raw if isinstance(_lw_cont_ordo_raw, dict) else None,
                message_meta=_lw_cont_message_meta,
            )
            _emit_llm_response_event(
                agent_id="comms_agent",
                message=_lw_cont_response,
                model_meta=_lw_cont_model_meta,
                routing_method="lightweight_social",
            )
            return ChatResponse(
                agent_id="comms_agent",
                message=_lw_cont_response,
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=_lw_cont_ordo,
                conversation_id=_lw_cont_conv_id,
                run_id=None,
                message_id=None,
                sources=[],
                selected_model=_lw_cont_model_meta.get("selected_model"),
                answering_model=_lw_cont_model_meta.get("answering_model"),
                runtime_model=_lw_cont_model_meta.get("runtime_model"),
                execution_role=_lw_cont_model_meta.get("execution_role"),
                model_source=_lw_cont_model_meta.get("model_source"),
                model_used=_lw_cont_model_meta.get("model_used"),
                routing_method="lightweight_social",
            )
        except Exception as _lw_cont_exc:
            logger.warning(f"[LightweightSocialContinuation] Failed, falling through: {_lw_cont_exc}")
        # Fall through only on error

    # Lightweight social path — text/news/caption posts, dispatches to comms_agent
    if (
        _lightweight_social_match
        and not _is_webgen_intent
        and not _AGENT_NAME_RE.search(request.message)
    ):
        try:
            from backend.routes.news import get_latest_news as _gln  # type: ignore[attr-defined]

            _lw_topic_m = _re_wg.search(r'\babout\s+(.+?)(?:[.?!]|$)', request.message, _re_wg.IGNORECASE)
            _lw_topic = _lw_topic_m.group(1).strip() if _lw_topic_m else None

            # Collect news items — prefer Discord-posted news if "discord" mentioned
            _lw_news_lines: list[str] = []
            _wants_discord_news = bool(_re_wg.search(r'\bdiscord\b', request.message, _re_wg.IGNORECASE))
            if _wants_discord_news:
                try:
                    from backend.discord_bot import get_discord_post_history as _gdph
                    _disc_posts = await asyncio.wait_for(
                        asyncio.to_thread(_gdph, event_type="DISCORD_NEWS_POSTED", limit=5),
                        timeout=3.0,
                    )
                    for _dp in _disc_posts[:5]:
                        # log saves 'title'; fall back through 'headline' and 'content'
                        _headline = _dp.get("title") or _dp.get("headline") or _dp.get("content", "")[:120]
                        if _headline:
                            _lw_news_lines.append(f"• {_headline}")
                except Exception:
                    pass

            if not _lw_news_lines:
                try:
                    _lw_result = await asyncio.wait_for(
                        _gln(limit=5, high_relevance_only=False, topic=_lw_topic),
                        timeout=5.0,
                    )
                    _lw_items = _lw_result.get("items", []) if isinstance(_lw_result, dict) else _lw_result
                    for _it in _lw_items[:5]:
                        _title = _it.get("title", "")
                        _summary = _it.get("summary", "")
                        if _title:
                            _lw_news_lines.append(f"• {_title}" + (f" — {_summary[:100]}" if _summary else ""))
                except Exception:
                    pass

            # Detect content format (carousel vs caption vs post)
            _lw_format = "Instagram carousel"
            if _re_wg.search(r'\bcaption\b', request.message, _re_wg.IGNORECASE):
                _lw_format = "Instagram caption"
            elif _re_wg.search(r'\bpost\b', request.message, _re_wg.IGNORECASE):
                _lw_format = "social media post"

            if _lw_news_lines:
                _news_block = "\n\nNews items to use:\n" + "\n".join(_lw_news_lines)
                _enriched_msg = (
                    f"Write a {_lw_format} based on the following request: {request.message}"
                    f"{_news_block}\n\n"
                    f"Format: produce ready-to-post copy only. "
                    f"For a carousel, write 5–7 slides each with a bold headline and 1–2 sentence body. "
                    f"For a caption, write the full caption with hashtags. "
                    f"Do not explain what you are doing — just output the content."
                )
            else:
                # No live news — surface suggestions and offer to write
                _enriched_msg = (
                    f"The user wants to: {request.message}\n\n"
                    f"No live news items are loaded right now. Do the following:\n"
                    f"1. Suggest 4–5 recent article topics or trending themes (AI, tech, business, or relevant niche) "
                    f"that would make great {_lw_format} content.\n"
                    f"2. After each suggestion write a one-line 'Slide 1 hook' showing what the opening slide could say.\n"
                    f"3. End with exactly this line: "
                    f"'Reply with a number (1–5) and I'll write the full carousel instantly.'\n"
                    f"Keep it concise — no extra commentary or explanations."
                )

            task_tracker.emit_activity("LIGHTWEIGHT_SOCIAL", {
                "topic": _lw_topic or request.message[:100],
                "format": _lw_format,
                "news_items": len(_lw_news_lines),
                "timestamp": datetime.now(UTC_TZ).isoformat(),
            })

            # Dispatch directly to comms_agent — bypass soul_core
            # Resolve the model: explicit request.model > persisted comms_agent override
            _lw_selection = _resolve_chat_model_selection("comms_agent", request.model)
            _lw_model: str | None = _lw_selection.get("requested_model")
            _lw_ctx: dict[str, Any] = {
                **dict(request.context),
                "lightweight_social": True,
                "_model_selection": _lw_selection,
                **(({"model": _lw_model}) if _lw_model else {}),
            }
            _LW_TIMEOUT_SENTINEL = "Error: Agent executor timed out. Please try again."

            async def _lw_call(
                msg: str,
                override_model: str | None,
                selection: dict[str, Any],
            ) -> dict[str, Any]:
                _ctx = {
                    **_lw_ctx,
                    "_model_selection": selection,
                    **(({"model": override_model}) if override_model else {}),
                }
                return await _orchestrator.process_message(
                    agent_id="comms_agent",
                    message=msg,
                    context=_ctx,
                )

            _lw_result_agent = await _lw_call(_enriched_msg, _lw_model, _lw_selection)
            _lw_response_raw = _lw_result_agent.get("response", "")

            # Retry once on step-1 timeout with a simplified prompt and fallback model
            if _lw_response_raw == _LW_TIMEOUT_SENTINEL:
                _lw_fallback_model: str | None = None
                if _lw_model:
                    from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY as _UMR
                    _lw_spec = _UMR.get(_lw_model)
                    _lw_fallback_model = (
                        _lw_spec.fallback_chain[0] if _lw_spec and _lw_spec.fallback_chain else None
                    )
                _lw_fallback_model = _lw_fallback_model or "llama3.2:1b"
                _lw_simple_msg = (
                    f"Write a brief {_lw_format} about: "
                    + ("; ".join(ln.lstrip("• ") for ln in _lw_news_lines[:3]) if _lw_news_lines else request.message)
                )
                _lw_retry_selection = {
                    **_lw_selection,
                    "requested_model": _lw_fallback_model,
                }
                _lw_retry_result = await _lw_call(_lw_simple_msg, _lw_fallback_model, _lw_retry_selection)
                _lw_retry_raw = _lw_retry_result.get("response", "")
                if _lw_retry_raw and _lw_retry_raw != _LW_TIMEOUT_SENTINEL:
                    _lw_result_agent = _lw_retry_result
                    _lw_response_raw = _lw_retry_raw
                    _lw_model = _lw_fallback_model
                else:
                    _lw_response_raw = (
                        "The social content agent timed out. "
                        "Try selecting a lighter model (e.g. llama3.2:1b) in the Social card and retry."
                    )

            # comms_agent may return schema-constrained JSON — extract "content" field if present
            try:
                import json as _json
                _lw_parsed = _json.loads(_lw_response_raw)
                _lw_response = _lw_parsed.get("content") or _lw_response_raw
            except Exception:
                _lw_response = _lw_response_raw
            # Replace literal \n sequences with real newlines
            if isinstance(_lw_response, str):
                _lw_response = _lw_response.replace("\\n", "\n")

            # Forward Ordo trace from the orchestrator result
            _lw_ordo_raw = _lw_result_agent.get("ordo_trace")
            _lw_ordo = OrdoTrace(**_lw_ordo_raw) if isinstance(_lw_ordo_raw, dict) else None
            _lw_model_meta = _merge_model_execution(_lw_result_agent, _lw_selection)
            _lw_message_meta = {
                **_lw_model_meta,
                "routing_method": "lightweight_social",
            }

            _lw_conv_id = task_tracker.create_or_attach_conversation(
                agent_id="comms_agent",
                conversation_id=request.conversation_id,
            )
            task_tracker.append_message(
                _lw_conv_id,
                "user",
                request.message,
                "comms_agent",
                None,
                message_meta=_lw_message_meta,
            )
            task_tracker.append_message(
                _lw_conv_id,
                "assistant",
                _lw_response,
                "comms_agent",
                None,
                ordo_trace=_lw_ordo_raw if isinstance(_lw_ordo_raw, dict) else None,
                message_meta=_lw_message_meta,
            )
            _emit_llm_response_event(
                agent_id="comms_agent",
                message=_lw_response,
                model_meta=_lw_model_meta,
                routing_method="lightweight_social",
            )
            return ChatResponse(
                agent_id="comms_agent",
                message=_lw_response,
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=_lw_ordo,
                conversation_id=_lw_conv_id,
                run_id=None,
                message_id=None,
                sources=[],
                selected_model=_lw_model_meta.get("selected_model"),
                answering_model=_lw_model_meta.get("answering_model"),
                runtime_model=_lw_model_meta.get("runtime_model"),
                execution_role=_lw_model_meta.get("execution_role"),
                model_source=_lw_model_meta.get("model_source"),
                model_used=_lw_model_meta.get("model_used"),
                routing_method="lightweight_social",
            )
        except Exception as _lw_exc:
            logger.warning(f"[LightweightSocial] Failed, falling through to orchestrator: {_lw_exc}")
        # Fall through only on error

    _content_match = _heavy_media_match  # alias for the block below
    if (
        _content_match
        and not _is_webgen_intent  # webgen wins if both match
        and not _AGENT_NAME_RE.search(request.message)
    ):
        try:
            from backend.content.job_store import job_store as _job_store
            from backend.content.pipeline import ContentPipeline as _ContentPipeline
            from backend.content.video_job import JobStatus as _JobStatus, VideoJob as _VideoJob
            from backend.llm import OllamaClient as _OllamaClient

            # Best-effort topic extraction: text after "about" or after the content noun.
            _topic = ""
            _topic_m = _re_wg.search(r'\babout\s+(.+?)(?:[.?!]|$)', request.message, _re_wg.IGNORECASE)
            if _topic_m:
                _topic = _topic_m.group(1).strip()
            else:
                _topic_m = _re_wg.search(r'\bon\s+(.+?)(?:[.?!]|$)', request.message, _re_wg.IGNORECASE)
                if _topic_m:
                    _topic = _topic_m.group(1).strip()
            if not _topic:
                _topic = request.message[:200]

            _platform_token = _content_match.group(1).lower().replace(" ", "")
            _platforms_map = {
                "tiktokvideo": ["tiktok"], "tiktokvideo": ["tiktok"],
                "reel": ["instagram"], "reels": ["instagram"],
                "short": ["youtube_shorts"], "shorts": ["youtube_shorts"],
                "shortvideo": ["youtube_shorts"],
                "youtubeshort": ["youtube_shorts"],
                "avatarvideo": ["instagram", "tiktok", "youtube_shorts"],
                "talkingheat": ["instagram", "tiktok", "youtube_shorts"],
                "videoclip": ["instagram", "tiktok", "youtube_shorts"],
                "video": ["instagram", "tiktok", "youtube_shorts"],
                "clip": ["instagram", "tiktok", "youtube_shorts"],
            }
            _targets = _platforms_map.get(_platform_token, ["instagram", "tiktok", "youtube_shorts"])

            _job = _VideoJob(
                topic=_topic,
                status=_JobStatus.IDEA_APPROVED,
                platform_targets=_targets,
                source="orchad_chat",
            )
            _job_store.save(_job)

            _content_run_id = _job.job_id

            async def _run_content_bg(_jid: str) -> None:
                try:
                    pipeline = _ContentPipeline(_OllamaClient())
                    # Bound to 30 minutes. subprocess calls inside agents are wrapped
                    # in asyncio.to_thread() so the event loop stays responsive.
                    results = await asyncio.wait_for(pipeline.run_full(), timeout=1800)
                    task_tracker.emit_activity("CONTENT_PIPELINE_COMPLETE", {
                        "job_id": _jid,
                        "results": results,
                        "status": "success",
                        "timestamp": datetime.now(UTC_TZ).isoformat(),
                    })
                except asyncio.TimeoutError:
                    logger.warning(f"[Content] Pipeline timed out after 30 min for job {_jid}")
                    task_tracker.emit_activity("CONTENT_PIPELINE_COMPLETE", {
                        "job_id": _jid,
                        "status": "failed",
                        "error": "Pipeline timed out after 30 minutes",
                        "timestamp": datetime.now(UTC_TZ).isoformat(),
                    })
                except Exception as exc:
                    logger.warning(f"[Content] Background pipeline failed: {exc}")
                    task_tracker.emit_activity("CONTENT_PIPELINE_COMPLETE", {
                        "job_id": _jid,
                        "status": "failed",
                        "error": str(exc)[:300],
                        "timestamp": datetime.now(UTC_TZ).isoformat(),
                    })

            asyncio.create_task(_run_content_bg(_content_run_id))

            return ChatResponse(
                agent_id="content_pipeline",
                message=(
                    f"Spinning up content for **{_topic}**\n\n"
                    f"Targets: {', '.join(_targets)}\n"
                    f"Job ID: `{_content_run_id}`\n\n"
                    "Watch the activity stream — script → voice → video → QA → publish."
                ),
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=None,
                conversation_id=None,
                run_id=_content_run_id,
                message_id=None,
                sources=[],
                model_used=None,
                routing_method="content_intent",
            )
        except Exception as _ct_exc:
            logger.warning(f"[Content] Pipeline failed, falling through to agent: {_ct_exc}")

    # ── Discord intent ──────────────────────────────────────────────────────────
    # Matches both forms:
    #   (a) "discord (bot)? (post|send|…) <text>"  — discord first
    #   (b) "(post|send|…) <text> (to|from|on|via|in) discord"  — discord last
    #   (c) "make a post using … from discord / from the discord bot"
    _DISCORD_INTENT_RE = _re_wg.compile(
        r'(?:'
        r'\b(?:tell|have|ask|use)?\s*(?:the\s+)?discord(?:\s+bot)?\s+(?:to\s+)?(post|send|announce|message|say|drop|share)\b\s+(.+)'
        r'|'
        r'\b(post|send|share|announce|publish|drop)\b(.+?)\b(?:to|from|on|via|in|using)\b\s*(?:the\s+)?discord(?:\s+bot)?\b'
        r'|'
        r'\bmake\b.{0,30}\bpost\b(.+?)\b(?:from|using|via)\b\s*(?:the\s+)?discord(?:\s+bot)?\b'
        r')',
        _re_wg.IGNORECASE | _re_wg.DOTALL,
    )
    _disc_match = _DISCORD_INTENT_RE.search(request.message) if request.agent_id in _ORCHESTRATOR_AGENTS else None
    if _disc_match and not _AGENT_NAME_RE.search(request.message):
        try:
            from backend import discord_bot as _discord_bot_mod

            # group(2) = text after verb for form (a)
            # group(4) = text between verb and "discord" for form (b)
            # group(5) = text between "post" and "from discord" for form (c)
            # Fall back to full message if no capture matched
            _disc_text = (
                _disc_match.group(2) or _disc_match.group(4) or _disc_match.group(5) or request.message
            ).strip().strip('"\'')
            _bot = getattr(_discord_bot_mod, "_bot_instance", None)
            _content_channel_id = getattr(_discord_bot_mod, "CONTENT_CHANNEL_ID", None)

            if _bot is None or _content_channel_id is None:
                _disc_msg = (
                    "Discord bridge not active — set `DISCORD_BOT_TOKEN` and "
                    "`DISCORD_CONTENT_CHANNEL_ID` in `.env`, then restart the backend."
                )
                _disc_status = "skipped"
            else:
                # The discord bot runs in its OWN event loop (spawned by start_bot()).
                # We must dispatch into that loop via run_coroutine_threadsafe — NOT
                # asyncio.create_task() which would run in FastAPI's loop and hang on
                # discord.py awaits that are bound to the bot's loop.
                def _post_to_discord_thread(text: str, channel_id: int) -> None:
                    import concurrent.futures as _cf
                    try:
                        bot_loop = _bot.loop  # type: ignore[attr-defined]
                        if bot_loop is None or not bot_loop.is_running():
                            logger.warning("[Discord] Bot loop not running — cannot post")
                            return

                        async def _do_send() -> None:
                            ch = _bot.get_channel(channel_id)
                            if ch is None:
                                logger.warning(f"[Discord] Channel {channel_id} not found")
                                return
                            await ch.send(text)
                            task_tracker.emit_activity("DISCORD_POST", {
                                "channel_id": channel_id,
                                "text": text[:200],
                                "status": "success",
                                "timestamp": datetime.now(UTC_TZ).isoformat(),
                            })

                        fut = asyncio.run_coroutine_threadsafe(_do_send(), bot_loop)
                        fut.result(timeout=10)  # wait up to 10s in background thread
                    except Exception as exc:
                        logger.warning(f"[Discord] Post failed: {exc}")

                # Fire-and-forget in a thread so we don't block FastAPI's event loop
                asyncio.get_event_loop().run_in_executor(
                    None, _post_to_discord_thread, _disc_text, _content_channel_id
                )
                _disc_msg = f"Posting to Discord #content channel:\n\n> {_disc_text[:400]}"
                _disc_status = "queued"

            return ChatResponse(
                agent_id="comms_agent",
                message=_disc_msg,
                drift_status=DriftStatus.GREEN,
                timestamp=datetime.now(UTC_TZ),
                ordo_trace=None,
                conversation_id=None,
                run_id=None,
                message_id=None,
                sources=[],
                model_used=None,
                routing_method=f"discord_intent_{_disc_status}",
            )
        except Exception as _disc_exc:
            logger.warning(f"[Discord] Intent handling failed, falling through: {_disc_exc}")

    # ── Model override: inject selected model into agent context ─────
    chat_context: dict[str, Any] = dict(request.context)
    if routing_meta:
        chat_context["routing"] = routing_meta
    _resolved_selection = _resolve_chat_model_selection(resolved_agent_id, request.model)
    chat_context["_model_selection"] = _resolved_selection
    if _resolved_selection.get("requested_model"):
        chat_context["model"] = _resolved_selection["requested_model"]

    # DeerFlow: open run BEFORE execution so timing is accurate
    _run_id_main: str | None = None
    if _execution_recorder:
        _run_id_main = _execution_recorder.start_run(
            agent_id=resolved_agent_id,
            message=request.message,
        )

    from backend.config import CHAT_REQUEST_TIMEOUT_SECONDS as _CHAT_TIMEOUT
    _chat_request_id = str(uuid.uuid4())[:8]
    global _active_user_requests
    _active_user_requests += 1
    try:
        result = await asyncio.wait_for(
            _orchestrator.process_message(
                agent_id=resolved_agent_id,
                message=request.message,
                context=chat_context,
            ),
            timeout=_CHAT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Agent timed out after {int(_CHAT_TIMEOUT)}s — Ollama may be busy with another request. "
                f"Try again in a moment. [ref:{_chat_request_id}]"
            ),
        )
    except ConnectionError as _conn_exc:
        # Ollama is unreachable — surface a structured 503 rather than 500
        write_chat_failure(
            request_id=_chat_request_id,
            user_message=request.message,
            chosen_agent=resolved_agent_id,
            selected_model=_resolved_selection.get("selected_model"),
            last_live_step=None,
            ordo_trace=None,
            error_class="ConnectionError",
            error_detail=str(_conn_exc),
            route_path="/chat",
            pipeline_stage="llm_connect",
        )
        raise HTTPException(
            status_code=503,
            detail=f"LLM service unavailable — Ollama may not be running. [ref:{_chat_request_id}]",
        )
    except Exception as _orch_exc:
        # Unexpected orchestrator failure — log it and re-raise so the catchall fires
        write_chat_failure(
            request_id=_chat_request_id,
            user_message=request.message,
            chosen_agent=resolved_agent_id,
            selected_model=_resolved_selection.get("selected_model"),
            last_live_step=None,
            ordo_trace=None,
            error_class=type(_orch_exc).__name__,
            error_detail=str(_orch_exc),
            route_path="/chat",
            pipeline_stage="orchestrator",
        )
        raise
    finally:
        _active_user_requests -= 1

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

    _ordo_raw = result.get("ordo_trace")
    _ordo = OrdoTrace(**_ordo_raw) if isinstance(_ordo_raw, dict) else None
    _routing_method = routing_meta.get("method") if routing_meta else ("direct" if request.agent_id != "auto" else None)
    _model_meta = _merge_model_execution(result, _resolved_selection)
    _message_meta = {
        **_model_meta,
        "routing_method": _routing_method,
    }

    # ── Persist conversation and messages ────────────────────────────
    _conv_id = task_tracker.create_or_attach_conversation(
        agent_id=resolved_agent_id,
        conversation_id=request.conversation_id,
    )
    task_tracker.append_message(
        conversation_id=_conv_id,
        role="user",
        content=request.message,
        agent_id=resolved_agent_id,
        run_id=_run_id_main,
        message_meta=_message_meta,
    )
    _assistant_msg = result.get("response", "")
    _msg_id = task_tracker.append_message(
        conversation_id=_conv_id,
        role="assistant",
        content=_assistant_msg,
        agent_id=resolved_agent_id,
        run_id=_run_id_main,
        ordo_trace=_ordo_raw if isinstance(_ordo_raw, dict) else None,
        message_meta=_message_meta,
    )
    _emit_llm_response_event(
        agent_id=resolved_agent_id,
        message=_assistant_msg,
        model_meta=_model_meta,
        routing_method=_routing_method,
    )

    return ChatResponse(
        agent_id=resolved_agent_id,
        message=_assistant_msg,
        drift_status=DriftStatus(result.get("drift_status", "GREEN")),
        timestamp=datetime.now(UTC_TZ),
        ordo_trace=_ordo,
        conversation_id=_conv_id,
        run_id=_run_id_main,
        message_id=_msg_id,
        sources=result.get("sources") or [],
        selected_model=_model_meta.get("selected_model"),
        answering_model=_model_meta.get("answering_model"),
        runtime_model=_model_meta.get("runtime_model"),
        execution_role=_model_meta.get("execution_role"),
        model_source=_model_meta.get("model_source"),
        model_used=_model_meta.get("model_used"),
        routing_method=_routing_method,
    )

@app.get("/agents")
async def list_agents(include_factory: bool = False) -> list[dict[str, Any]]:
    """Return the canonical production agent roster.

    Pass ``?include_factory=true`` to also include dynamically created
    factory/debug agents (operator-only surface).
    """
    if not _orchestrator:
        return []
    return [d.model_dump() for d in _orchestrator.get_all_agent_definitions(include_factory=include_factory)]


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    """Return a specific agent's definition and state."""
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    all_defs = {d.agent_id: d for d in _orchestrator.get_all_agent_definitions(include_factory=True)}
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
        save_agent_model_overrides(_agent_model_overrides)
    return {"agent_id": agent_id, "model_id": _agent_model_overrides.get(agent_id, "")}


@app.get("/model-preferences")
async def get_model_preferences() -> dict[str, Any]:
    """Return the canonical team model state for the Command screen."""
    return build_model_preferences_response(
        team_models=_team_model_preferences,
        agent_overrides=_agent_model_overrides,
        fallback_model=OLLAMA_MODEL,
    )


@app.patch("/model-preferences/teams/{team_id}")
async def set_team_model_preference(team_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Persist a shared team model preference and fan it out to mapped agents."""
    if team_id not in EDITABLE_TEAM_AGENT_MAP:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' is not editable")

    model_id = str(body.get("model_id", "")).strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    _team_model_preferences[team_id] = model_id
    save_team_model_preferences(_team_model_preferences)
    for agent_id in EDITABLE_TEAM_AGENT_MAP[team_id]:
        _agent_model_overrides[agent_id] = model_id
    save_agent_model_overrides(_agent_model_overrides)

    response = build_model_preferences_response(
        team_models=_team_model_preferences,
        agent_overrides=_agent_model_overrides,
        fallback_model=OLLAMA_MODEL,
    )
    return response["teams"][team_id]


# ── Conversation history routes ──────────────────────────────────────────


@app.get("/conversations/active")
async def get_active_conversation(agent_id: str = "orchad") -> dict[str, Any]:
    """Return the most recently active conversation for *agent_id*.

    Used by OrchestrationHub to seed its chat history on mount instead of
    relying solely on localStorage.
    """
    conv = task_tracker.get_active_conversation(agent_id)
    if not conv:
        return {"conversation_id": None, "messages": []}
    messages = task_tracker.get_messages(conv["conversation_id"])
    return {**conv, "messages": messages}


@app.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return messages for a conversation oldest-first (up to *limit*)."""
    return task_tracker.get_messages(conversation_id, limit=limit)


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
            yield f'event: connected\ndata: {{"status": "ok", "timestamp": "{datetime.now(UTC_TZ).isoformat()}"}}\n\n'
            while True:
                try:
                    # Wait for next event with timeout for heartbeat
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event.to_sse()
                except TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f'event: heartbeat\ndata: {{"timestamp": "{datetime.now(UTC_TZ).isoformat()}"}}\n\n'
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
    from backend.llm.unified_registry import ModelProvider, UNIFIED_MODEL_REGISTRY, UnifiedModelRouter

    available: list[str] = []
    if _llm_client:
        try:
            available = await _llm_client.list_models()
        except Exception:
            pass
    models = []
    for spec in UNIFIED_MODEL_REGISTRY.values():
        runtime_model_id: str | None = None
        available_locally = False
        if spec.provider == ModelProvider.OLLAMA:
            for candidate in UnifiedModelRouter._local_model_candidates(spec.model_id):
                runtime_model_id = UnifiedModelRouter._match_ollama_model_name(candidate, available)
                if runtime_model_id:
                    available_locally = True
                    break
        models.append(
            {
                "model_id": spec.model_id,
                "display_name": spec.display_name,
                "provider": spec.provider.value,
                "context_window": spec.context_window,
                "input_cost_per_m": spec.input_cost_per_m,
                "output_cost_per_m": spec.output_cost_per_m,
                "supports_tools": spec.supports_tools,
                "best_for": spec.best_for,
                "available_locally": available_locally,
                "runtime_model_id": runtime_model_id,
                "role": spec.role or None,
                "alias_of": spec.alias_of,
            }
        )
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

    # ── Local (Ollama) token counts — captured from every OllamaClient call ──
    import os as _os
    from backend.llm import OllamaClient as _OllamaClient
    local_counts = _OllamaClient.get_token_counts()

    # Cloud router counts (from LLMRouter if available)
    cloud_tokens_in = router_stats.get("tokens_in", 0)
    cloud_tokens_out = router_stats.get("tokens_out", 0)

    # Aggregate: local + cloud
    total_in = local_counts["tokens_in"] + cloud_tokens_in
    total_out = local_counts["tokens_out"] + cloud_tokens_out

    # ── Configured API key status (boolean only — no values exposed) ──
    api_keys_configured = {
        "openrouter": bool(_os.getenv("OPENROUTER_API_KEY", "")),
        "elevenlabs": bool(_os.getenv("ELEVENLABS_API_KEY", "")),
        "fal": bool(_os.getenv("FAL_KEY", "")),
        "tiktok": bool(_os.getenv("TIKTOK_CLIENT_KEY", "") or _os.getenv("TIKTOK_ACCESS_TOKEN", "")),
        "github": bool(_os.getenv("GITHUB_TOKEN", "")),
        "facebook": bool(_os.getenv("FACEBOOK_APP_SECRET", "")),
    }

    return {
        "stats": {
            **router_stats,
            # Merge in local request count so total_requests is accurate
            "total_requests": router_stats.get("total_requests", 0) + local_counts["requests"],
            "local_requests": router_stats.get("local_requests", 0) + local_counts["requests"],
        },
        "cost_log": cost_log,
        "circuit_states": circuit_states,
        "budget": {
            "monthly_limit_usd": LLM_MONTHLY_BUDGET,
            "spent_usd": router_stats.get("estimated_cost_usd", 0),
            "remaining_usd": budget_remaining,
            "percent_used": round((router_stats.get("estimated_cost_usd", 0) / max(LLM_MONTHLY_BUDGET, 0.01)) * 100, 1),
        },
        "tokens": {
            "total_in": total_in,
            "total_out": total_out,
            "total": total_in + total_out,
            "local_in": local_counts["tokens_in"],
            "local_out": local_counts["tokens_out"],
            "local_total": local_counts["total"],
            "cloud_in": cloud_tokens_in,
            "cloud_out": cloud_tokens_out,
            "cloud_total": cloud_tokens_in + cloud_tokens_out,
        },
        "api_keys": api_keys_configured,
    }


@app.get("/llm/openrouter/balance")
async def openrouter_balance() -> dict[str, Any]:
    """
    Fetch the real OpenRouter account credit balance.
    Calls https://openrouter.ai/api/v1/credits — returns actual money in the account.
    """
    import os as _os
    import httpx

    api_key = _os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not configured", "configured": False}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if r.status_code != 200:
            return {"error": f"OpenRouter returned {r.status_code}", "configured": True}
        data = r.json().get("data", r.json())
        total_credits = data.get("total_credits", data.get("limit", None))
        total_usage = data.get("total_usage", data.get("usage", 0.0))
        remaining = (total_credits - total_usage) if total_credits is not None else None
        return {
            "configured": True,
            "total_credits_usd": total_credits,
            "total_usage_usd": round(float(total_usage), 6),
            "remaining_usd": round(float(remaining), 6) if remaining is not None else None,
            "percent_used": round((float(total_usage) / max(float(total_credits), 0.0001)) * 100, 1)
            if total_credits else None,
        }
    except Exception as exc:
        return {"error": str(exc), "configured": True}


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


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, project_type: str = "webgen", _auth: None = Depends(_verify_auth)) -> dict[str, Any]:
    """
    Permanently delete a project and all its files.
    - webgen: removes output/webgen/{project_id}/ directory
    - content: removes backend/memory/content_jobs/{project_id}.json
    - webgen_project: removes backend/memory/webgen_projects/{project_id}.json
    """
    import shutil as _shutil

    # Validate project_id to prevent path traversal
    if not project_id or "/" in project_id or ".." in project_id or project_id.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    if project_type == "webgen":
        target_dir = (PROJECT_ROOT / "output" / "webgen" / project_id).resolve()
        safe_root = (PROJECT_ROOT / "output" / "webgen").resolve()
        if not str(target_dir).startswith(str(safe_root)):
            raise HTTPException(status_code=403, detail="Path traversal not allowed")
        if not target_dir.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        _shutil.rmtree(target_dir)
        return {"deleted": True, "id": project_id, "type": project_type}

    elif project_type == "content":
        target_file = (PROJECT_ROOT / "backend" / "memory" / "content_jobs" / f"{project_id}.json").resolve()
        safe_root = (PROJECT_ROOT / "backend" / "memory" / "content_jobs").resolve()
        if not str(target_file).startswith(str(safe_root)):
            raise HTTPException(status_code=403, detail="Path traversal not allowed")
        if not target_file.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        target_file.unlink()
        return {"deleted": True, "id": project_id, "type": project_type}

    elif project_type == "webgen_project":
        target_file = (PROJECT_ROOT / "backend" / "memory" / "webgen_projects" / f"{project_id}.json").resolve()
        safe_root = (PROJECT_ROOT / "backend" / "memory" / "webgen_projects").resolve()
        if not str(target_file).startswith(str(safe_root)):
            raise HTTPException(status_code=403, detail="Path traversal not allowed")
        if not target_file.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        target_file.unlink()
        return {"deleted": True, "id": project_id, "type": project_type}

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported project type: {project_type}")


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
    return {"reflection": reflection, "trigger": trigger, "timestamp": datetime.now(UTC_TZ).isoformat()}


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


@app.patch("/soul/goals/{goal_id}")
async def soul_update_goal(goal_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """
    Activate or dismiss a pending_review goal.

    body: {"action": "activate" | "dismiss"}
    - activate: sets status to "active" — goal is now visible to agents
    - dismiss: removes the goal entirely
    Only goals with status='pending_review' can be activated this way.
    """
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    action = str(request.get("action", "")).lower()
    if action not in ("activate", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be 'activate' or 'dismiss'")

    soul = _orchestrator._soul_agent  # type: ignore[attr-defined]
    if soul is None:
        raise HTTPException(status_code=503, detail="Soul agent not available")

    from typing import cast as _cast
    _raw = soul.read_memory(soul.GOALS_KEY)
    goals: list[dict[str, Any]] = _cast(list[dict[str, Any]], _raw) if isinstance(_raw, list) else []

    updated: dict[str, Any] | None = None
    new_goals: list[dict[str, Any]] = []
    for g in goals:
        if g.get("id") == goal_id:
            if action == "activate":
                g = {**g, "status": "active"}
                updated = g
                new_goals.append(g)
            # dismiss: skip (don't append)
        else:
            new_goals.append(g)

    if updated is None and action == "activate":
        raise HTTPException(status_code=404, detail=f"Goal {goal_id!r} not found")

    soul.write_memory(soul.GOALS_KEY, new_goals)
    soul._active_goals = [g for g in new_goals if not g.get("completed") and g.get("status") != "pending_review"]

    return {"goal_id": goal_id, "action": action, "goal": updated}


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
