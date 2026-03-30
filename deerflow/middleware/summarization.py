"""
Context summarization middleware — compresses old conversation messages
when approaching the LLM's token budget.

Plugs into the MiddlewareChain as a ``before_llm`` hook. When the message
list exceeds a configurable threshold, the oldest messages are summarized
into a single "recap" message by the LLM, preserving recent context while
staying within budget.

Critical for Ollama's smaller context windows (llama3.2 = ~8 K tokens).

Usage::

    from deerflow.middleware.chain import MiddlewareChain
    from deerflow.middleware.summarization import SummarizationMiddleware

    chain = MiddlewareChain()
    chain.add(SummarizationMiddleware(llm_client, max_history=20))
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.middleware.chain import LLMContext, Middleware

logger = logging.getLogger("deerflow.middleware.summarization")

_SUMMARIZE_SYSTEM = """\
Summarize the following conversation messages into a concise recap.
Keep all actionable facts — tool results, decisions, user requirements.
Drop pleasantries, filler, and anything repeated.
Output a single paragraph, max 300 words. No markdown formatting."""


class SummarizationMiddleware(Middleware):
    """
    Compress older messages when conversation length exceeds *max_history*.

    The first message (system prompt) is always preserved. Recent messages
    (the last *keep_recent*) are preserved as-is. Everything in between is
    summarized into one "assistant" message tagged ``[CONTEXT RECAP]``.
    """

    name = "summarization"
    priority = 50  # runs after governance, before the actual LLM call

    def __init__(
        self,
        llm_client: Any,
        max_history: int = 20,
        keep_recent: int = 6,
    ) -> None:
        self._llm = llm_client
        self._max_history = max_history
        self._keep_recent = keep_recent
        # Cache summaries so we don't re-summarise the same prefix
        self._cache: dict[str, str] = {}

    async def before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        if len(messages) <= self._max_history:
            return messages

        # Separate system prompt (index 0) from the rest
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= self._keep_recent:
            return messages

        to_summarize = non_system[: -self._keep_recent]
        to_keep = non_system[-self._keep_recent :]

        # Build a cache key from the content being summarized
        cache_key = _cache_key(to_summarize)
        summary_text = self._cache.get(cache_key)

        if summary_text is None:
            summary_text = await self._summarize(to_summarize)
            self._cache[cache_key] = summary_text
            logger.info(
                "summarization.compressed agent=%s msgs=%d->1 chars=%d",
                meta.agent_id,
                len(to_summarize),
                len(summary_text),
            )

        recap_msg = {
            "role": "assistant",
            "content": f"[CONTEXT RECAP] {summary_text}",
        }

        return system_msgs + [recap_msg] + to_keep

    async def _summarize(
        self, messages: list[dict[str, str]]
    ) -> str:
        conversation = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages
        )

        try:
            return await self._llm.generate(
                prompt=conversation,
                system=_SUMMARIZE_SYSTEM,
                temperature=0.3,
                max_tokens=512,
            )
        except (ConnectionError, RuntimeError) as exc:
            logger.warning("summarization.llm_error=%s", exc)
            # Graceful degradation: just keep last N messages raw
            return "(Summary unavailable — prior context truncated.)"


def _cache_key(messages: list[dict[str, str]]) -> str:
    """Deterministic hash of message list for caching."""
    import hashlib

    content = "|".join(m.get("content", "") for m in messages)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
