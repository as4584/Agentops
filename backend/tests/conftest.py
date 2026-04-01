"""
Shared pytest configuration for backend tests.

Markers are auto-applied based on filename patterns so individual test files
don't need explicit ``@pytest.mark.<group>`` decorators.  Run subsets with::

    pytest -m ml          # only ML tests (12 files)
    pytest -m gateway     # only gateway tests
    pytest -m "not ml"    # everything except ML
    pytest -m integration # integration tests
    pytest -m unit        # pure unit tests

Parallel execution (requires pytest-xdist)::

    pytest -n auto        # use all cores
    pytest -n 4 -m ml     # 4 workers, ML only
"""

from __future__ import annotations

import pytest

# ── Filename-pattern → marker mapping ────────────────────────────────────────
# Order matters: first match wins.  More specific patterns go first.
_MARKER_RULES: list[tuple[str, str]] = [
    # ML subsystem
    ("test_ml_", "ml"),
    # Gateway (auth, ACL, secrets, rate-limiting)
    ("gateway/", "gateway"),
    ("test_ratelimit", "gateway"),
    # Sandbox / Docker isolation
    ("test_sandbox_", "sandbox"),
    ("test_docker_sandbox_", "sandbox"),
    # Agent orchestration
    ("test_agent_to_agent", "agents"),
    ("test_gatekeeper_", "agents"),
    ("test_gsd_agent", "agents"),
    # Tools
    ("test_tool_ids", "tools"),
    ("test_tools_native", "tools"),
    # Skills
    ("test_skills_", "skills"),
    # Content / webgen
    ("test_webgen_", "webgen"),
    # Browser automation
    ("test_browser_", "browser"),
    # MCP bridge
    ("test_mcp_", "mcp"),
    # Middleware (drift guard)
    ("test_drift_guard", "middleware"),
    # Memory
    ("test_memory_", "memory"),
    # Models (Pydantic schemas)
    ("test_models", "models"),
    # Deerflow
    ("deerflow/", "deerflow"),
    # Integration (multi-component, HTTP clients, DB, WebSocket)
    ("test_a2ui_", "integration"),
    ("test_customer_store", "integration"),
    ("test_gsd_store", "integration"),
    ("test_health_deps", "integration"),
    ("test_integration_flows", "integration"),
    ("test_knowledge_store", "integration"),
    ("test_launch", "integration"),
    ("test_routes_", "integration"),
    ("test_scheduler_routes", "integration"),
    ("test_webhooks", "integration"),
    ("test_ws_control_plane", "integration"),
    # Unit (pure isolation, full mocking)
    ("test_llm_client", "unit"),
    ("test_model_failover", "unit"),
    ("test_profile_rotation", "unit"),
    ("test_scheduler", "unit"),
]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag every test item with a group marker based on its file path."""
    for item in items:
        nodeid = item.nodeid  # e.g. "backend/tests/test_ml_pipeline.py::test_run"
        for pattern, marker_name in _MARKER_RULES:
            if pattern in nodeid:
                item.add_marker(getattr(pytest.mark, marker_name))
                break
