"""Sprint 6 — Architecture Decomposition: route registration extraction.

Verifies that:
- register_all_routes() is importable from backend.routes
- It wires all expected route prefixes onto a fresh FastAPI app
- Gateway routes are only included when gateway_enabled=True
- server.py no longer contains inline app.include_router() calls
- server.py uses register_all_routes() for route wiring
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SERVER_PY = Path(__file__).parent.parent / "server.py"


def _get_app_routes(app: FastAPI) -> set[str]:
    """Return all unique route paths registered on *app*."""
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
    return paths


# ---------------------------------------------------------------------------
# TestImportability
# ---------------------------------------------------------------------------


class TestImportability:
    def test_register_all_routes_importable(self) -> None:
        from backend.routes import register_all_routes  # noqa: F401

    def test_register_all_routes_is_callable(self) -> None:
        from backend.routes import register_all_routes

        assert callable(register_all_routes)

    def test_register_all_routes_signature(self) -> None:
        from backend.routes import register_all_routes

        sig = inspect.signature(register_all_routes)
        params = list(sig.parameters)
        assert "app" in params
        assert "gateway_enabled" in params

    def test_gateway_enabled_defaults_to_false(self) -> None:
        from backend.routes import register_all_routes

        sig = inspect.signature(register_all_routes)
        default = sig.parameters["gateway_enabled"].default
        assert default is False


# ---------------------------------------------------------------------------
# TestRouteRegistration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    @pytest.fixture()
    def fresh_app(self) -> FastAPI:
        return FastAPI()

    def test_register_all_routes_returns_none(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)  # return type is None

    def test_routes_added_to_app(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        before = len(fresh_app.routes)
        register_all_routes(fresh_app)
        after = len(fresh_app.routes)
        assert after > before, "register_all_routes must add routes to the app"

    def test_agent_control_routes_present(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        paths = _get_app_routes(fresh_app)
        assert any("/agents" in p for p in paths)

    def test_skills_routes_present(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        paths = _get_app_routes(fresh_app)
        assert any("/skills" in p for p in paths)

    def test_ml_routes_present(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        paths = _get_app_routes(fresh_app)
        assert any("/ml" in p for p in paths)

    def test_knowledge_routes_present(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        paths = _get_app_routes(fresh_app)
        assert any("/knowledge" in p for p in paths)

    def test_gsd_routes_present(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        paths = _get_app_routes(fresh_app)
        assert any("/gsd" in p for p in paths)

    def test_at_least_twenty_routes(self, fresh_app: FastAPI) -> None:
        from backend.routes import register_all_routes

        register_all_routes(fresh_app)
        assert len(fresh_app.routes) >= 20


# ---------------------------------------------------------------------------
# TestGatewayConditional
# ---------------------------------------------------------------------------


class TestGatewayConditional:
    def test_gateway_routes_excluded_by_default(self) -> None:
        from backend.routes import register_all_routes

        app = FastAPI()
        register_all_routes(app, gateway_enabled=False)
        paths = _get_app_routes(app)
        # Gateway adds /v1/chat/completions OpenAI-compatible endpoint
        assert not any("/v1/chat/completions" in p for p in paths)

    def test_gateway_routes_included_when_enabled(self) -> None:
        from backend.routes import register_all_routes

        app = FastAPI()
        register_all_routes(app, gateway_enabled=True)
        paths = _get_app_routes(app)
        assert any("/v1/chat/completions" in p for p in paths)

    def test_gateway_false_vs_true_diff(self) -> None:
        from backend.routes import register_all_routes

        app_no_gw = FastAPI()
        register_all_routes(app_no_gw, gateway_enabled=False)

        app_gw = FastAPI()
        register_all_routes(app_gw, gateway_enabled=True)

        assert len(app_gw.routes) > len(app_no_gw.routes)


# ---------------------------------------------------------------------------
# TestServerPyRefactor
# ---------------------------------------------------------------------------


class TestServerPyRefactor:
    def test_server_py_uses_register_all_routes(self) -> None:
        """server.py must call register_all_routes() for route wiring."""
        source = SERVER_PY.read_text()
        assert "register_all_routes" in source

    def test_server_py_no_inline_include_router_in_body(self) -> None:
        """server.py must not have inline app.include_router() body calls.

        Module-level top-of-file imports that *mention* router variables are
        OK (though they should be gone too), but bare ``app.include_router(``
        statements should not appear in the module body after the refactor.
        """
        source = SERVER_PY.read_text()
        # Strip comments
        lines = [ln for ln in source.splitlines() if not ln.strip().startswith("#")]
        body_calls = [ln for ln in lines if re.search(r"^\s*app\.include_router\(", ln)]
        assert body_calls == [], "Found inline app.include_router() calls in server.py body:\n" + "\n".join(body_calls)

    def test_server_py_imports_register_all_routes(self) -> None:
        source = SERVER_PY.read_text()
        assert "from backend.routes import register_all_routes" in source

    def test_server_py_passes_gateway_enabled_flag(self) -> None:
        source = SERVER_PY.read_text()
        assert "gateway_enabled=GATEWAY_ENABLED" in source


# ---------------------------------------------------------------------------
# TestIdempotentRegistration
# ---------------------------------------------------------------------------


class TestIdempotentRegistration:
    def test_second_call_adds_duplicate_routes(self) -> None:
        """FastAPI allows duplicate route registrations; calling twice is safe."""
        from backend.routes import register_all_routes

        app = FastAPI()
        register_all_routes(app)
        count_after_first = len(app.routes)
        # Should not raise
        register_all_routes(app)
        assert len(app.routes) >= count_after_first

    def test_register_on_multiple_apps(self) -> None:
        from backend.routes import register_all_routes

        app1, app2 = FastAPI(), FastAPI()
        register_all_routes(app1)
        register_all_routes(app2)
        assert len(app1.routes) == len(app2.routes)
