"""Deterministic tests for GatewayAuthMiddleware.

Uses FastAPI TestClient — no external DB, mocked key manager.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.gateway.middleware import GatewayAuthMiddleware, GatewayContext, _extract_bearer


def _make_api_key(**overrides):
    """Create a mock APIKey dataclass."""
    defaults = {
        "key_id": "test-key-1",
        "name": "Test Key",
        "owner": "tester",
        "key_hash": "abc123",
        "key_prefix": "agp_sk_test",
        "created_at": 1000000.0,
        "expires_at": 0.0,
        "disabled": False,
        "scopes": {"chat", "models"},
        "quota_rpm": 600,
        "quota_tpm": 100000,
        "quota_tpd": 1000000,
        "quota_daily_usd": 10.0,
        "quota_monthly_usd": 100.0,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_app():
    """Minimal FastAPI with GatewayAuthMiddleware."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    @app.get("/v1/health")
    async def v1_health():
        return {"status": "ok"}

    @app.get("/admin/keys")
    async def admin_keys():
        return {"keys": []}

    @app.get("/api/other")
    async def other():
        return {"data": "not gated"}

    app.add_middleware(GatewayAuthMiddleware)
    return app


# ── _extract_bearer ──────────────────────────────────────────────────


class TestExtractBearer:
    def test_valid_bearer(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer agp_sk_test_abc123"}
        assert _extract_bearer(req) == "agp_sk_test_abc123"

    def test_missing_header(self):
        req = MagicMock()
        req.headers = {}
        assert _extract_bearer(req) is None

    def test_empty_bearer(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer "}
        assert _extract_bearer(req) is None

    def test_non_bearer_scheme(self):
        req = MagicMock()
        req.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        assert _extract_bearer(req) is None

    def test_strips_whitespace(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer  some_key  "}
        assert _extract_bearer(req) == "some_key"


# ── GatewayAuthMiddleware ────────────────────────────────────────────


class TestGatewayAuthMiddleware:
    @patch("backend.gateway.middleware.get_key_manager")
    def test_public_paths_bypass_auth(self, mock_km):
        """Health and v1/health don't require auth."""
        app = _make_app()
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/v1/health").status_code == 200
        mock_km.assert_not_called()

    @patch("backend.gateway.middleware.get_key_manager")
    def test_non_gateway_paths_bypass_auth(self, mock_km):
        """Paths not under /v1/ or /admin/ skip gateway auth."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/other")
        assert resp.status_code == 200
        mock_km.assert_not_called()

    @patch("backend.gateway.middleware.get_key_manager")
    def test_missing_auth_returns_401(self, mock_km):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == 401

    @patch("backend.gateway.middleware.get_key_manager")
    def test_invalid_key_returns_401(self, mock_km):
        km = MagicMock()
        km.validate_key.return_value = None
        mock_km.return_value = km
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/v1/models", headers={"Authorization": "Bearer bad_key"})
        assert resp.status_code == 401

    @patch("backend.gateway.middleware.get_key_manager")
    def test_valid_key_allows_request(self, mock_km):
        km = MagicMock()
        km.validate_key.return_value = _make_api_key()
        mock_km.return_value = km
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/v1/models", headers={"Authorization": "Bearer agp_sk_test_valid"})
        assert resp.status_code == 200

    @patch("backend.gateway.middleware.get_key_manager")
    def test_admin_without_admin_scope_returns_403(self, mock_km):
        km = MagicMock()
        km.validate_key.return_value = _make_api_key(scopes={"chat"})  # No admin scope
        mock_km.return_value = km
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/admin/keys", headers={"Authorization": "Bearer agp_sk_test_noadmin"})
        assert resp.status_code == 403
        body = resp.json()
        assert "scope" in body["error"]["message"].lower()

    @patch("backend.gateway.middleware.get_key_manager")
    def test_admin_with_admin_scope_allowed(self, mock_km):
        km = MagicMock()
        km.validate_key.return_value = _make_api_key(scopes={"chat", "models", "admin"})
        mock_km.return_value = km
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/admin/keys", headers={"Authorization": "Bearer agp_sk_test_admin"})
        assert resp.status_code == 200


# ── GatewayContext ───────────────────────────────────────────────────


class TestGatewayContext:
    def test_populates_all_slots(self):
        api_key = _make_api_key(
            key_id="ctx-test",
            owner="alice",
            scopes={"chat"},
            quota_rpm=100,
        )
        ctx = GatewayContext(api_key)
        assert ctx.key_id == "ctx-test"
        assert ctx.owner == "alice"
        assert ctx.scopes == {"chat"}
        assert ctx.quota_rpm == 100
