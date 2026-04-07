from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from backend.config import (
    LLM_CIRCUIT_FAILURE_THRESHOLD,
    LLM_CIRCUIT_RESET_SECONDS,
    OLLAMA_MODEL,
)
from backend.llm import OllamaClient
from backend.utils.tool_ids import ToolIdRegistry, validate_tool_definitions
from lib.localllm.cloud_client import CloudLLMClient


class ModelProvider(str, Enum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    COPILOT = "copilot"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    provider: ModelProvider
    display_name: str
    context_window: int
    input_cost_per_m: float
    output_cost_per_m: float
    best_for: list[str]
    fallback_chain: list[str] = field(default_factory=lambda: cast(list[str], []))
    supports_tools: bool = False


@dataclass
class ModelHealthState:
    model_id: str
    healthy: bool = True
    consecutive_failures: int = 0
    circuit_open: bool = False
    circuit_opened_at: float = 0.0
    last_error: str | None = None


class AllModelsFailedError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


UNIFIED_MODEL_REGISTRY: dict[str, ModelSpec] = {
    # ── Fine-tuned local models ──
    "lex": ModelSpec(
        model_id="lex",
        provider=ModelProvider.OLLAMA,
        display_name="Lex (Fine-tuned)",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["orchestration", "agent_tasks", "reasoning", "code"],
        fallback_chain=["mistral:7b", "llama3.2"],
        supports_tools=True,
    ),
    "webgen": ModelSpec(
        model_id="webgen",
        provider=ModelProvider.OLLAMA,
        display_name="WebGen (Fine-tuned)",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["web_generation", "html", "css", "frontend"],
        fallback_chain=["qwen2.5", "mistral:7b"],
        supports_tools=True,
    ),
    # ── Local base models ──
    "llama3.2:1b": ModelSpec(
        model_id="llama3.2:1b",
        provider=ModelProvider.OLLAMA,
        display_name="Llama 3.2 1B",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["routing", "classification", "simple_qa"],
        fallback_chain=["llama3.2", "mistral:7b"],
    ),
    "llama3.2": ModelSpec(
        model_id="llama3.2",
        provider=ModelProvider.OLLAMA,
        display_name="Llama 3.2 3B",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["general", "summarization", "content_drafts"],
        fallback_chain=["mistral:7b", "llama3.2:1b"],
    ),
    "mistral:7b": ModelSpec(
        model_id="mistral:7b",
        provider=ModelProvider.OLLAMA,
        display_name="Mistral 7B",
        context_window=32000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["code", "reasoning", "agent_tasks"],
        fallback_chain=["llama3.2", "llama3.2:1b"],
        supports_tools=True,
    ),
    "qwen2.5": ModelSpec(
        model_id="qwen2.5",
        provider=ModelProvider.OLLAMA,
        display_name="Qwen 2.5 7B",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["multilingual", "coding", "analysis"],
        fallback_chain=["llama3.2", "mistral:7b"],
        supports_tools=True,
    ),
    # OpenRouter cloud models from existing CloudLLMClient
    "kimi-k2": ModelSpec(
        model_id="kimi-k2",
        provider=ModelProvider.OPENROUTER,
        display_name="Kimi K2",
        context_window=131072,
        input_cost_per_m=0.60,
        output_cost_per_m=0.60,
        best_for=["architecture", "planning", "reasoning"],
        fallback_chain=["kimi-k2-thinking", "claude-sonnet"],
        supports_tools=True,
    ),
    "kimi-k2-thinking": ModelSpec(
        model_id="kimi-k2-thinking",
        provider=ModelProvider.OPENROUTER,
        display_name="Kimi K2 Thinking",
        context_window=131072,
        input_cost_per_m=0.60,
        output_cost_per_m=2.00,
        best_for=["deep_reasoning", "system_design"],
        fallback_chain=["kimi-k2", "claude-sonnet"],
        supports_tools=True,
    ),
    "claude-sonnet": ModelSpec(
        model_id="claude-sonnet",
        provider=ModelProvider.OPENROUTER,
        display_name="Claude Sonnet",
        context_window=200000,
        input_cost_per_m=3.00,
        output_cost_per_m=15.00,
        best_for=["code_review", "orchestration", "writing"],
        fallback_chain=["kimi-k2", "openai:gpt-4o"],
        supports_tools=True,
    ),
    # Provider placeholders so UI/API can include them in one registry.
    # They are routed through OpenRouter or local runtime unless a direct client is added.
    "openai:gpt-4o": ModelSpec(
        model_id="openai:gpt-4o",
        provider=ModelProvider.OPENAI,
        display_name="OpenAI GPT-4o (via unified registry)",
        context_window=128000,
        input_cost_per_m=2.50,
        output_cost_per_m=10.00,
        best_for=["reasoning", "code", "general"],
        fallback_chain=["claude-sonnet", "kimi-k2"],
        supports_tools=True,
    ),
    "copilot:chat": ModelSpec(
        model_id="copilot:chat",
        provider=ModelProvider.COPILOT,
        display_name="GitHub Copilot Chat (registry entry)",
        context_window=64000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["coding", "refactoring", "review"],
        fallback_chain=["openai:gpt-4o", "claude-sonnet"],
        supports_tools=False,
    ),
}


DEFAULT_TASK_MODELS: dict[str, str] = {
    "routing": "llama3.2:1b",
    "classification": "llama3.2:1b",
    "copy_writing": "llama3.2",
    "code_generation": "mistral:7b",
    "architecture_analysis": "kimi-k2-thinking",
    "system_design": "kimi-k2-thinking",
    "qa_review": "claude-sonnet",
    "web_generation": "lex-webgen-v1",
    "general": OLLAMA_MODEL,
}


class UnifiedModelRouter:
    """Single model registry + generation adapter for local/cloud calls."""

    def __init__(self) -> None:
        self._local_client: OllamaClient | None = None
        self._cloud_client: CloudLLMClient | None = None
        self._health_map: dict[str, ModelHealthState] = {}
        self._failure_threshold = max(1, int(LLM_CIRCUIT_FAILURE_THRESHOLD))
        self._circuit_reset_seconds = max(1, int(LLM_CIRCUIT_RESET_SECONDS))

    @property
    def local_client(self) -> OllamaClient:
        if self._local_client is None:
            self._local_client = OllamaClient()
        return self._local_client

    @property
    def cloud_client(self) -> CloudLLMClient:
        if self._cloud_client is None:
            self._cloud_client = CloudLLMClient()
        return self._cloud_client

    def _get_health_state(self, model_id: str) -> ModelHealthState:
        state = self._health_map.get(model_id)
        if state is None:
            state = ModelHealthState(model_id=model_id)
            self._health_map[model_id] = state
        return state

    def _is_circuit_open(self, model_id: str) -> bool:
        state = self._get_health_state(model_id)
        if not state.circuit_open:
            return False

        elapsed = time.monotonic() - state.circuit_opened_at
        if elapsed >= self._circuit_reset_seconds:
            state.circuit_open = False
            state.healthy = True
            state.consecutive_failures = 0
            state.last_error = None
            state.circuit_opened_at = 0.0
            return False
        return True

    def _record_success(self, model_id: str) -> None:
        state = self._get_health_state(model_id)
        state.healthy = True
        state.consecutive_failures = 0
        state.circuit_open = False
        state.circuit_opened_at = 0.0
        state.last_error = None

    def _record_failure(self, model_id: str, exc: Exception) -> None:
        state = self._get_health_state(model_id)
        state.healthy = False
        state.consecutive_failures += 1
        state.last_error = f"{type(exc).__name__}: {exc}"

        if state.consecutive_failures >= self._failure_threshold:
            state.circuit_open = True
            state.circuit_opened_at = time.monotonic()

    async def _is_model_healthy(self, model_id: str) -> bool:
        if self._is_circuit_open(model_id):
            return False

        spec = UNIFIED_MODEL_REGISTRY.get(model_id)
        if spec is None:
            return False

        if spec.provider == ModelProvider.OLLAMA:
            try:
                if not await self.local_client.is_available():
                    return False
                available = await self.local_client.list_models()
                return any(model_id in item for item in available)
            except Exception:
                return False

        if spec.provider == ModelProvider.OPENROUTER:
            return bool(os.getenv("OPENROUTER_API_KEY", "").strip())

        if spec.provider == ModelProvider.OPENAI:
            return bool(os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("OPENROUTER_API_KEY", "").strip())

        if spec.provider == ModelProvider.COPILOT:
            return True

        return False

    def get_health_summary(self) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for model_id in UNIFIED_MODEL_REGISTRY:
            self._is_circuit_open(model_id)
            state = self._get_health_state(model_id)
            summary[model_id] = {
                "model_id": model_id,
                "healthy": state.healthy,
                "circuit_open": state.circuit_open,
                "consecutive_failures": state.consecutive_failures,
                "last_error": state.last_error,
            }
        return summary

    def list_models(self) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        for spec in UNIFIED_MODEL_REGISTRY.values():
            models.append(
                {
                    "model_id": spec.model_id,
                    "provider": spec.provider.value,
                    "display_name": spec.display_name,
                    "context_window": spec.context_window,
                    "input_cost_per_m": spec.input_cost_per_m,
                    "output_cost_per_m": spec.output_cost_per_m,
                    "best_for": spec.best_for,
                    "fallback_chain": spec.fallback_chain,
                    "supports_tools": spec.supports_tools,
                }
            )
        return models

    def resolve_model(self, task: str = "general", override_model: str | None = None) -> ModelSpec:
        model_id = override_model or DEFAULT_TASK_MODELS.get(task, DEFAULT_TASK_MODELS["general"])
        return UNIFIED_MODEL_REGISTRY.get(model_id, UNIFIED_MODEL_REGISTRY["llama3.2"])

    def _candidate_chain(self, primary: ModelSpec) -> list[str]:
        candidates: list[str] = []
        for model_id in [primary.model_id, *primary.fallback_chain]:
            if model_id not in candidates:
                candidates.append(model_id)
        return candidates

    @staticmethod
    def _cloud_model_key(model_id: str) -> str:
        if model_id == "openai:gpt-4o":
            return "gpt-4o"
        if model_id == "copilot:chat":
            return "claude-sonnet"
        return model_id

    async def _call_model(
        self,
        spec: ModelSpec,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if spec.provider == ModelProvider.OLLAMA:
            previous_model = self.local_client.model
            self.local_client.model = spec.model_id
            try:
                output = await self.local_client.generate(
                    prompt=prompt,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            finally:
                self.local_client.model = previous_model

            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": output,
                "estimated_cost_usd": 0.0,
            }

        if spec.provider in {ModelProvider.OPENROUTER, ModelProvider.OPENAI, ModelProvider.COPILOT}:
            output = await self.cloud_client.generate(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                model=self._cloud_model_key(spec.model_id),
            )
            est_in = len(prompt + system) // 4
            est_out = len(output) // 4
            cost = (est_in / 1_000_000) * spec.input_cost_per_m + (est_out / 1_000_000) * spec.output_cost_per_m
            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": output,
                "estimated_cost_usd": round(cost, 6),
            }

        raise RuntimeError(f"Unsupported provider: {spec.provider}")

    async def _call_model_with_tools(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        sanitized_tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        reg: ToolIdRegistry,
    ) -> dict[str, Any]:
        if spec.provider == ModelProvider.OLLAMA:
            previous_model = self.local_client.model
            self.local_client.model = spec.model_id
            try:
                output = await self.local_client.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            finally:
                self.local_client.model = previous_model

            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": output,
                "tool_calls": [],
                "estimated_cost_usd": 0.0,
                "registry": reg,
            }

        if spec.provider in {ModelProvider.OPENROUTER, ModelProvider.OPENAI, ModelProvider.COPILOT}:
            result = await self.cloud_client.generate_with_tools(
                messages=messages,
                tools=sanitized_tools,
                temperature=temperature,
                max_tokens=max_tokens,
                model=self._cloud_model_key(spec.model_id),
                registry=reg,
            )

            raw_tool_calls: list[dict[str, Any]] = result.get("tool_calls", [])
            canonical_tool_calls = reg.desanitize_tool_calls(raw_tool_calls)

            est_in = sum(len(str(m)) for m in messages) // 4
            est_out = len(result.get("output", "")) // 4
            cost = (est_in / 1_000_000) * spec.input_cost_per_m + (est_out / 1_000_000) * spec.output_cost_per_m
            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": result.get("output", ""),
                "tool_calls": canonical_tool_calls,
                "estimated_cost_usd": round(cost, 6),
                "registry": reg,
            }

        raise RuntimeError(f"Unsupported provider for tool calls: {spec.provider}")

    async def generate(
        self,
        prompt: str,
        system: str = "",
        task: str = "general",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        primary = self.resolve_model(task=task, override_model=model)
        candidates = self._candidate_chain(primary)
        last_error: Exception | None = None

        for model_id in candidates:
            if not await self._is_model_healthy(model_id):
                continue

            spec = UNIFIED_MODEL_REGISTRY.get(model_id)
            if spec is None:
                continue

            try:
                result = await self._call_model(
                    spec=spec,
                    prompt=prompt,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._record_success(model_id)
                if model_id != primary.model_id:
                    result["fallback_used"] = model_id
                    result["effective_model"] = model_id
                return result
            except Exception as exc:
                self._record_failure(model_id, exc)
                last_error = exc
                continue

        raise AllModelsFailedError(f"All candidates exhausted: {candidates}") from last_error

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        task: str = "general",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        registry: ToolIdRegistry | None = None,
    ) -> dict[str, Any]:
        """
        Generate a response that may include tool calls, with automatic tool ID
        sanitization at the API boundary.

        Pre-processes ``tools`` so every ``function.name`` satisfies
        ``^[a-zA-Z0-9_-]{1,64}$`` before the request reaches any
        OpenAI-compatible endpoint.  Desanitizes ``tool_calls`` in the response
        so callers always see canonical tool names.

        Args:
            messages:    OpenAI-format message list.
            tools:       OpenAI-format tool definitions (will be sanitized).
            task:        Task label for model selection.
            model:       Optional model override.
            temperature: Sampling temperature.
            max_tokens:  Maximum output tokens.
            registry:    Optional per-conversation ToolIdRegistry; a new one is
                         created if not supplied.

        Returns:
            Dict with keys: model_id, provider, output, tool_calls,
            estimated_cost_usd, registry.
        """
        # Validate tools before any transformation to surface bugs early.
        violations = validate_tool_definitions(tools)
        if violations:
            # Log violations but continue — sanitization will fix them below.
            import logging as _logging

            _logging.getLogger(__name__).warning("Tool definition violations before sanitization: %s", violations)

        reg = registry or ToolIdRegistry()

        # Sanitize all tool names before calling the API.
        sanitized_tools, reg = reg.sanitize_tool_definitions(tools)

        primary = self.resolve_model(task=task, override_model=model)
        candidates = self._candidate_chain(primary)
        last_error: Exception | None = None

        for model_id in candidates:
            if not await self._is_model_healthy(model_id):
                continue

            spec = UNIFIED_MODEL_REGISTRY.get(model_id)
            if spec is None:
                continue

            if model_id != primary.model_id and spec.provider == ModelProvider.OLLAMA:
                logger.warning(
                    "Skipping Ollama fallback for tool-call generation: primary=%s fallback=%s",
                    primary.model_id,
                    model_id,
                )
                continue

            try:
                result = await self._call_model_with_tools(
                    spec=spec,
                    messages=messages,
                    sanitized_tools=sanitized_tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reg=reg,
                )
                self._record_success(model_id)
                if model_id != primary.model_id:
                    result["fallback_used"] = model_id
                    result["effective_model"] = model_id
                return result
            except Exception as exc:
                self._record_failure(model_id, exc)
                last_error = exc
                continue

        raise AllModelsFailedError(f"All candidates exhausted: {candidates}") from last_error


unified_model_router = UnifiedModelRouter()
