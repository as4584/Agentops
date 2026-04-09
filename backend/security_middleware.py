"""
Security Middleware — Rate limiting and security headers for Agentop.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import LLM_RATE_LIMIT_RPM, RATE_LIMIT_RPM

# LLM-backed endpoints that should receive stricter per-IP rate limits
_LLM_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/chat",
        "/agents/message",
        "/llm/generate",
        "/campaign/generate",
        "/intake/start",
        "/intake/answer",
    }
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per IP address."""

    def __init__(self, app, rpm: int = RATE_LIMIT_RPM):
        super().__init__(app)
        self.rpm = rpm
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self.rpm <= 0:
            return await call_next(request)

        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean old requests (older than 60 seconds)
        self.requests[client_ip] = [t for t in self.requests[client_ip] if now - t < 60]

        # Check rate limit
        if len(self.requests[client_ip]) >= self.rpm:
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        # Record this request
        self.requests[client_ip].append(now)

        response = await call_next(request)

        # Add rate limit headers
        remaining = max(0, self.rpm - len(self.requests[client_ip]))
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response


class TieredRateLimitMiddleware(BaseHTTPMiddleware):
    """Tiered in-memory rate limiter.

    LLM-backed endpoints (e.g. /chat, /campaign/generate) are limited to a
    lower per-IP request rate than general API endpoints to protect compute
    resources and prevent prompt-injection amplification attacks.

    Defaults:
        general_rpm: 600  (matches legacy RateLimitMiddleware default)
        llm_rpm:      30  (LLM endpoints — strict)
    """

    def __init__(
        self,
        app,
        general_rpm: int = RATE_LIMIT_RPM,
        llm_rpm: int = LLM_RATE_LIMIT_RPM,
    ):
        super().__init__(app)
        self.general_rpm = general_rpm
        self.llm_rpm = llm_rpm
        # Separate bucket dicts for each tier
        self.general_buckets: dict[str, list[float]] = defaultdict(list)
        self.llm_buckets: dict[str, list[float]] = defaultdict(list)

    def _check(
        self,
        buckets: dict[str, list[float]],
        ip: str,
        limit: int,
    ) -> tuple[bool, int]:
        """Slide the window and return (exceeded, remaining)."""
        now = time.time()
        buckets[ip] = [t for t in buckets[ip] if now - t < 60]
        if len(buckets[ip]) >= limit:
            return True, 0
        buckets[ip].append(now)
        return False, max(0, limit - len(buckets[ip]))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Skip rate limiting for health check
        if path == "/health":
            return await call_next(request)

        is_llm = path in _LLM_ENDPOINTS
        limit = self.llm_rpm if is_llm else self.general_rpm
        buckets = self.llm_buckets if is_llm else self.general_buckets

        if limit > 0:
            exceeded, remaining = self._check(buckets, client_ip, limit)
            if exceeded:
                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        response = await call_next(request)

        if limit > 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)  # type: ignore[possibly-undefined]

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        path = request.url.path
        # /ml/webgen/site/* files are served into iframes in the ML Lab viewer.
        is_ml_site = path.startswith("/ml/webgen/site/")
        # /preview/* files are served into iframes in the main dashboard Projects tab.
        is_preview = path.startswith("/preview/")

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Block framing to prevent clickjacking — except iframe-served site files
        if not is_ml_site and not is_preview:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy
        if is_ml_site:
            # Allow framing from localhost for the ML Lab iframe viewer (port 3009)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; frame-ancestors http://localhost:3009 http://127.0.0.1:3009;"
            )
        elif is_preview:
            # Allow framing from the main dashboard (port 3007)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; frame-ancestors http://localhost:3007 http://127.0.0.1:3007;"
            )
        else:
            # Tightened for an API-only backend
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self';"
            )
        # HTTP Strict Transport Security (safe for local TLS / proxied deployments)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Disable intrusive browser features that this API never uses
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), "
            "gyroscope=(), magnetometer=(), microphone=(), "
            "payment=(), usb=()"
        )
        # Prevent caching of sensitive API responses
        response.headers["Cache-Control"] = "no-store"

        return response
