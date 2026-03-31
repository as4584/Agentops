"""
LLM-powered fact memory — extracts, deduplicates, and retrieves structured
facts from agent conversation history.

Inspired by DeerFlow's persistent fact store, but built on Agentop's
MemoryStore (namespace isolation, INV-4) and OllamaClient.

Usage::

    fact_mem = FactMemory(llm_client, memory_store)

    # After a conversation turn, extract facts
    new_facts = await fact_mem.extract(
        agent_id="devops_agent",
        messages=[{"role": "user", "content": "Deploy to staging on Fridays"}],
    )

    # Retrieve top facts for prompt injection
    top = fact_mem.get_top_facts("devops_agent", limit=5)
    prompt_section = fact_mem.build_prompt_section("devops_agent")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("deerflow.memory.facts")

FACTS_KEY = "deerflow_facts"

# ---------------------------------------------------------------------------
# Fact model
# ---------------------------------------------------------------------------


class FactCategory(str, Enum):
    PREFERENCE = "preference"
    KNOWLEDGE = "knowledge"
    CONTEXT = "context"
    BEHAVIOR = "behavior"
    GOAL = "goal"


@dataclass
class Fact:
    content: str
    category: FactCategory
    confidence: float  # 0.0 – 1.0
    source_agent: str
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "category": self.category.value,
            "confidence": self.confidence,
            "source_agent": self.source_agent,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fact:
        return cls(
            content=d["content"],
            category=FactCategory(d["category"]),
            confidence=d["confidence"],
            source_agent=d["source_agent"],
            created_at=d.get("created_at", 0.0),
            access_count=d.get("access_count", 0),
            last_accessed=d.get("last_accessed", 0.0),
        )


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = """\
You are a fact extractor. Given a conversation snippet, output a JSON array
of facts. Each fact object has:
  "content": short declarative sentence,
  "category": one of preference|knowledge|context|behavior|goal,
  "confidence": float 0.0-1.0

Rules:
- Only extract concrete, actionable facts — skip pleasantries.
- Deduplicate: if two facts say the same thing keep the more specific one.
- Output ONLY valid JSON — no markdown fences, no commentary.
- If no facts can be extracted, output an empty array: []
"""


# ---------------------------------------------------------------------------
# FactMemory
# ---------------------------------------------------------------------------


class FactMemory:
    """
    LLM-powered fact extraction and retrieval built on MemoryStore.

    Stores facts under ``{agent_namespace}/deerflow_facts`` so each
    agent's facts are namespace-isolated (INV-4).
    """

    def __init__(self, llm_client: Any, memory_store: Any) -> None:
        self._llm = llm_client
        self._mem = memory_store

    # -- extract ------------------------------------------------------------

    async def extract(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        min_confidence: float = 0.4,
    ) -> list[Fact]:
        """Use the LLM to pull facts out of *messages*, store them."""
        if not messages:
            return []

        conversation = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages[-10:]  # last 10 messages only
        )

        try:
            raw = await self._llm.generate(
                prompt=conversation,
                system=_EXTRACTION_SYSTEM,
                temperature=0.2,
                max_tokens=1024,
            )
        except (ConnectionError, RuntimeError) as exc:
            logger.warning("fact_extract llm_error=%s", exc)
            return []

        parsed = self._parse_facts(raw, agent_id)
        filtered = [f for f in parsed if f.confidence >= min_confidence]

        if filtered:
            self._merge_and_store(agent_id, filtered)
            logger.info("facts.extracted agent=%s count=%d", agent_id, len(filtered))

        return filtered

    # -- read ---------------------------------------------------------------

    def get_all_facts(self, agent_id: str) -> list[Fact]:
        raw = self._mem.read(agent_id, FACTS_KEY, default=[])
        return [Fact.from_dict(d) for d in raw]

    def get_top_facts(
        self,
        agent_id: str,
        limit: int = 10,
        category: FactCategory | None = None,
    ) -> list[Fact]:
        """Top facts ranked by confidence * recency * access frequency."""
        facts = self.get_all_facts(agent_id)
        if category:
            facts = [f for f in facts if f.category == category]

        now = time.time()

        def score(f: Fact) -> float:
            age_days = max((now - f.created_at) / 86400, 0.1)
            recency = 1.0 / age_days
            return f.confidence * (1 + 0.1 * f.access_count) * recency

        facts.sort(key=score, reverse=True)

        # bump access counts for returned facts
        for f in facts[:limit]:
            f.access_count += 1
            f.last_accessed = now

        # persist updated counters
        self._mem.write(agent_id, FACTS_KEY, [f.to_dict() for f in self.get_all_facts(agent_id)])

        return facts[:limit]

    def build_prompt_section(self, agent_id: str, limit: int = 8) -> str:
        """Build a markdown section for injection into the agent's system prompt."""
        top = self.get_top_facts(agent_id, limit=limit)
        if not top:
            return ""

        lines = ["## Known Facts (from prior interactions)\n"]
        for f in top:
            lines.append(f"- [{f.category.value}] {f.content} (confidence: {f.confidence:.0%})")
        return "\n".join(lines)

    # -- internals ----------------------------------------------------------

    def _parse_facts(self, raw: str, agent_id: str) -> list[Fact]:
        # Strip markdown fences if the LLM wraps them
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("facts.parse_error raw=%s", text[:200])
            return []

        if not isinstance(items, list):
            return []

        facts: list[Fact] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                facts.append(
                    Fact(
                        content=str(item["content"]),
                        category=FactCategory(item.get("category", "knowledge")),
                        confidence=float(item.get("confidence", 0.5)),
                        source_agent=agent_id,
                    )
                )
            except (KeyError, ValueError):
                continue
        return facts

    def _merge_and_store(self, agent_id: str, new_facts: list[Fact]) -> None:
        """Deduplicate by content similarity then persist."""
        existing = self.get_all_facts(agent_id)
        existing_contents = {f.content.lower().strip() for f in existing}

        merged = list(existing)
        for nf in new_facts:
            normalised = nf.content.lower().strip()
            if normalised not in existing_contents:
                merged.append(nf)
                existing_contents.add(normalised)
            else:
                # Update confidence if new extraction is higher
                for ef in merged:
                    if ef.content.lower().strip() == normalised:
                        ef.confidence = max(ef.confidence, nf.confidence)
                        break

        self._mem.write(agent_id, FACTS_KEY, [f.to_dict() for f in merged])
