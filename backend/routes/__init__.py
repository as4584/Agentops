"""FastAPI route modules for Agentop."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def register_all_routes(app: "FastAPI", gateway_enabled: bool = False) -> None:
    """Register all Agentop route modules with the FastAPI application.

    Extracted from ``backend.server`` (Sprint 6) so that route wiring is
    a single, testable, side-effect-free function call.

    Args:
        app: The FastAPI application instance.
        gateway_enabled: When True, include the OpenAI-compatible gateway
            and admin routers (controlled by ``GATEWAY_ENABLED`` config).
    """
    from backend.routes.a2ui import router as a2ui_router
    from backend.routes.agent_control import a2a_router, router as agent_control_router
    from backend.routes.agent_factory import router as agent_factory_router
    from backend.routes.auth_oauth import router as auth_oauth_router
    from backend.routes.content_pipeline import router as content_pipeline_router
    from backend.routes.customers import router as customers_router
    from backend.routes.gsd import router as gsd_router
    from backend.routes.higgsfield import router as higgsfield_router
    from backend.routes.knowledge import router as knowledge_router
    from backend.routes.llm_registry import router as llm_registry_router
    from backend.routes.marketing import router as marketing_router
    from backend.routes.mcp_server import router as mcp_router
    from backend.routes.memory_management import router as memory_management_router
    from backend.routes.ml import router as ml_router
    from backend.routes.ml_eval import router as ml_eval_router
    from backend.routes.ml_training import router as ml_training_router
    from backend.routes.ml_webgen import router as ml_webgen_router
    from backend.routes.network import router as network_router
    from backend.routes.news import router as news_router
    from backend.routes.sandbox import router as sandbox_router
    from backend.routes.schedule_routes import router as scheduler_router
    from backend.routes.security_alerts import router as security_alerts_router
    from backend.routes.skills import router as skills_router
    from backend.routes.social_media import router as social_media_router
    from backend.routes.studio import router as studio_router
    from backend.routes.task_management import router as task_management_router
    from backend.routes.webgen_builder import router as webgen_builder_router
    from backend.routes.webhooks import router as webhooks_router
    from backend.orchestrator.openclaw_bridge import router as openclaw_router

    app.include_router(agent_control_router)
    app.include_router(a2a_router)
    app.include_router(task_management_router)
    app.include_router(memory_management_router)
    app.include_router(content_pipeline_router)
    app.include_router(customers_router)
    app.include_router(llm_registry_router)
    app.include_router(webgen_builder_router)
    app.include_router(marketing_router)
    app.include_router(sandbox_router)
    app.include_router(scheduler_router)
    app.include_router(webhooks_router)
    app.include_router(skills_router)
    app.include_router(higgsfield_router)
    app.include_router(knowledge_router)
    app.include_router(a2ui_router)
    app.include_router(auth_oauth_router)
    app.include_router(social_media_router)
    app.include_router(gsd_router)
    app.include_router(ml_router)
    app.include_router(ml_eval_router)
    app.include_router(ml_training_router)
    app.include_router(ml_webgen_router)
    app.include_router(agent_factory_router)
    app.include_router(openclaw_router)
    app.include_router(mcp_router)
    app.include_router(security_alerts_router)
    app.include_router(network_router)
    app.include_router(news_router)
    app.include_router(studio_router)

    if gateway_enabled:
        from backend.routes.gateway import router as gateway_router
        from backend.routes.gateway_admin import router as gateway_admin_router

        app.include_router(gateway_router)
        app.include_router(gateway_admin_router)

