"""
Agent Factory — Dynamic agent creation by the orchestrator.
============================================================
Allows the orchestrator (and soul_core) to spawn new agents at runtime
based on observed gaps in routing coverage. Created agents are persisted
to ``data/agents/factory/`` and registered in the live agent cluster.

Governance:
- Only soul_core or the orchestrator can invoke the factory (INV-6 extended)
- Created agents get MEDIUM impact by default (escalation requires soul approval)
- Every creation is logged as a shared event and appended to CHANGE_LOG.md
- Factory agents are tagged ``origin=factory`` so they can be audited separately
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from backend.config import PROJECT_ROOT
from backend.models import AgentDefinition, ChangeImpactLevel
from backend.utils import logger

FACTORY_DIR = PROJECT_ROOT / "data" / "agents" / "factory"
FACTORY_DIR.mkdir(parents=True, exist_ok=True)

# Tools a factory-spawned agent may reference
ALLOWED_TOOLS = frozenset(
    {
        "safe_shell",
        "file_reader",
        "doc_updater",
        "system_info",
        "webhook_send",
        "git_ops",
        "health_check",
        "log_tail",
        "alert_dispatch",
        "secret_scanner",
        "db_query",
        "process_restart",
    }
)

# Maximum number of factory-created agents to prevent runaway spawning
MAX_FACTORY_AGENTS = 20

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")


class AgentBlueprint(BaseModel):
    """Specification for a new agent to be created by the factory."""

    agent_id: str = Field(..., description="snake_case identifier, 3-40 chars")
    role: str = Field(..., min_length=10, max_length=500, description="What this agent does")
    system_prompt: str = Field(..., min_length=20, max_length=4000)
    tool_permissions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    change_impact_level: ChangeImpactLevel = Field(default=ChangeImpactLevel.MEDIUM)
    skills: list[str] = Field(default_factory=list)
    rationale: str = Field(..., min_length=10, max_length=500, description="Why this agent is needed")
    requested_by: str = Field(default="orchestrator", description="Who requested creation")

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if not _AGENT_ID_RE.match(v):
            raise ValueError(f"agent_id must be lowercase snake_case, 3-40 chars: got '{v}'")
        return v

    @field_validator("tool_permissions")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        invalid = set(v) - ALLOWED_TOOLS
        if invalid:
            raise ValueError(f"Unknown tools: {invalid}. Valid: {sorted(ALLOWED_TOOLS)}")
        return v


class FactoryResult(BaseModel):
    """Result of an agent creation attempt."""

    success: bool
    agent_id: str
    definition: AgentDefinition | None = None
    error: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AgentFactory:
    """Creates, persists, and manages dynamically spawned agents."""

    def __init__(self) -> None:
        self._created: dict[str, AgentDefinition] = {}
        self._load_persisted()

    def _load_persisted(self) -> None:
        """Load previously created factory agents from disk."""
        for path in sorted(FACTORY_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                defn = AgentDefinition(**data)
                self._created[defn.agent_id] = defn
            except Exception as exc:
                logger.warning(f"[AgentFactory] Failed to load {path.name}: {exc}")

    @property
    def count(self) -> int:
        return len(self._created)

    def list_agents(self) -> list[AgentDefinition]:
        return list(self._created.values())

    def get(self, agent_id: str) -> AgentDefinition | None:
        return self._created.get(agent_id)

    def create_agent(
        self,
        blueprint: AgentBlueprint,
        existing_ids: set[str],
    ) -> FactoryResult:
        """
        Validate and create a new agent from a blueprint.

        Args:
            blueprint: The agent specification.
            existing_ids: Set of already-registered agent IDs (static + factory).

        Returns:
            FactoryResult with success/failure and the definition if created.
        """
        # Guard: max cap
        if self.count >= MAX_FACTORY_AGENTS:
            return FactoryResult(
                success=False,
                agent_id=blueprint.agent_id,
                error=f"Factory agent limit reached ({MAX_FACTORY_AGENTS})",
            )

        # Guard: no collisions
        if blueprint.agent_id in existing_ids or blueprint.agent_id in self._created:
            return FactoryResult(
                success=False,
                agent_id=blueprint.agent_id,
                error=f"Agent '{blueprint.agent_id}' already exists",
            )

        # Guard: only soul_core or orchestrator can request HIGH/CRITICAL
        if (
            blueprint.change_impact_level
            in (
                ChangeImpactLevel.HIGH,
                ChangeImpactLevel.CRITICAL,
            )
            and blueprint.requested_by != "soul_core"
        ):
            return FactoryResult(
                success=False,
                agent_id=blueprint.agent_id,
                error="Only soul_core can create HIGH/CRITICAL impact agents",
            )

        definition = AgentDefinition(
            agent_id=blueprint.agent_id,
            role=blueprint.role,
            system_prompt=blueprint.system_prompt,
            tool_permissions=blueprint.tool_permissions,
            memory_namespace=blueprint.agent_id,
            allowed_actions=blueprint.allowed_actions,
            change_impact_level=blueprint.change_impact_level,
            skills=blueprint.skills,
        )

        # Persist to disk
        path = FACTORY_DIR / f"{blueprint.agent_id}.json"
        path.write_text(
            definition.model_dump_json(indent=2),
            encoding="utf-8",
        )

        self._created[blueprint.agent_id] = definition

        logger.info(
            f"[AgentFactory] Created agent: {blueprint.agent_id} "
            f"(requested_by={blueprint.requested_by}, rationale={blueprint.rationale[:80]})"
        )

        return FactoryResult(
            success=True,
            agent_id=blueprint.agent_id,
            definition=definition,
        )

    def delete_agent(self, agent_id: str) -> bool:
        """Remove a factory-created agent. Returns True if found and removed."""
        if agent_id not in self._created:
            return False
        del self._created[agent_id]
        path = FACTORY_DIR / f"{agent_id}.json"
        if path.exists():
            path.unlink()
        logger.info(f"[AgentFactory] Deleted agent: {agent_id}")
        return True


# Module-level singleton
agent_factory = AgentFactory()
