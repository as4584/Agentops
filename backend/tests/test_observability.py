"""
Sprint 4 — Observability tests.

Tests:
- X-Trace-ID header is present on every response
- X-Trace-ID from request is echoed back
- current_trace_id() is accessible
- Trace ID is a non-empty hex string
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import backend.server as srv

    with TestClient(srv.app, raise_server_exceptions=False) as c:
        yield c


# Regex: 32 hex chars (UUID without hyphens)
_HEX_32 = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


class TestTraceIDMiddleware:
    """Every response must carry an X-Trace-ID header."""

    def test_health_live_has_trace_id(self, client):
        resp = client.get("/health/live")
        assert "x-trace-id" in resp.headers

    def test_health_ready_has_trace_id(self, client):
        resp = client.get("/health/ready")
        assert "x-trace-id" in resp.headers

    def test_metrics_has_trace_id(self, client):
        resp = client.get("/metrics")
        assert "x-trace-id" in resp.headers

    def test_health_has_trace_id(self, client):
        resp = client.get("/health")
        assert "x-trace-id" in resp.headers

    def test_trace_id_is_hex_string(self, client):
        resp = client.get("/health/live")
        trace_id = resp.headers.get("x-trace-id", "")
        assert trace_id, "X-Trace-ID is empty"
        assert _HEX_32.match(trace_id), f"X-Trace-ID not a 32-char hex string: {trace_id!r}"

    def test_client_provided_trace_id_is_echoed(self, client):
        """If client sends X-Trace-ID, it must be reflected in the response."""
        custom_id = "a" * 32
        resp = client.get("/health/live", headers={"X-Trace-ID": custom_id})
        assert resp.headers.get("x-trace-id") == custom_id

    def test_different_requests_get_different_trace_ids(self, client):
        r1 = client.get("/health/live")
        r2 = client.get("/health/live")
        tid1 = r1.headers.get("x-trace-id")
        tid2 = r2.headers.get("x-trace-id")
        assert tid1 and tid2
        assert tid1 != tid2, "Two consecutive requests got the same auto-generated trace ID"

    def test_trace_id_not_empty_string(self, client):
        resp = client.get("/metrics")
        assert resp.headers.get("x-trace-id") != ""


class TestCurrentTraceId:
    """current_trace_id() helper must be importable and return str."""

    def test_returns_string(self):
        from backend.server import current_trace_id

        result = current_trace_id()
        assert isinstance(result, str)

    def test_returns_empty_outside_request(self):
        """Outside a live request, ContextVar default is empty string."""
        from backend.server import current_trace_id

        result = current_trace_id()
        # In a test context there is no active request, so default is used.
        assert result == ""
