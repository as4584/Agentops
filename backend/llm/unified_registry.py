from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.config import OLLAMA_MODEL
from backend.llm import OllamaClient
from backend.utils.tool_ids import ToolIdRegistry, sanitize_tool_id, validate_tool_definitions
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
    supports_tools: bool = False


UNIFIED_MODEL_REGISTRY: dict[str, ModelSpec] = {
    # Local models (no variable token billing)
    "llama3.2:1b": ModelSpec(
        model_id="llama3.2:1b",
        provider=ModelProvider.OLLAMA,
        display_name="Llama 3.2 1B",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["routing", "classification", "simple_qa"],
    ),
    "llama3.2": ModelSpec(
        model_id="llama3.2",
        provider=ModelProvider.OLLAMA,
        display_name="Llama 3.2 3B",
        context_window=128000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["general", "summarization", "content_drafts"],
    ),
    "mistral:7b": ModelSpec(
        model_id="mistral:7b",
        provider=ModelProvider.OLLAMA,
        display_name="Mistral 7B",
        context_window=32000,
        input_cost_per_m=0.0,
        output_cost_per_m=0.0,
        best_for=["code", "reasoning", "agent_tasks"],
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
    "general": OLLAMA_MODEL,
}


class UnifiedModelRouter:
    """Single model registry + generation adapter for local/cloud calls."""

    def __init__(self) -> None:
        self._local_client: OllamaClient | None = None
        self._cloud_client: CloudLLMClient | None = None

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

    def list_models(self) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        for spec in UNIFIED_MODEL_REGISTRY.values():
            models.append({
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "display_name": spec.display_name,
                "context_window": spec.context_window,
                "input_cost_per_m": spec.input_cost_per_m,
                "output_cost_per_m": spec.output_cost_per_m,
                "best_for": spec.best_for,
                "supports_tools": spec.supports_tools,
            })
        return models

    def resolve_model(self, task: str = "general", override_model: str | None = None) -> ModelSpec:
        model_id = override_model or DEFAULT_TASK_MODELS.get(task, DEFAULT_TASK_MODELS["general"])
        return UNIFIED_MODEL_REGISTRY.get(model_id, UNIFIED_MODEL_REGISTRY["llama3.2"])

    async def generate(
        self,
        prompt: str,
        system: str = "",
        task: str = "general",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        spec = self.resolve_model(task=task, override_model=model)

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
            # OPENAI/COPILOT entries currently route through the OpenRouter-compatible client
            # until dedicated provider clients are added.
            cloud_model_key = spec.model_id
            if spec.model_id == "openai:gpt-4o":
                cloud_model_key = "gpt-4o"
            elif spec.model_id == "copilot:chat":
                cloud_model_key = "claude-sonnet"

            output = await self.cloud_client.generate(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                model=cloud_model_key,
            )
            est_in = len(prompt + system) // 4
            est_out = len(output) // 4
            cost = (
                (est_in / 1_000_000) * spec.input_cost_per_m
                + (est_out / 1_000_000) * spec.output_cost_per_m
            )
            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": output,
                "estimated_cost_usd": round(cost, 6),
            }

        raise RuntimeError(f"Unsupported provider: {spec.provider}")

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
            _logging.getLogger(__name__).warning(
                "Tool definition violations before sanitization: %s", violations
            )

        reg = registry or ToolIdRegistry()

        # Sanitize all tool names before calling the API.
        sanitized_tools, reg = reg.sanitize_tool_definitions(tools)

        spec = self.resolve_model(task=task, override_model=model)

        if spec.provider == ModelProvider.OLLAMA:
            # Ollama tool calls use the same sanitized definitions; the response
            # contains a text block that BaseAgent parses via [TOOL:] — no
            # structured tool_calls needed here.
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
            cloud_model_key = spec.model_id
            if spec.model_id == "openai:gpt-4o":
                cloud_model_key = "gpt-4o"
            elif spec.model_id == "copilot:chat":
                cloud_model_key = "claude-sonnet"

            result = await self.cloud_client.generate_with_tools(
                messages=messages,
                tools=sanitized_tools,
                temperature=temperature,
                max_tokens=max_tokens,
                model=cloud_model_key,
                registry=reg,
            )

            # Desanitize tool_calls so callers see canonical names.
            raw_tool_calls: list[dict[str, Any]] = result.get("tool_calls", [])
            canonical_tool_calls = reg.desanitize_tool_calls(raw_tool_calls)

            est_in = sum(len(str(m)) for m in messages) // 4
            est_out = len(result.get("output", "")) // 4
            cost = (
                (est_in / 1_000_000) * spec.input_cost_per_m
                + (est_out / 1_000_000) * spec.output_cost_per_m
            )
            return {
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "output": result.get("output", ""),
                "tool_calls": canonical_tool_calls,
                "estimated_cost_usd": round(cost, 6),
                "registry": reg,
            }

        raise RuntimeError(f"Unsupported provider for tool calls: {spec.provider}")


unified_model_router = UnifiedModelRouter()
