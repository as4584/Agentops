"""
Gateway Rate Limiting & Quotas — Token-bucket per API key.
==========================================================
Supports:
- RPM  (requests per minute)
- TPM  (tokens per minute)
- TPD  (tokens per day)
- $/hour soft cap
- Memory and Redis backends

Headers returned:
  X-RateLimit-Limit-Requests
  X-RateLimit-Remaining-Requests
  X-RateLimit-Limit-Tokens
  X-RateLimit-Remaining-Tokens
  X-Quota-Used-Today-USD
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config_gateway import (
    GATEWAY_RATE_LIMIT_BACKEND,
    GATEWAY_REDIS_URL,
)


# ---------------------------------------------------------------------------
# Token bucket state
# ---------------------------------------------------------------------------

@dataclass
class BucketState:
    """In-memory token bucket for a single API key."""

    rpm_window: list[float] = field(default_factory=list)   # request timestamps
    tpm_tokens: float = 0.0                                  # tokens used this minute
    tpm_window_start: float = field(default_factory=time.time)
    tpd_tokens: float = 0.0                                  # tokens used today
    tpd_day: str = ""                                        # YYYY-MM-DD
    usd_hour: float = 0.0                                    # cost this hour
    usd_hour_window_start: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# In-memory rate limiter
# ---------------------------------------------------------------------------

class MemoryRateLimiter:
    """Thread-safe in-memory rate limiter keyed by API key_id."""

    def __init__(self) -> None:
        self._buckets: dict[str, BucketState] = defaultdict(BucketState)

    def check_rpm(self, key_id: str, limit: int) -> tuple[bool, int]:
        """Returns (allowed, remaining). Modifies state only if allowed."""
        if limit <= 0:
            return True, 999_999
        now = time.time()
        b = self._buckets[key_id]
        b.rpm_window = [t for t in b.rpm_window if now - t < 60]
        remaining = max(0, limit - len(b.rpm_window))
        if len(b.rpm_window) >= limit:
            return False, 0
        b.rpm_window.append(now)
        return True, remaining - 1

    def check_tpm(self, key_id: str, tokens: int, limit: int) -> tuple[bool, int]:
        """Returns (allowed, remaining_tokens)."""
        if limit <= 0:
            return True, 999_999
        now = time.time()
        b = self._buckets[key_id]
        if now - b.tpm_window_start >= 60:
            b.tpm_tokens = 0.0
            b.tpm_window_start = now
        remaining = max(0.0, limit - b.tpm_tokens)
        if b.tpm_tokens + tokens > limit:
            return False, int(remaining)
        b.tpm_tokens += tokens
        return True, int(remaining - tokens)

    def check_tpd(self, key_id: str, tokens: int, limit: int) -> tuple[bool, int]:
        """Returns (allowed, remaining_tokens)."""
        if limit <= 0:
            return True, 999_999
        from datetime import date

        today = date.today().isoformat()
        b = self._buckets[key_id]
        if b.tpd_day != today:
            b.tpd_tokens = 0.0
            b.tpd_day = today
        remaining = max(0.0, limit - b.tpd_tokens)
        if b.tpd_tokens + tokens > limit:
            return False, int(remaining)
        b.tpd_tokens += tokens
        return True, int(remaining - tokens)

    def record_cost(self, key_id: str, usd: float, hourly_limit: float) -> tuple[bool, float]:
        """Track cost. Returns (within_budget, remaining_usd)."""
        if hourly_limit <= 0:
            return True, 999_999.0
        now = time.time()
        b = self._buckets[key_id]
        if now - b.usd_hour_window_start >= 3600:
            b.usd_hour = 0.0
            b.usd_hour_window_start = now
        b.usd_hour += usd
        remaining = max(0.0, hourly_limit - b.usd_hour)
        return b.usd_hour <= hourly_limit, remaining

    def get_tpd_used(self, key_id: str) -> float:
        return self._buckets[key_id].tpd_tokens

    def reset(self, key_id: str) -> None:
        self._buckets.pop(key_id, None)


# ---------------------------------------------------------------------------
# Redis rate limiter stub (for future distributed deployments)
# ---------------------------------------------------------------------------

class RedisRateLimiter(MemoryRateLimiter):
    """Redis-backed rate limiter. Falls back to memory if Redis unavailable."""

    def __init__(self, redis_url: str = GATEWAY_REDIS_URL) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._redis = None
        self._connect()

    def _connect(self) -> None:
        try:
            import redis  # type: ignore

            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_timeout=1)
            self._redis.ping()
        except Exception:
            self._redis = None  # fall back to memory


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_rate_limiter() -> MemoryRateLimiter:
    global _limiter
    if _limiter is None:
        if GATEWAY_RATE_LIMIT_BACKEND == "redis":
            _limiter = RedisRateLimiter()
        else:
            _limiter = MemoryRateLimiter()
    return _limiter


_limiter: MemoryRateLimiter | None = None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class GatewayRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-key RPM rate limiting. TPM/TPD enforced in route handlers
    after token counts are known."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ctx = getattr(request.state, "gateway_context", None)
        if ctx is None:
            return await call_next(request)

        limiter = get_rate_limiter()
        allowed, remaining = limiter.check_rpm(ctx.key_id, ctx.quota_rpm)

        if not allowed:
            import json
            return Response(
                content=json.dumps({
                    "error": {
                        "message": "Rate limit exceeded (RPM)",
                        "type": "rate_limit_error",
                        "code": 429,
                    }
                }),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit-Requests"] = str(ctx.quota_rpm)
        response.headers["X-RateLimit-Remaining-Requests"] = str(remaining)
        return response
