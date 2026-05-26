"""
Resilient backend HTTP client for the Discord bot (Week 2 sprint B2).

Wraps ``httpx.AsyncClient`` with two safety rails the raw client lacks:

  1. **Bounded retry with exponential backoff** — three retries after the
     initial attempt (delays 50ms, 200ms, 800ms) on ``ConnectError``,
     ``TimeoutException``, ``ReadError`` and any 5xx response. The user's
     ``/chat`` call therefore tolerates a single transient hiccup without
     surfacing a scary error.

  2. **Circuit breaker** — five consecutive *call-level* failures inside a
     30-second window opens the breaker for 60 seconds. While open the bot
     skips its per-message error replies entirely and posts a single
     ``🔧 Backend down`` notice (consumed via ``consume_breaker_notice``).
     The breaker auto-allows a probe call after the open window expires and
     fully resets on the first successful response.

The class is constructor-injectable with a fake ``httpx.AsyncClient``, a
mock ``sleep`` coroutine, and a fake monotonic clock so tests can drive it
deterministically without real I/O or wall-clock waits.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


class CircuitBreakerOpen(RuntimeError):  # noqa: N818
    """Raised when a tracked call is attempted while the breaker is open."""


class BackendHttpClient:
    """HTTP client for the Discord bot to talk to the Agentop backend."""

    # Tuning knobs (seconds). Module-level so tests can monkeypatch if needed.
    FAILURE_WINDOW = 30.0
    OPEN_DURATION = 60.0
    FAILURE_THRESHOLD = 5
    BACKOFFS: tuple[float, ...] = (0.05, 0.2, 0.8)
    RETRY_STATUS: frozenset[int] = frozenset({500, 502, 503, 504})

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 120.0,
        headers: dict[str, str] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout, headers=headers or {})
        self._sleep = sleep
        self._clock = clock
        self._failures = 0
        self._first_failure_at = 0.0
        self._opened_at: float | None = None
        self._breaker_notice_pending = False

    # ------------------------------------------------------------------
    # Wrapped client passthrough — for non-critical/poller calls that
    # should NOT trip the breaker (e.g. background news/security polls).
    # ------------------------------------------------------------------

    @property
    def raw(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Breaker state inspection
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """True iff the breaker is currently blocking new tracked calls."""
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.OPEN_DURATION:
            # Open window elapsed → allow one probe call. State stays "armed"
            # until a probe succeeds (then ``_record_success`` resets).
            return False
        return True

    def consume_breaker_notice(self) -> bool:
        """One-shot read of the "breaker just opened" flag.

        The Discord handler reads this to know whether to post the single
        ``🔧 Backend down`` notice. Returns True at most once per open event.
        """
        if self._breaker_notice_pending:
            self._breaker_notice_pending = False
            return True
        return False

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    # ------------------------------------------------------------------
    # Tracked request — retries + breaker bookkeeping
    # ------------------------------------------------------------------

    async def post_tracked(self, path: str, *, json: dict[str, Any]) -> httpx.Response:
        return await self._request_tracked("POST", path, json=json)

    async def _request_tracked(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if self.is_open():
            raise CircuitBreakerOpen("Backend circuit breaker is open")

        url = f"{self.base_url}{path}"
        attempts = len(self.BACKOFFS) + 1  # initial + 3 retries
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None

        for i in range(attempts):
            try:
                resp = await self._client.request(method, url, json=json)
                if resp.status_code in self.RETRY_STATUS:
                    last_resp = resp
                    last_exc = None
                else:
                    self._record_success()
                    return resp
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.ReadError,
            ) as exc:
                last_exc = exc
                last_resp = None
            if i < attempts - 1:
                await self._sleep(self.BACKOFFS[i])

        # Exhausted retries — record one call-level failure.
        self._record_failure()
        if last_exc is not None:
            raise last_exc
        assert last_resp is not None
        return last_resp  # final 5xx — caller can decide what to do

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record_failure(self) -> None:
        now = self._clock()
        if self._failures == 0 or (now - self._first_failure_at) > self.FAILURE_WINDOW:
            self._failures = 1
            self._first_failure_at = now
        else:
            self._failures += 1
        if self._failures >= self.FAILURE_THRESHOLD and self._opened_at is None:
            self._opened_at = now
            self._breaker_notice_pending = True

    def _record_success(self) -> None:
        had_been_open = self._opened_at is not None
        self._failures = 0
        self._first_failure_at = 0.0
        self._opened_at = None
        self._breaker_notice_pending = False
        if had_been_open:
            # No-op — kept for future telemetry hook
            pass
