"""
Health & Safety — Provider health monitoring and circuit breaker.
=================================================================
Circuit breaker pattern:
  CLOSED   → requests pass through normally
  OPEN     → fast-fail, no requests sent to provider
  HALF_OPEN → one probe request to test recovery

Content safety:
  Basic prompt injection detection (keyword heuristics).
  Doesn't replace a real content filter — use externally if needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.config_gateway import (
    GATEWAY_CIRCUIT_BREAKER_THRESHOLD,
    GATEWAY_CIRCUIT_BREAKER_TIMEOUT,
)

logger = logging.getLogger("gateway.health")


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderCircuit:
    provider: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_ts: float = 0.0
    threshold: int = GATEWAY_CIRCUIT_BREAKER_THRESHOLD
    timeout: int = GATEWAY_CIRCUIT_BREAKER_TIMEOUT

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_ts = time.monotonic()
        if self.failure_count >= self.threshold:
            logger.warning("Circuit OPEN for provider %s after %d failures", self.provider, self.failure_count)
            self.state = CircuitState.OPEN

    def is_open(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return False
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_ts
            if elapsed >= self.timeout:
                logger.info("Circuit HALF_OPEN for provider %s — probing", self.provider)
                self.state = CircuitState.HALF_OPEN
                return False  # Allow one probe
            return True
        # HALF_OPEN — allow one request through
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_ago_s": round(time.monotonic() - self.last_failure_ts, 1)
            if self.last_failure_ts
            else None,
        }


class CircuitBreakerRegistry:
    """Manages circuits for all providers."""

    def __init__(self) -> None:
        self._circuits: dict[str, ProviderCircuit] = {}

    def get(self, provider: str) -> ProviderCircuit:
        if provider not in self._circuits:
            self._circuits[provider] = ProviderCircuit(provider=provider)
        return self._circuits[provider]

    def all_status(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._circuits.values()]


_registry = CircuitBreakerRegistry()


def get_circuit(provider: str) -> ProviderCircuit:
    return _registry.get(provider)


def all_circuit_status() -> list[dict[str, Any]]:
    return _registry.all_status()


# ---------------------------------------------------------------------------
# Provider Health Monitor
# ---------------------------------------------------------------------------

class ProviderHealthMonitor:
    """Periodically pings all configured providers."""

    def __init__(self) -> None:
        self._status: dict[str, bool] = {}
        self._last_check: dict[str, float] = {}
        self._check_interval = 60.0  # seconds

    async def check_provider(self, provider: str) -> bool:
        from backend.gateway.adapters import get_adapter

        try:
            adapter = get_adapter(provider)
            ok = await adapter.health_check()
        except Exception as e:
            logger.debug("Health check failed for %s: %s", provider, e)
            ok = False

        circuit = get_circuit(provider)
        if ok:
            circuit.record_success()
        else:
            circuit.record_failure()

        self._status[provider] = ok
        self._last_check[provider] = time.monotonic()
        return ok

    async def check_all(self) -> dict[str, bool]:
        from backend.gateway.adapters import list_adapters

        tasks = {p: self.check_provider(p) for p in list_adapters()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for p, r in zip(tasks.keys(), results):
            self._status[p] = r is True
        return dict(self._status)

    def get_status(self) -> dict[str, Any]:
        return {
            "providers": {
                p: {
                    "healthy": self._status.get(p, None),
                    "last_check_ago_s": round(time.monotonic() - self._last_check.get(p, 0), 1)
                    if p in self._last_check
                    else None,
                    "circuit": get_circuit(p).state.value,
                }
                for p in ["ollama", "openrouter", "openai", "anthropic"]
            }
        }


_health_monitor = ProviderHealthMonitor()


def get_health_monitor() -> ProviderHealthMonitor:
    return _health_monitor


# ---------------------------------------------------------------------------
# Fallback selection
# ---------------------------------------------------------------------------

async def select_provider_with_fallback(
    preferred_provider: str,
    fallback_order: list[str] | None = None,
) -> str:
    """Return the first available provider, starting with *preferred_provider*."""
    from backend.config_gateway import GATEWAY_FALLBACK_ORDER

    order = [preferred_provider] + [
        p for p in (fallback_order or GATEWAY_FALLBACK_ORDER)
        if p != preferred_provider
    ]

    for provider in order:
        circuit = get_circuit(provider)
        if not circuit.is_open():
            return provider

    # All circuits open — return preferred anyway (will fail fast)
    return preferred_provider


# ---------------------------------------------------------------------------
# Content Safety — basic prompt injection detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "you are now",
    "you are a",
    "pretend you are",
    "act as if",
    "system prompt:",
    "new instructions:",
    "<|im_start|>",
    "<|system|>",
    "###instruction",
    "[system]",
    "prompt injection",
]


def check_prompt_safety(text: str) -> tuple[bool, str]:
    """Return (safe, reason). Heuristic check only — not a full content filter."""
    lower = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in lower:
            return False, f"Potential prompt injection detected: {pattern!r}"
    return True, ""
