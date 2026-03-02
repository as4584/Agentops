"""
LLM Router — Hybrid local/cloud model routing with cost tracking.
=================================================================
Routes inference requests to the optimal model based on task type,
balancing cost, quality, and latency.

Three modes:
  - local_only:  All requests → Ollama (free, fast, lower quality)
  - hybrid:      Routes by task type — design/architecture → cloud,
                 copy/metadata → local (best cost/quality ratio)
  - cloud_only:  All requests → OpenRouter (highest quality, costs money)

Usage:
    from lib.localllm.router import LLMRouter

    router = LLMRouter(mode="hybrid")

    # Auto-route by task type
    result = await router.generate("Create a design system", task="design_system")

    # Force a specific model
    result = await router.generate("Write copy", model="local")

    # Check costs
    print(router.get_stats())
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from lib.localllm.client import LocalLLM
from lib.localllm.cloud_client import CloudLLMClient, CLOUD_MODELS


# ---------------------------------------------------------------------------
# Routing mode
# ---------------------------------------------------------------------------
class RoutingMode(str, Enum):
    LOCAL_ONLY = "local_only"
    HYBRID = "hybrid"
    CLOUD_ONLY = "cloud_only"


# ---------------------------------------------------------------------------
# Task → Model routing table
# ---------------------------------------------------------------------------
# Maps task types to the preferred cloud model for hybrid mode.
# Any task not listed here defaults to local inference in hybrid mode.
TASK_ROUTES: dict[str, dict[str, Any]] = {
    # High-value tasks → cloud (quality matters)
    "design_system": {
        "model": "kimi-k2",
        "reason": "Design systems require strong visual/architectural reasoning",
        "temperature": 0.6,
    },
    "site_architecture": {
        "model": "kimi-k2",
        "reason": "Site structure needs coherent multi-page planning",
        "temperature": 0.5,
    },
    "code_generation": {
        "model": "kimi-k2",
        "reason": "Complex code benefits from cloud model reasoning",
        "temperature": 0.4,
    },
    "qa_review": {
        "model": "kimi-k2",
        "reason": "QA needs quality evaluation capabilities",
        "temperature": 0.3,
    },
    "architecture_analysis": {
        "model": "kimi-k2-thinking",
        "reason": "Deep architecture analysis benefits from extended reasoning",
        "temperature": 0.4,
    },
    "system_design": {
        "model": "kimi-k2-thinking",
        "reason": "System design requires multi-step reasoning chains",
        "temperature": 0.5,
    },
    "agent_prompt": {
        "model": "kimi-k2",
        "reason": "Agent system prompts need precise, capable authoring",
        "temperature": 0.5,
    },

    # Cost-efficient tasks → local (quality sufficient)
    "copy_writing": {
        "model": "local",
        "reason": "Copy benefits from iteration speed over raw quality",
        "temperature": 0.7,
    },
    "seo_metadata": {
        "model": "local",
        "reason": "SEO meta tags are formulaic — local handles fine",
        "temperature": 0.5,
    },
    "aeo_schema": {
        "model": "local",
        "reason": "JSON-LD schemas follow templates — local is sufficient",
        "temperature": 0.4,
    },
    "summarization": {
        "model": "local",
        "reason": "Summaries are compression tasks — local handles well",
        "temperature": 0.5,
    },
    "classification": {
        "model": "local",
        "reason": "Simple classification is within local model capability",
        "temperature": 0.3,
    },
    "embedding": {
        "model": "local",
        "reason": "Embeddings must be local (cloud doesn't support them)",
        "temperature": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Router Statistics
# ---------------------------------------------------------------------------
class RouterStats:
    """Tracks routing decisions and costs."""

    def __init__(self) -> None:
        self.total_requests = 0
        self.local_requests = 0
        self.cloud_requests = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.total_latency_ms = 0
        self._cost_log: list[dict[str, Any]] = []

    def record(
        self,
        destination: str,
        model: str,
        task: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0,
        cost_usd: float = 0,
    ) -> None:
        self.total_requests += 1
        if destination == "local":
            self.local_requests += 1
        else:
            self.cloud_requests += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.total_latency_ms += latency_ms
        self._cost_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "destination": destination,
            "model": model,
            "task": task,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": round(latency_ms, 1),
            "cost_usd": round(cost_usd, 6),
        })

    @property
    def estimated_cost_usd(self) -> float:
        return sum(e["cost_usd"] for e in self._cost_log)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "local_requests": self.local_requests,
            "cloud_requests": self.cloud_requests,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "avg_latency_ms": round(
                self.total_latency_ms / max(self.total_requests, 1), 1
            ),
            "cost_per_request_avg": round(
                self.estimated_cost_usd / max(self.total_requests, 1), 6
            ),
        }

    def recent_log(self, n: int = 20) -> list[dict[str, Any]]:
        return self._cost_log[-n:]


# ---------------------------------------------------------------------------
# LLM Router
# ---------------------------------------------------------------------------
class LLMRouter:
    """
    Intelligent LLM router — routes requests to local or cloud
    based on task type, mode, and cost constraints.

    This is the ONLY entry point agents should use for LLM calls
    when running in hybrid or cloud mode (INV-13).
    """

    def __init__(
        self,
        mode: str | RoutingMode = RoutingMode.HYBRID,
        local_client: Optional[LocalLLM] = None,
        cloud_client: Optional[CloudLLMClient] = None,
        monthly_budget_usd: float = 50.0,
    ) -> None:
        self.mode = RoutingMode(mode) if isinstance(mode, str) else mode
        self.monthly_budget = monthly_budget_usd
        self.stats = RouterStats()

        # Lazy-init clients only when needed
        self._local: Optional[LocalLLM] = local_client
        self._cloud: Optional[CloudLLMClient] = cloud_client

    # ── Client accessors (lazy init) ─────────────────────

    @property
    def local(self) -> LocalLLM:
        if self._local is None:
            self._local = LocalLLM()
        return self._local

    @property
    def cloud(self) -> CloudLLMClient:
        if self._cloud is None:
            self._cloud = CloudLLMClient()
        return self._cloud

    # ── Route decision ───────────────────────────────────

    def _route(self, task: str, model: Optional[str] = None) -> tuple[str, str]:
        """
        Decide where to route a request.

        Returns: (destination, model_name)
            destination: "local" or "cloud"
            model_name: specific model to use

        Priority:
        1. Explicit model override ("local", "kimi-k2", etc.)
        2. Budget guard (fallback to local if budget exhausted)
        3. Mode-based routing
        4. Task-based routing table
        """
        # Explicit model override
        if model:
            if model == "local":
                return "local", self.local.model
            if model in CLOUD_MODELS:
                return "cloud", model
            # Assume it's a local model name (e.g., "codellama:13b")
            return "local", model

        # Mode overrides
        if self.mode == RoutingMode.LOCAL_ONLY:
            return "local", self.local.model

        if self.mode == RoutingMode.CLOUD_ONLY:
            return "cloud", "kimi-k2"

        # Hybrid mode: check budget
        if self.stats.estimated_cost_usd >= self.monthly_budget:
            return "local", self.local.model

        # Hybrid mode: consult task routes
        route = TASK_ROUTES.get(task, {})
        route_model = route.get("model", "local")

        if route_model == "local":
            return "local", self.local.model
        return "cloud", route_model

    # ── Generate (primary interface) ─────────────────────

    async def generate(
        self,
        prompt: str,
        system: str = "",
        task: str = "general",
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Route a generation request to the optimal model.

        Args:
            prompt: The user/agent prompt.
            system: System prompt.
            task: Task type for routing (e.g., "design_system", "copy_writing").
            temperature: Override temperature (uses task default if None).
            max_tokens: Max response tokens.
            model: Force a specific model ("local", "kimi-k2", etc.).

        Returns:
            Generated text response.
        """
        destination, model_name = self._route(task, model)

        # Resolve temperature
        if temperature is None:
            route = TASK_ROUTES.get(task, {})
            temperature = route.get("temperature", 0.7)

        t0 = time.monotonic()

        if destination == "local":
            result = await self.local.generate(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name if model_name != self.local.model else None,
            )
            latency = (time.monotonic() - t0) * 1000
            self.stats.record(
                destination="local",
                model=model_name,
                task=task,
                latency_ms=latency,
                cost_usd=0.0,
            )
        else:
            result = await self.cloud.generate(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name,
            )
            latency = (time.monotonic() - t0) * 1000

            # Estimate tokens for cost tracking
            est_in = len(prompt + system) // 4
            est_out = len(result) // 4
            model_info = CLOUD_MODELS.get(model_name, CLOUD_MODELS["kimi-k2"])
            cost = (
                (est_in / 1_000_000) * model_info["input_cost_per_m"]
                + (est_out / 1_000_000) * model_info["output_cost_per_m"]
            )

            self.stats.record(
                destination="cloud",
                model=model_name,
                task=task,
                tokens_in=est_in,
                tokens_out=est_out,
                latency_ms=latency,
                cost_usd=cost,
            )

        return result

    # ── Chat (message list interface) ────────────────────

    async def chat(
        self,
        messages: list[dict[str, str]],
        task: str = "general",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Route a chat completion request.
        Interface matches OllamaClient.chat().
        """
        destination, model_name = self._route(task, model)

        t0 = time.monotonic()

        if destination == "local":
            result = await self.local.chat_messages(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name if model_name != self.local.model else None,
            )
            latency = (time.monotonic() - t0) * 1000
            self.stats.record(
                destination="local", model=model_name, task=task,
                latency_ms=latency, cost_usd=0.0,
            )
        else:
            result = await self.cloud.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name,
            )
            latency = (time.monotonic() - t0) * 1000
            total_text = " ".join(m.get("content", "") for m in messages)
            est_in = len(total_text) // 4
            est_out = len(result) // 4
            model_info = CLOUD_MODELS.get(model_name, CLOUD_MODELS["kimi-k2"])
            cost = (
                (est_in / 1_000_000) * model_info["input_cost_per_m"]
                + (est_out / 1_000_000) * model_info["output_cost_per_m"]
            )
            self.stats.record(
                destination="cloud", model=model_name, task=task,
                tokens_in=est_in, tokens_out=est_out,
                latency_ms=latency, cost_usd=cost,
            )

        return result

    # ── Structured JSON ──────────────────────────────────

    async def chat_json(
        self,
        prompt: str,
        system: str = "",
        schema: Optional[dict] = None,
        task: str = "general",
        temperature: float = 0.5,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> dict:
        """
        Route a structured JSON request.
        Interface matches LocalLLM.chat_json().
        """
        destination, model_name = self._route(task, model)

        if destination == "local":
            return await self.local.chat_json(
                prompt=prompt,
                system=system,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name if model_name != self.local.model else None,
            )
        else:
            return await self.cloud.chat_json(
                prompt=prompt,
                system=system,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name,
            )

    # ── Embeddings (always local) ────────────────────────

    async def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        """
        Generate embeddings. Always uses local model (free + fast).
        Cloud models don't support embeddings via OpenRouter.
        """
        return await self.local.embed(text, model)

    # ── Health ───────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Combined health check for local + cloud."""
        local_available = await self.local.is_available()

        cloud_available = False
        if self.mode != RoutingMode.LOCAL_ONLY:
            try:
                cloud_available = await self.cloud.is_available()
            except (ValueError, Exception):
                cloud_available = False

        return {
            "mode": self.mode.value,
            "local": {
                "status": "ready" if local_available else "offline",
                "model": self.local.model,
                "server": self.local.base_url,
            },
            "cloud": {
                "status": "ready" if cloud_available else "unavailable",
                "provider": "openrouter",
                "default_model": "kimi-k2" if self.mode != RoutingMode.LOCAL_ONLY else "n/a",
            },
            "stats": self.stats.to_dict(),
            "budget_remaining_usd": round(
                self.monthly_budget - self.stats.estimated_cost_usd, 2
            ),
        }

    # ── Stats ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return routing statistics and cost tracking."""
        return self.stats.to_dict()

    def get_cost_log(self, n: int = 20) -> list[dict[str, Any]]:
        """Return recent cost log entries."""
        return self.stats.recent_log(n)

    # ── Sync wrappers ────────────────────────────────────

    def generate_sync(
        self,
        prompt: str,
        system: str = "",
        task: str = "general",
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper around generate()."""
        return _run_sync(
            self.generate(prompt, system, task, temperature, max_tokens, model)
        )

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        task: str = "general",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper around chat()."""
        return _run_sync(
            self.chat(messages, task, temperature, max_tokens, model)
        )

    def chat_json_sync(
        self,
        prompt: str,
        system: str = "",
        schema: Optional[dict] = None,
        task: str = "general",
        temperature: float = 0.5,
        model: Optional[str] = None,
    ) -> dict:
        """Synchronous wrapper around chat_json()."""
        return _run_sync(
            self.chat_json(prompt, system, schema, task, temperature, model=model)
        )

    async def close(self) -> None:
        """Close both clients."""
        if self._local:
            await self._local.close()
        if self._cloud:
            await self._cloud.close()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
import asyncio


def _run_sync(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
