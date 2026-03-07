"""
CloudLLM Client — OpenRouter-backed cloud LLM interface.
=========================================================
Mirrors the LocalLLM / OllamaClient interface so it can be
swapped in anywhere local inference is used.

Routes through OpenRouter (https://openrouter.ai) which provides
a single API key gateway to Kimi K2, GPT-4o, Claude, DeepSeek,
Gemini, and dozens of other models.

Security:
  - API key loaded from .env (OPENROUTER_API_KEY)
  - Never hardcoded, never logged, never committed
  - .env must have chmod 600

Usage:
    from lib.localllm.cloud_client import CloudLLMClient

    client = CloudLLMClient()
    response = await client.generate("Explain quantum computing")
    response = client.generate_sync("Explain quantum computing")
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.utils.tool_ids import ToolIdRegistry

import httpx

from backend.llm.profiles import ProfileRotator


# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available (graceful degradation)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    # Walk up to find .env relative to this file
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Model registry — canonical IDs for OpenRouter
CLOUD_MODELS: dict[str, dict[str, Any]] = {
    "kimi-k2": {
        "id": "moonshotai/kimi-k2",
        "name": "Kimi K2",
        "input_cost_per_m": 0.60,
        "output_cost_per_m": 0.60,
        "context_window": 131072,
        "strengths": ["design", "architecture", "reasoning", "code"],
    },
    "kimi-k2-thinking": {
        "id": "moonshotai/kimi-k2",
        "name": "Kimi K2 (Thinking)",
        "input_cost_per_m": 0.60,
        "output_cost_per_m": 2.00,
        "context_window": 131072,
        "strengths": ["deep-reasoning", "planning", "multi-step"],
        "extra_params": {"reasoning": {"effort": "high"}},
    },
    "gpt-4o": {
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "input_cost_per_m": 2.50,
        "output_cost_per_m": 10.00,
        "context_window": 128000,
        "strengths": ["general", "code", "reasoning"],
    },
    "claude-sonnet": {
        "id": "anthropic/claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "context_window": 200000,
        "strengths": ["code", "writing", "analysis"],
    },
    "deepseek-v3": {
        "id": "deepseek/deepseek-chat-v3-0324",
        "name": "DeepSeek V3",
        "input_cost_per_m": 0.27,
        "output_cost_per_m": 1.10,
        "context_window": 131072,
        "strengths": ["budget-reasoning", "code", "math"],
    },
    "gemini-flash": {
        "id": "google/gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "input_cost_per_m": 0.15,
        "output_cost_per_m": 0.60,
        "context_window": 1048576,
        "strengths": ["speed", "bulk", "metadata"],
    },
}

DEFAULT_CLOUD_MODEL = "kimi-k2"


class CloudLLMClient:
    """
    Cloud LLM client via OpenRouter.

    Interface-compatible with OllamaClient (backend/llm/__init__.py)
    and LocalLLM (lib/localllm/client.py) so it can be used as a
    drop-in replacement or alongside them in the hybrid router.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_CLOUD_MODEL,
        timeout: int = 120,
        site_url: str = "https://agentop.dev",
        site_name: str = "Agentop",
    ) -> None:
        self._fixed_api_key = (api_key or "").strip() or None
        self.profile_rotator = ProfileRotator()
        self.profile_rotator.load_from_env()

        if self._fixed_api_key:
            self.api_key = self._fixed_api_key
        else:
            try:
                bootstrap_profile = self.profile_rotator.get_profile("openrouter")
                self.api_key = bootstrap_profile.api_key
            except ValueError as exc:
                raise ValueError(
                    "OPENROUTER_API_KEY not set. "
                    "Add it to .env or pass api_key= to CloudLLMClient."
                ) from exc

        self.model = model
        self.timeout = timeout
        self.site_url = site_url
        self.site_name = site_name
        self._client: Optional[httpx.AsyncClient] = None

        # Cost tracking
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_requests = 0

    # ── Client lifecycle ─────────────────────────────────

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Headers ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }

    def _headers_for_key(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }

    def _get_openrouter_auth(self) -> tuple[str, str | None]:
        if self._fixed_api_key:
            return self._fixed_api_key, None

        profile = self.profile_rotator.get_profile("openrouter")
        return profile.api_key, profile.profile_id

    def _resolve_model_entry(self, model: Optional[str], resolved_model_id: str) -> dict[str, Any]:
        if model and model in CLOUD_MODELS:
            return CLOUD_MODELS[model]

        if self.model in CLOUD_MODELS and (model is None):
            return CLOUD_MODELS[self.model]

        for entry in CLOUD_MODELS.values():
            if entry.get("id") == resolved_model_id:
                return entry

        return CLOUD_MODELS[DEFAULT_CLOUD_MODEL]

    def _estimate_request_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: Optional[str],
        resolved_model_id: str,
    ) -> float:
        model_entry = self._resolve_model_entry(model=model, resolved_model_id=resolved_model_id)
        input_cost = (prompt_tokens / 1_000_000) * float(model_entry.get("input_cost_per_m", 0.0))
        output_cost = (completion_tokens / 1_000_000) * float(model_entry.get("output_cost_per_m", 0.0))
        return round(input_cost + output_cost, 6)

    # ── Model resolution ─────────────────────────────────

    def _resolve_model(self, model: Optional[str] = None) -> tuple[str, dict[str, Any]]:
        """
        Resolve a short model name to OpenRouter model ID + extra params.

        Accepts:
          - Short name: "kimi-k2", "gpt-4o", etc.
          - Full OpenRouter ID: "moonshotai/kimi-k2"
          - None → uses self.model default

        Returns: (openrouter_model_id, extra_params_dict)
        """
        key = model or self.model
        if key in CLOUD_MODELS:
            entry = CLOUD_MODELS[key]
            return entry["id"], entry.get("extra_params", {})
        # Assume it's a raw OpenRouter model ID
        return key, {}

    # ── Generate (matches OllamaClient.generate) ─────────

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Generate text completion. Interface matches OllamaClient.generate().
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self._chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    # ── Chat (matches OllamaClient.chat) ─────────────────

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Chat completion with message list. Interface matches OllamaClient.chat().
        """
        return await self._chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    # ── Chat with prompt+system (matches LocalLLM.chat) ──

    async def chat_prompt(
        self,
        prompt: str,
        system: str = "",
        history: Optional[list[dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Chat with prompt string. Interface matches LocalLLM.chat().
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        return await self._chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    # ── Structured JSON output ───────────────────────────

    async def chat_json(
        self,
        prompt: str,
        system: str = "",
        schema: Optional[dict] = None,
        temperature: float = 0.5,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> dict:
        """
        Get structured JSON response. Interface matches LocalLLM.chat_json().
        """
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "No markdown, no explanation, no code fences. "
            "Output raw JSON."
        )
        if schema:
            json_instruction += f"\n\nExpected schema:\n{json.dumps(schema, indent=2)}"

        full_system = (system + json_instruction) if system else json_instruction.strip()

        raw = await self.generate(
            prompt=prompt,
            system=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        return self._parse_json(raw)

    # ── Generate with tools (OpenAI tool-call protocol) ──

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
        registry: Optional["ToolIdRegistry"] = None,
    ) -> dict[str, Any]:
        """
        Chat completion with OpenAI-format tool definitions.

        All tool names in *tools* **must** already satisfy
        ``^[a-zA-Z0-9_-]{1,64}$`` (enforced by ``ToolIdRegistry.sanitize_tool_definitions``
        before this method is called from ``UnifiedModelRouter.generate_with_tools``).

        Returns a dict with:
          - ``output``     – assistant's text reply (may be empty when tools are called).
          - ``tool_calls`` – list of OpenAI ``tool_calls`` objects (may be empty).
          - ``usage``      – raw usage dict from the API.

        Args:
            messages:    OpenAI-format conversation history.
            tools:       Pre-sanitized OpenAI tool definitions.
            temperature: Sampling temperature.
            max_tokens:  Maximum output tokens.
            model:       Short model key or full OpenRouter model ID.
            registry:    ToolIdRegistry used for this session (informational; the
                         caller is responsible for desanitization).
        """
        model_id, extra_params = self._resolve_model(model)
        api_key, profile_id = self._get_openrouter_auth()

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(extra_params)

        try:
            resp = await self.client.post(
                OPENROUTER_API_URL,
                headers=self._headers_for_key(api_key),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            usage = data.get("usage", {})
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            self._total_input_tokens += prompt_tokens
            self._total_output_tokens += completion_tokens
            self._total_requests += 1

            if profile_id:
                call_cost = self._estimate_request_cost(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model,
                    resolved_model_id=model_id,
                )
                self.profile_rotator.record_spend(profile_id=profile_id, usd=call_cost)

            choices = data.get("choices", [])
            output_text = ""
            raw_tool_calls: list[dict[str, Any]] = []

            if choices:
                message = choices[0].get("message", {})
                output_text = message.get("content") or ""
                raw_tool_calls = message.get("tool_calls") or []

            return {
                "output": output_text,
                "tool_calls": raw_tool_calls,
                "usage": usage,
            }

        except httpx.ConnectError:
            raise ConnectionError(
                "Cannot reach OpenRouter API at "
                f"{OPENROUTER_API_URL}. Check network connectivity."
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:500]
            if status == 400:
                # Most likely cause: invalid tool name — surface clearly.
                raise ValueError(
                    f"OpenRouter 400 Bad Request (possible invalid tool name/ID). "
                    f"Verify tool names match ^[a-zA-Z0-9_-]{{1,64}}$. "
                    f"Body: {body}"
                )
            if status == 401:
                raise PermissionError(
                    "OpenRouter API key is invalid or expired. "
                    "Check OPENROUTER_API_KEY in .env"
                )
            if status == 429:
                raise RuntimeError("OpenRouter rate limit exceeded.")
            raise RuntimeError(f"OpenRouter error {status}: {body}")

    # ── Embed (stub — OpenRouter doesn't serve embeddings) ─

    async def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        """
        Embedding stub. Cloud client does NOT support embeddings.
        Use local Ollama for embeddings (they're free and fast).
        """
        raise NotImplementedError(
            "CloudLLMClient does not support embeddings. "
            "Use LocalLLM or OllamaClient for local embeddings."
        )

    # ── Health & Model listing ───────────────────────────

    async def is_available(self) -> bool:
        """Check if OpenRouter API is reachable and key is valid."""
        try:
            resp = await self.client.get(
                OPENROUTER_MODELS_URL,
                headers=self._headers_for_key(self._get_openrouter_auth()[0]),
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available cloud models (from our registry, not full OpenRouter catalog)."""
        return list(CLOUD_MODELS.keys())

    async def health(self) -> dict[str, Any]:
        """Full health check."""
        available = await self.is_available()
        return {
            "status": "ready" if available else "api_unreachable",
            "provider": "openrouter",
            "default_model": self.model,
            "available_models": list(CLOUD_MODELS.keys()),
            "total_requests": self._total_requests,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "estimated_cost_usd": self._estimate_total_cost(),
        }

    # ── Cost tracking ────────────────────────────────────

    def get_cost_stats(self) -> dict[str, Any]:
        """Return cumulative cost statistics."""
        return {
            "total_requests": self._total_requests,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "estimated_cost_usd": self._estimate_total_cost(),
        }

    def _estimate_total_cost(self) -> float:
        """Rough cost estimate based on default model pricing."""
        model_info = CLOUD_MODELS.get(self.model, CLOUD_MODELS[DEFAULT_CLOUD_MODEL])
        input_cost = (self._total_input_tokens / 1_000_000) * model_info["input_cost_per_m"]
        output_cost = (self._total_output_tokens / 1_000_000) * model_info["output_cost_per_m"]
        return round(input_cost + output_cost, 6)

    # ── Sync wrappers ────────────────────────────────────

    def generate_sync(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper around generate()."""
        return self._run_sync(
            self.generate(prompt, system, temperature, max_tokens, model)
        )

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper around chat()."""
        return self._run_sync(
            self.chat(messages, temperature, max_tokens, model)
        )

    def chat_json_sync(
        self,
        prompt: str,
        system: str = "",
        schema: Optional[dict] = None,
        temperature: float = 0.5,
        model: Optional[str] = None,
    ) -> dict:
        """Synchronous wrapper around chat_json()."""
        return self._run_sync(
            self.chat_json(prompt, system, schema, temperature, model=model)
        )

    # ── Internal: chat completion ────────────────────────

    async def _chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Core method: send messages to OpenRouter and return response text.
        """
        model_id, extra_params = self._resolve_model(model)
        api_key, profile_id = self._get_openrouter_auth()

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(extra_params)

        try:
            resp = await self.client.post(
                OPENROUTER_API_URL,
                headers=self._headers_for_key(api_key),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # Track usage
            usage = data.get("usage", {})
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            self._total_input_tokens += prompt_tokens
            self._total_output_tokens += completion_tokens
            self._total_requests += 1

            if profile_id:
                call_cost = self._estimate_request_cost(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model,
                    resolved_model_id=model_id,
                )
                self.profile_rotator.record_spend(profile_id=profile_id, usd=call_cost)

            # Extract content
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

            return ""

        except httpx.ConnectError:
            raise ConnectionError(
                "Cannot reach OpenRouter API at "
                f"{OPENROUTER_API_URL}. Check network connectivity."
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:500]
            if status == 401:
                raise PermissionError(
                    "OpenRouter API key is invalid or expired. "
                    "Check OPENROUTER_API_KEY in .env"
                )
            if status == 402:
                raise RuntimeError(
                    "OpenRouter credit balance exhausted. "
                    "Add credits at https://openrouter.ai/credits"
                )
            if status == 429:
                raise RuntimeError(
                    "OpenRouter rate limit exceeded. "
                    "Reduce request frequency or upgrade plan."
                )
            raise RuntimeError(
                f"OpenRouter error {status}: {body}"
            )

    # ── Internal: JSON parsing ───────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Best-effort JSON extraction from LLM output."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        cleaned = re.sub(r"```(?:json)?\s*", "", raw)
        cleaned = cleaned.strip().rstrip("`")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            match = re.search(pattern, raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        return {"error": "Failed to parse JSON", "raw": raw}

    # ── Internal: sync runner ────────────────────────────

    @staticmethod
    def _run_sync(coro):
        """Run async coroutine synchronously."""
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
