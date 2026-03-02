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

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info(f"OllamaClient initialized: model={model}, url={base_url}")

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

            # Emit activity event for live preview
            try:
                from backend.tasks import task_tracker as _tt
                _tt.emit_activity("llm_response", {
                    "model": self.model,
                    "endpoint": "generate",
                    "prompt_len": len(prompt),
                    "response_len": len(result),
                })
            except Exception:
                pass

            logger.info(
                f"LLM generate: model={self.model}, "
                f"prompt_len={len(prompt)}, response_len={len(result)}"
            )
            return result

        except httpx.ConnectError:
            error_msg = (
                f"Cannot connect to Ollama at {self.base_url}. "
                "Ensure Ollama is running: `ollama serve`"
            )
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

            # Emit activity event for live preview
            try:
                from backend.tasks import task_tracker as _tt
                _tt.emit_activity("llm_response", {
                    "model": self.model,
                    "endpoint": "chat",
                    "messages": len(messages),
                    "response_len": len(result),
                })
            except Exception:
                pass

            logger.info(
                f"LLM chat: model={self.model}, "
                f"messages={len(messages)}, response_len={len(result)}"
            )
            return result

        except httpx.ConnectError:
            error_msg = (
                f"Cannot connect to Ollama at {self.base_url}. "
                "Ensure Ollama is running: `ollama serve`"
            )
            logger.error(error_msg)
            raise ConnectionError(error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"Ollama HTTP error: {e.response.status_code} — {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings for text using local Ollama embeddings endpoint."""
        if not text.strip():
            return []

        payload = {
            "model": self.model,
            "input": text,
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/api/embed",
                json=payload,
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
        response = await self._client.post(
            f"{self.base_url}/api/embeddings",
            json=legacy_payload,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("embedding", [])

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
                self._router = LLMRouter(
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
