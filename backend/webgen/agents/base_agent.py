"""
WebAgent Base — Base class for all webgen agents.
==================================================
Provides shared LLM access, logging, and error handling.
Uses the backend OllamaClient for consistency with Agentop.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any

from backend.llm import OllamaClient
from backend.utils import logger


class WebAgentBase(ABC):
    """
    Base class for all web generation agents.

    Agents receive an OllamaClient and operate on SiteProject data.
    All LLM interaction goes through local Ollama.
    """

    name: str = "WebAgentBase"

    def __init__(self, llm: OllamaClient | None = None) -> None:
        self.llm = llm or OllamaClient()

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the agent's primary task."""
        ...

    # ── LLM helpers ──────────────────────────────────────

    async def ask_llm(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Send a prompt to the local LLM and get text back."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            result = await self.llm.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            logger.info(f"[{self.name}] LLM response: {len(result)} chars")
            return result
        except Exception as e:
            logger.error(f"[{self.name}] LLM error: {e}")
            return ""

    async def ask_llm_json(
        self,
        prompt: str,
        system: str = "",
        schema: dict | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Get a structured JSON response from the local LLM.

        Injects JSON formatting instructions and parses the response.
        """
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, no code fences. Output raw JSON."
        )
        if schema:
            json_instruction += f"\n\nExpected schema:\n{json.dumps(schema, indent=2)}"

        full_system = (system + json_instruction) if system else json_instruction.strip()

        raw = await self.ask_llm(
            prompt=prompt,
            system=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return self._parse_json(raw)

    # ── Sync wrappers ────────────────────────────────────

    def run_sync(self, *args: Any, **kwargs: Any) -> Any:
        """Synchronous wrapper around run()."""
        return self._run_sync(self.run(*args, **kwargs))

    def ask_llm_sync(self, prompt: str, system: str = "", **kw: Any) -> str:
        return self._run_sync(self.ask_llm(prompt, system, **kw))

    def ask_llm_json_sync(self, prompt: str, system: str = "", **kw: Any) -> dict:
        return self._run_sync(self.ask_llm_json(prompt, system, **kw))

    # ── Internals ────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Best-effort JSON extraction from LLM output."""
        if not raw:
            return {"error": "Empty LLM response"}

        # Direct parse
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

        # Find first JSON object or array
        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            match = re.search(pattern, raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        return {"error": "Failed to parse JSON", "raw": raw[:500]}

    @staticmethod
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
