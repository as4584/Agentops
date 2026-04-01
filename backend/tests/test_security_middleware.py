"""Deterministic tests for security middleware (rate limiting + headers).

Uses FastAPI TestClient — no network, fully in-process.
Covers: RateLimitMiddleware, TieredRateLimitMiddleware, SecurityHeadersMiddleware.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security_middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TieredRateLimitMiddleware,
)


def _make_app(middleware_cls, **kwargs):
    """Create a minimal FastAPI app with the given middleware."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/test")
    async def test_endpoint():
        return {"data": "ok"}

    @app.post("/chat")
    async def chat():
        return {"response": "hello"}

    @app.get("/llm/generate")
    async def llm_generate():
        return {"output": "generated"}

    app.add_middleware(middleware_cls, **kwargs)
    return app


# ── RateLimitMiddleware ──────────────────────────────────────────────


class TestRateLimitMiddleware:
    def test_allows_requests_under_limit(self):
        app = _make_app(RateLimitMiddleware, rpm=10)
        client = TestClient(app)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert resp.headers["X-RateLimit-Limit"] == "10"

    def test_blocks_after_limit_exceeded(self):
        app = _make_app(RateLimitMiddleware, rpm=3)
        client = TestClient(app)
        for _ in range(3):
            resp = client.get("/api/test")
            assert resp.status_code == 200
        # 4th request should be blocked
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_health_bypasses_rate_limit(self):
        app = _make_app(RateLimitMiddleware, rpm=1)
        client = TestClient(app)
        # Use up the limit
        client.get("/api/test")
        # Health should still work
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_zero_rpm_disables_limiting(self):
        app = _make_app(RateLimitMiddleware, rpm=0)
        client = TestClient(app)
        for _ in range(100):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_remaining_header_decrements(self):
        app = _make_app(RateLimitMiddleware, rpm=5)
        client = TestClient(app)
        resp1 = client.get("/api/test")
        remaining1 = int(resp1.headers["X-RateLimit-Remaining"])
        resp2 = client.get("/api/test")
        remaining2 = int(resp2.headers["X-RateLimit-Remaining"])
        assert remaining2 < remaining1


# ── TieredRateLimitMiddleware ────────────────────────────────────────


class TestTieredRateLimitMiddleware:
    def test_general_endpoint_uses_general_rpm(self):
        app = _make_app(TieredRateLimitMiddleware, general_rpm=10, llm_rpm=2)
        client = TestClient(app)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "10"

    def test_llm_endpoint_uses_stricter_limit(self):
        app = _make_app(TieredRateLimitMiddleware, general_rpm=100, llm_rpm=2)
        client = TestClient(app)
        # LLM endpoints should have stricter limit
        for _ in range(2):
            resp = client.post("/chat")
            assert resp.status_code == 200
        # 3rd LLM request blocked
        resp = client.post("/chat")
        assert resp.status_code == 429

    def test_llm_limit_independent_of_general(self):
        app = _make_app(TieredRateLimitMiddleware, general_rpm=100, llm_rpm=2)
        client = TestClient(app)
        # Exhaust LLM limit
        client.post("/chat")
        client.post("/chat")
        resp = client.post("/chat")
        assert resp.status_code == 429
        # General endpoint should still work
        resp = client.get("/api/test")
        assert resp.status_code == 200

    def test_health_bypasses_tiered_limits(self):
        app = _make_app(TieredRateLimitMiddleware, general_rpm=1, llm_rpm=1)
        client = TestClient(app)
        client.get("/api/test")  # Use up general limit
        resp = client.get("/health")
        assert resp.status_code == 200


# ── SecurityHeadersMiddleware ────────────────────────────────────────


class TestSecurityHeadersMiddleware:
    def setup_method(self):
        app = _make_app(SecurityHeadersMiddleware)
        self.client = TestClient(app)

    def test_x_content_type_options(self):
        resp = self.client.get("/api/test")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options(self):
        resp = self.client.get("/api/test")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_xss_protection(self):
        resp = self.client.get("/api/test")
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"

    def test_referrer_policy(self):
        resp = self.client.get("/api/test")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_csp_present(self):
        resp = self.client.get("/api/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp

    def test_hsts_present(self):
        resp = self.client.get("/api/test")
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]

    def test_permissions_policy(self):
        resp = self.client.get("/api/test")
        pp = resp.headers["Permissions-Policy"]
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_cache_control_no_store(self):
        resp = self.client.get("/api/test")
        assert resp.headers["Cache-Control"] == "no-store"

    def test_all_headers_present_on_every_response(self):
        expected = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
            "Content-Security-Policy",
            "Strict-Transport-Security",
            "Permissions-Policy",
            "Cache-Control",
        ]
        resp = self.client.get("/health")
        for header in expected:
            assert header in resp.headers, f"Missing header: {header}"
