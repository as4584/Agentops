"""
LocalLLM Client — Portable async/sync Ollama client.
=====================================================
Zero cloud dependency. One file. Drop anywhere.

Supports:
  - Chat completions (single + multi-turn)
  - Text generation
  - Structured JSON output
  - Embeddings
  - Model management (list, pull, delete)
  - Sync wrappers for non-async code
  - Connection health checks
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional

import httpx


# ---------------------------------------------------------------------------
# Defaults (overridable via env vars or constructor)
# ---------------------------------------------------------------------------
_DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
_DEFAULT_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))


class LocalLLM:
    """
    Portable local LLM client for Ollama.

    Works standalone — no dependency on Agentop backend.
    Copy this file + models.py into any project.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    # ── Client lifecycle ─────────────────────────────────

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Chat (primary interface) ─────────────────────────

    async def chat(
        self,
        prompt: str,
        system: str = "",
        history: Optional[list[dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Send a chat message and get a response.

        Args:
            prompt: User message text.
            system: Optional system prompt.
            history: Optional conversation history [{role, content}, ...].
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
            max_tokens: Maximum response tokens.
            model: Override the default model for this call.

        Returns:
            The assistant's response text.
        """
        messages: list[dict[str, str]] = []

        if system:
            messages.append({"role": "system", "content": system})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": prompt})

        return await self.chat_messages(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    async def chat_messages(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Multi-turn chat completion with raw message list.
        """
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        resp = await self._post("/api/chat", payload)
        return resp.get("message", {}).get("content", "")

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
        Get a structured JSON response from the LLM.

        Injects JSON formatting instructions into the system prompt.
        Parses and returns a Python dict.

        Args:
            prompt: User message.
            system: Base system prompt (JSON instructions appended).
            schema: Optional example schema to guide the LLM.
            temperature: Lower = more deterministic JSON.
            max_tokens: Max response tokens.
            model: Override model.

        Returns:
            Parsed JSON dict. Returns {"error": ..., "raw": ...} on parse failure.
        """
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "No markdown, no explanation, no code fences. "
            "Output raw JSON."
        )
        if schema:
            json_instruction += f"\n\nExpected schema:\n{json.dumps(schema, indent=2)}"

        full_system = (system + json_instruction) if system else json_instruction.strip()

        raw = await self.chat(
            prompt=prompt,
            system=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

        return self._parse_json(raw)

    # ── Text generation (simpler endpoint) ───────────────

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """
        Simple text generation (non-chat format).
        """
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        resp = await self._post("/api/generate", payload)
        return resp.get("response", "")

    # ── Embeddings ───────────────────────────────────────

    async def embed(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> list[float]:
        """
        Generate embedding vector for text.
        Falls back to legacy /api/embeddings endpoint if needed.
        """
        if not text.strip():
            return []

        use_model = model or self.model

        # Try new endpoint first
        try:
            resp = await self._post("/api/embed", {
                "model": use_model,
                "input": text,
            })
            embeddings = resp.get("embeddings", [])
            if embeddings and isinstance(embeddings[0], list):
                return embeddings[0]
            if embeddings and isinstance(embeddings[0], (int, float)):
                return embeddings
        except Exception:
            pass

        # Fallback to legacy endpoint
        resp = await self._post("/api/embeddings", {
            "model": use_model,
            "prompt": text,
        })
        return resp.get("embedding", [])

    # ── Model management ─────────────────────────────────

    async def list_models(self) -> list[str]:
        """List all locally available Ollama models."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def pull_model(self, model_name: str) -> bool:
        """
        Pull a model from Ollama registry.
        This can take minutes for large models.
        """
        try:
            resp = await self.client.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=600,  # 10 min for large models
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    async def delete_model(self, model_name: str) -> bool:
        """Delete a local model."""
        try:
            resp = await self.client.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def model_info(self, model_name: Optional[str] = None) -> dict:
        """Get details about a model."""
        try:
            resp = await self._post("/api/show", {
                "name": model_name or self.model,
            })
            return resp
        except Exception:
            return {}

    # ── Health ───────────────────────────────────────────

    async def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def health(self) -> dict:
        """Full health check — server reachable + model loaded."""
        available = await self.is_available()
        if not available:
            return {
                "status": "offline",
                "server": self.base_url,
                "model": self.model,
            }

        models = await self.list_models()
        model_ready = any(self.model in m for m in models)

        return {
            "status": "ready" if model_ready else "model_missing",
            "server": self.base_url,
            "model": self.model,
            "model_available": model_ready,
            "available_models": models,
        }

    # ── Sync wrappers (for non-async code) ───────────────

    def chat_sync(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper around chat()."""
        return self._run_sync(
            self.chat(prompt, system, temperature=temperature,
                      max_tokens=max_tokens, model=model)
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

    def embed_sync(self, text: str, model: Optional[str] = None) -> list[float]:
        """Synchronous wrapper around embed()."""
        return self._run_sync(self.embed(text, model))

    def is_available_sync(self) -> bool:
        """Synchronous wrapper around is_available()."""
        return self._run_sync(self.is_available())

    # ── Internals ────────────────────────────────────────

    async def _post(self, endpoint: str, payload: dict) -> dict:
        """POST to Ollama and return parsed JSON."""
        try:
            resp = await self.client.post(
                f"{self.base_url}{endpoint}",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Start it with: ollama serve"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama error {e.response.status_code}: {e.response.text}"
            )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Best-effort JSON extraction from LLM output."""
        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Strip markdown fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw)
        cleaned = cleaned.strip().rstrip("`")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find first { ... } or [ ... ] block
        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            match = re.search(pattern, raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        return {"error": "Failed to parse JSON", "raw": raw}

    @staticmethod
    def _run_sync(coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop — use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)
