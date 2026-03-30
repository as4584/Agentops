"""
Progressive skill loader — on-demand skill injection based on intent
classification, inspired by DeerFlow's progressive Markdown skill loading.

Instead of injecting all 15+ domain knowledge packs into every agent prompt
(burning tokens), this module:

1. Classifies the user's intent against a keyword/pattern index
2. Selects only the relevant skills
3. Loads their content lazily
4. Builds a minimal prompt section

Integrates with Agentop's SkillRegistry (manifest + legacy JSON) and
plugs into the MiddlewareChain as a ``before_llm`` hook.

Usage::

    loader = ProgressiveSkillLoader(skill_registry)

    # As middleware
    chain.add(loader.as_middleware())

    # Or direct
    prompt_section = loader.select_and_build(
        message="How do I set up CI/CD for the staging server?",
        agent_id="devops_agent",
        max_skills=3,
    )
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from deerflow.middleware.chain import LLMContext, Middleware

logger = logging.getLogger("deerflow.skills.progressive")


# ---------------------------------------------------------------------------
# Keyword-to-skill intent index
# ---------------------------------------------------------------------------

# Maps regex patterns to skill IDs. Evaluated in order; first N matches win.
# This covers Agentop's 15 legacy JSON domain packs + manifest skills.
_INTENT_INDEX: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ci[/-]?cd|deploy|release|pipeline|github.actions", re.I), "release_engineering"),
    (re.compile(r"frontend|react|next\.?js|css|tailwind|component", re.I), "frontend_architecture"),
    (re.compile(r"fullstack|api.route|backend.+frontend|end.to.end", re.I), "fullstack_engineering"),
    (re.compile(r"hexagonal|port.+adapter|clean.arch|domain.driven", re.I), "hexagonal_architecture"),
    (re.compile(r"state.machine|fsm|transition|statechart", re.I), "state_machine_design"),
    (re.compile(r"infrastructure|resilience|failover|disaster|uptime", re.I), "infrastructure_resilience"),
    (re.compile(r"agent.design|multi.agent|orchestrat|langgraph", re.I), "agent_design_patterns"),
    (re.compile(r"enterprise.ai|mlops|model.deploy|ml.pipeline", re.I), "applied_enterprise_ai"),
    (re.compile(r"business.analy|stakeholder|requirement|brd|use.case", re.I), "business_analysis"),
    (re.compile(r"business.ops|operations|kpi|workflow.automat", re.I), "business_operations"),
    (re.compile(r"community|training|workshop|curriculum", re.I), "community_ai_training"),
    (re.compile(r"data.system|knowledge.graph|vector|embedding|rag", re.I), "data_knowledge_systems"),
    (re.compile(r"systems.analy|architecture.review|design.doc", re.I), "systems_analysis_design"),
    (re.compile(r"token|cost|budget|optimi[sz]|cheap|expensive", re.I), "token_optimization"),
    (re.compile(r"web.dev|html|javascript|typescript|dom|browser", re.I), "web_development_inquiry"),
    (re.compile(r"newsletter|email|weekly.tips", re.I), "newsletter_weekly_tips"),
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SkillMatch:
    """A skill selected by intent classification."""

    skill_id: str
    pattern_matched: str
    relevance_rank: int  # 1 = best match


# ---------------------------------------------------------------------------
# ProgressiveSkillLoader
# ---------------------------------------------------------------------------

class ProgressiveSkillLoader:
    """
    Lazy-loads only the skills relevant to the current message.

    Wraps Agentop's SkillRegistry and adds intent-based selection.
    """

    def __init__(self, skill_registry: Any) -> None:
        self._registry = skill_registry

    def classify_intent(
        self, message: str, max_skills: int = 3
    ) -> list[SkillMatch]:
        """Match *message* against the keyword index, return top N skills."""
        matches: list[SkillMatch] = []
        seen: set[str] = set()

        for pattern, skill_id in _INTENT_INDEX:
            if pattern.search(message) and skill_id not in seen:
                matches.append(
                    SkillMatch(
                        skill_id=skill_id,
                        pattern_matched=pattern.pattern,
                        relevance_rank=len(matches) + 1,
                    )
                )
                seen.add(skill_id)
                if len(matches) >= max_skills:
                    break

        return matches

    def select_and_build(
        self,
        message: str,
        agent_id: str,
        max_skills: int = 3,
    ) -> str:
        """Classify intent, then build a prompt section for matched skills."""
        matches = self.classify_intent(message, max_skills=max_skills)
        if not matches:
            return ""

        skill_ids = [m.skill_id for m in matches]
        prompt = self._registry.build_prompt(skill_ids, agent_id)

        if prompt:
            logger.info(
                "skills.progressive agent=%s matched=%s",
                agent_id,
                [m.skill_id for m in matches],
            )

        return prompt

    def as_middleware(self, max_skills: int = 3) -> "_ProgressiveSkillMiddleware":
        """Return a Middleware instance that plugs into MiddlewareChain."""
        return _ProgressiveSkillMiddleware(self, max_skills)


# ---------------------------------------------------------------------------
# Middleware adapter
# ---------------------------------------------------------------------------

class _ProgressiveSkillMiddleware(Middleware):
    """Injects relevant skill context into the system prompt before LLM calls."""

    name = "progressive_skills"
    priority = 45  # after summarization, before LLM call

    def __init__(
        self, loader: ProgressiveSkillLoader, max_skills: int
    ) -> None:
        self._loader = loader
        self._max_skills = max_skills

    async def before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        # Find the last user message to classify intent
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        if not last_user:
            return messages

        skill_section = self._loader.select_and_build(
            message=last_user,
            agent_id=meta.agent_id,
            max_skills=self._max_skills,
        )

        if not skill_section:
            return messages

        # Append skill context to the system message
        for m in messages:
            if m.get("role") == "system":
                m["content"] = m["content"] + "\n\n" + skill_section
                break
        else:
            # No system message — prepend one
            messages.insert(
                0, {"role": "system", "content": skill_section}
            )

        return messages
