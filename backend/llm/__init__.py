"""
Ollama LLM Client — Local-first LLM interface.
===============================================
Communicates with the Ollama server running locally.
No cloud dependency. Configurable model selection.

Governance Note: This module MUST NOT depend on the frontend (INV-1).
It is a pure inference client with no state management.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from backend.utils import logger


class OllamaClient:
    """
    HTTP client for the local Ollama LLM server.

    Responsibilities:
    - Send prompts and receive completions
    - Handle connection errors gracefully
    - Log all LLM interactions

    Non-responsibilities (by design):
    - No state management
    - No tool execution
    - No agent logic
    """

    # Class-level accumulators — shared across all OllamaClient instances
    _global_tokens_in: int = 0
    _global_tokens_out: int = 0
    _global_requests: int = 0

    @classmethod
    def get_token_counts(cls) -> dict[str, int]:
        """Return accumulated local (Ollama) token usage."""
        return {
            "tokens_in": cls._global_tokens_in,
            "tokens_out": cls._global_tokens_out,
            "total": cls._global_tokens_in + cls._global_tokens_out,
            "requests": cls._global_requests,
        }

    @classmethod
    def _record_usage(cls, prompt_eval_count: int, eval_count: int) -> None:
        """Thread-safe accumulation (GIL-protected int increment is atomic in CPython)."""
        cls._global_tokens_in += prompt_eval_count
        cls._global_tokens_out += eval_count
        cls._global_requests += 1

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        logger.info(f"OllamaClient initialized: model={model}, url={base_url}")

    async def prewarm(self) -> None:
        """Load the model into Ollama memory without generating any output.

        Fires a no-op /api/generate request so that the model is resident
        before the first real chat_with_schema call.  Returns immediately if
        the model is already loaded.  Uses the client's full timeout so that
        large models (7B+) have time to load from disk.
        """
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": "", "stream": False, "keep_alive": "10m"},
            )
            resp.raise_for_status()
            logger.info(f"OllamaClient prewarm complete: model={self.model}")
        except Exception as exc:  # non-fatal — generation will surface any real error
            logger.warning(f"OllamaClient prewarm failed for {self.model}: {exc}")

    async def unload(self) -> None:
        """Evict this model from Ollama RAM by setting keep_alive to 0.

        Safe to call at any time. Ollama releases VRAM/RAM on the next GC
        cycle. Subsequent requests will trigger a fresh cold load (~5-30s).
        """
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": "", "stream": False, "keep_alive": 0},
            )
            resp.raise_for_status()
            logger.info(f"OllamaClient: model={self.model} unloaded from Ollama RAM")
        except Exception as exc:
            logger.warning(f"OllamaClient unload failed for {self.model}: {exc}")

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Generate a completion from the local Ollama model.

        Args:
            prompt: The user/agent prompt.
            system: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            The generated text response.

        Raises:
            ConnectionError: If Ollama server is not reachable.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        try:
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("response", "")

            # Capture Ollama token counts (present on non-streaming responses)
            _pin = data.get("prompt_eval_count", 0) or 0
            _pout = data.get("eval_count", 0) or 0
            OllamaClient._record_usage(_pin, _pout)

            # Emit activity event for live preview
            try:
                from backend.tasks import task_tracker as _tt

                _tt.emit_activity(
                    "llm_response",
                    {
                        "model": self.model,
                        "endpoint": "generate",
                        "prompt_len": len(prompt),
                        "response_len": len(result),
                        "tokens_in": _pin,
                        "tokens_out": _pout,
                    },
                )
            except Exception:
                pass

            logger.info(f"LLM generate: model={self.model}, prompt_len={len(prompt)}, response_len={len(result)}, tokens=({_pin}+{_pout})")
            return result

        except httpx.ConnectError:
            error_msg = f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running: `ollama serve`"
            logger.error(error_msg)
            raise ConnectionError(error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"Ollama HTTP error: {e.response.status_code} — {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Chat completion via Ollama's chat endpoint.

        Args:
            messages: List of {role, content} message dicts.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            The assistant's response text.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("message", {}).get("content", "")

            # Capture Ollama token counts
            _pin = data.get("prompt_eval_count", 0) or 0
            _pout = data.get("eval_count", 0) or 0
            OllamaClient._record_usage(_pin, _pout)

            # Emit activity event for live preview
            try:
                from backend.tasks import task_tracker as _tt

                _tt.emit_activity(
                    "llm_response",
                    {
                        "model": self.model,
                        "endpoint": "chat",
                        "messages": len(messages),
                        "response_len": len(result),
                        "tokens_in": _pin,
                        "tokens_out": _pout,
                    },
                )
            except Exception:
                pass

            logger.info(f"LLM chat: model={self.model}, messages={len(messages)}, response_len={len(result)}, tokens=({_pin}+{_pout})")
            return result

        except httpx.ConnectError:
            error_msg = f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running: `ollama serve`"
            logger.error(error_msg)
            raise ConnectionError(error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"Ollama HTTP error: {e.response.status_code} — {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings for text using local Ollama embeddings endpoint.

        Uses a short 10-second timeout independent of OLLAMA_TIMEOUT so that
        generation models (e.g. qwen3:4b) fail fast when asked to embed rather
        than blocking the executor for the full generation timeout.
        """
        if not text.strip():
            return []

        _embed_timeout = httpx.Timeout(10.0)

        payload = {
            "model": self.model,
            "input": text,
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/api/embed",
                json=payload,
                timeout=_embed_timeout,
            )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings", [])
            if embeddings and isinstance(embeddings, list) and isinstance(embeddings[0], list):
                return embeddings[0]
        except Exception:
            pass

        # Backward compatibility with /api/embeddings
        legacy_payload = {
            "model": self.model,
            "prompt": text,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/api/embeddings",
                json=legacy_payload,
                timeout=_embed_timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding", [])
        except Exception:
            return []

    async def is_available(self) -> bool:
        """Check if the Ollama server is reachable."""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models on the Ollama server."""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    async def chat_with_schema(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        Schema-constrained chat generation for local Ollama models.

        Uses Ollama's native JSON format mode combined with a schema description
        injected into the system prompt. On parse failure, retries up to
        ``max_retries`` times before raising.

        Args:
            messages:    OpenAI-style message list (role/content dicts).
            schema:      JSON Schema object the response must conform to.
            temperature: Sampling temperature (low default for determinism).
            max_tokens:  Maximum output tokens.
            max_retries: Number of additional attempts on JSON parse failure.

        Returns:
            Parsed dict conforming to the provided schema.

        Raises:
            ValueError:  If the model fails to produce valid JSON after retries.
            ConnectionError: If Ollama is unreachable.
        """
        import json as _json

        schema_hint = _json.dumps(schema, indent=2)
        # Append /no_think for Qwen3 models — suppresses the <think> chain-of-thought
        # block that can consume 500-1500 tokens before the JSON output.  The directive
        # is a documented soft-switch (qwen.readthedocs.io) and is ignored by other models.
        _is_qwen3 = "qwen3" in self.model.lower()
        _no_think_suffix = " /no_think" if _is_qwen3 else ""
        schema_injection = (
            "You MUST respond with valid JSON that matches this schema exactly. "
            f"Do not include any text outside the JSON object.{_no_think_suffix}\n\n"
            f"Schema:\n{schema_hint}"
        )

        # Prepend or merge schema hint into system message
        patched_messages: list[dict[str, Any]] = []
        has_system = False
        for msg in messages:
            if msg.get("role") == "system":
                patched_messages.append({"role": "system", "content": f"{msg['content']}\n\n{schema_injection}"})
                has_system = True
            else:
                patched_messages.append(msg)
        if not has_system:
            patched_messages = [{"role": "system", "content": schema_injection}, *patched_messages]

        _options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        # Ollama >=0.6 honours think:false to suppress CoT at the API level for Qwen3.
        if _is_qwen3:
            _options["think"] = False

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": patched_messages,
            "stream": False,
            "format": "json",
            "options": _options,
        }

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                raw_text = data.get("message", {}).get("content", "")
                # Strip qwen3-style <think>...</think> reasoning blocks before parsing.
                # These appear when the model emits chain-of-thought prior to JSON output.
                import re as _re
                raw_text = _re.sub(r"<think>.*?</think>", "", raw_text, flags=_re.DOTALL).strip()
                # Also strip markdown code fences (```json ... ```)
                raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = _json.loads(raw_text)
                _pin = data.get("prompt_eval_count", 0) or 0
                _pout = data.get("eval_count", 0) or 0
                OllamaClient._record_usage(_pin, _pout)
                logger.info(f"chat_with_schema: model={self.model} attempt={attempt + 1} success tokens=({_pin}+{_pout})")
                return parsed
            except _json.JSONDecodeError as exc:
                last_error = exc
                logger.warning(f"chat_with_schema: JSON parse failure attempt={attempt + 1}: {exc}")
                continue
            except httpx.ConnectError:
                error_msg = f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running."
                logger.error(error_msg)
                raise ConnectionError(error_msg)
            except httpx.HTTPStatusError as exc:
                error_msg = f"Ollama HTTP error: {exc.response.status_code} — {exc.response.text}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

        raise ValueError(
            f"chat_with_schema: failed to produce valid JSON after {max_retries + 1} attempts. Last error: {last_error}"
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# HybridClient — Drop-in replacement that routes local ↔ cloud
# ---------------------------------------------------------------------------
# Uses LLMRouter under the hood but presents the same interface as
# OllamaClient so existing agents don't need code changes.
# ---------------------------------------------------------------------------


class HybridClient:
    """
    Hybrid LLM client — presents the OllamaClient interface but
    routes requests through the LLMRouter for local/cloud splitting.

    Drop-in replacement: agents call generate() and chat() exactly
    as they do with OllamaClient. The `task` kwarg is the only addition.

    Usage:
        client = HybridClient(mode="hybrid")
        response = await client.generate("Design a nav component", task="design_system")
    """

    def __init__(
        self,
        mode: str = "hybrid",
        monthly_budget: float = 50.0,
    ) -> None:
        from backend.config import (
            OLLAMA_BASE_URL,
            OLLAMA_MODEL,
            OLLAMA_TIMEOUT,
        )

        self.mode = mode
        self.model = OLLAMA_MODEL
        self._local = OllamaClient(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
            timeout=OLLAMA_TIMEOUT,
        )

        # Lazy-init cloud + router only when needed
        self._router = None
        self._monthly_budget = monthly_budget

    @property
    def router(self):
        """Lazy-init the LLMRouter (avoids import cost when local_only)."""
        if self._router is None:
            try:
                from lib.localllm.client import LocalLLM
                from lib.localllm.cloud_client import CloudLLMClient
                from lib.localllm.router import LLMRouter

                local_llm = LocalLLM()
                cloud_llm = CloudLLMClient() if self.mode != "local_only" else None
                self._router = LLMRouter(  # type: ignore[assignment]
                    mode=self.mode,
                    local_client=local_llm,
                    cloud_client=cloud_llm,
                    monthly_budget_usd=self._monthly_budget,
                )
            except Exception as exc:
                logger.warning(f"HybridClient: router init failed ({exc}), falling back to local-only")
                self._router = None
        return self._router

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        task: str = "general",
    ) -> str:
        """
        Generate completion — routes through LLMRouter in hybrid/cloud mode,
        falls back to local OllamaClient if router unavailable.
        """
        if self.mode == "local_only" or self.router is None:
            return await self._local.generate(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await self.router.generate(
            prompt=prompt,
            system=system,
            task=task,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        task: str = "general",
    ) -> str:
        """
        Chat completion — routes through LLMRouter in hybrid/cloud mode.
        """
        if self.mode == "local_only" or self.router is None:
            return await self._local.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await self.router.chat(
            messages=messages,
            task=task,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def embed(self, text: str) -> list[float]:
        """Embeddings always go local (free + fast)."""
        return await self._local.embed(text)

    async def is_available(self) -> bool:
        """Check local availability (primary requirement)."""
        return await self._local.is_available()

    async def list_models(self) -> list[str]:
        """List local models + cloud model names."""
        local_models = await self._local.list_models()
        if self.mode != "local_only":
            try:
                from lib.localllm.cloud_client import CLOUD_MODELS

                cloud_names = [f"cloud:{k}" for k in CLOUD_MODELS]
                return local_models + cloud_names
            except ImportError:
                pass
        return local_models

    async def health(self) -> dict:
        """Combined health status."""
        if self.router:
            return await self.router.health()
        return {
            "mode": "local_only",
            "local": await self._local.is_available(),
            "cloud": False,
        }

    def get_stats(self) -> dict:
        """Return routing stats (empty if local-only)."""
        if self.router:
            return self.router.get_stats()
        return {"mode": "local_only", "note": "no cloud routing active"}

    async def close(self) -> None:
        """Close all clients."""
        await self._local.close()
        if self.router:
            await self.router.close()
