"""
Fact memory middleware — hooks FactMemory into the MiddlewareChain.

- ``before_llm``: injects known facts into the system prompt
- ``after_llm``: extracts new facts from the conversation
"""

from __future__ import annotations

import logging

from deerflow.memory.facts import FactMemory
from deerflow.middleware.chain import LLMContext, Middleware

logger = logging.getLogger("deerflow.memory.middleware")


class FactMemoryMiddleware(Middleware):
    """Bridges FactMemory into the ordered middleware chain."""

    name = "fact_memory"
    priority = 40  # after governance/logging, before skills/summarization

    def __init__(self, fact_memory: FactMemory, inject_limit: int = 8) -> None:
        self._fm = fact_memory
        self._inject_limit = inject_limit
        # Track messages per agent to extract facts after LLM response
        self._pending: dict[str, list[dict[str, str]]] = {}

    async def before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        # Inject facts into the system prompt
        section = self._fm.build_prompt_section(meta.agent_id, limit=self._inject_limit)
        if section:
            for m in messages:
                if m.get("role") == "system":
                    m["content"] = m["content"] + "\n\n" + section
                    break

        # Stash messages for post-LLM extraction
        self._pending[meta.agent_id] = list(messages)
        return messages

    async def after_llm(self, response: str, meta: LLMContext) -> str:
        # Extract facts from the full conversation including the new response
        msgs = self._pending.pop(meta.agent_id, [])
        msgs.append({"role": "assistant", "content": response})

        # Only extract from the last few turns to keep it fast
        recent = [m for m in msgs if m.get("role") in ("user", "assistant")][-6:]
        if recent:
            try:
                await self._fm.extract(meta.agent_id, recent)
            except Exception as exc:
                logger.warning("fact_extract.error agent=%s err=%s", meta.agent_id, exc)

        return response
