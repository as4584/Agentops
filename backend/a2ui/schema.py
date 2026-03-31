"""A2UI message schema — strict Pydantic v2 validation for agent-to-UI events.

Protocol v1
-----------
Agents emit :class:`A2UIMessage` objects that the frontend ``AgentCanvas``
component consumes via the WebSocket ``canvas`` channel.

``op`` semantics
~~~~~~~~~~~~~~~~
- ``render``  — draw a new widget (must not already exist at ``widget_id``).
- ``replace`` — replace an existing widget's props in-place.
- ``append``  — add a row/item to a list-type widget.
- ``clear``   — remove all widgets from ``target`` (``component`` optional).

Validation rules
~~~~~~~~~~~~~~~~
- ``component`` is required for ``render`` / ``replace`` / ``append``.
- ``component`` must be a known v1 component name.
- ``props`` must pass per-component validation.
- ``target`` must match ``canvas/<identifier>`` format.
- ``widget_id`` required for ``render`` / ``replace`` / ``append``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal  # noqa: F401 — Annotated used in field definitions

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Component catalogue (v1)
# ---------------------------------------------------------------------------

A2UIComponentType = Literal["status_card", "task_list", "kv_table"]

A2UIOp = Literal["render", "replace", "append", "clear"]

_OPS_REQUIRING_COMPONENT: frozenset[str] = frozenset({"render", "replace", "append"})

_TARGET_RE = re.compile(r"^canvas/[a-zA-Z0-9_\-]+$")


# ---------------------------------------------------------------------------
# Per-component prop schemas (Sprint 5.1 strict validation)
# ---------------------------------------------------------------------------


class StatusCardProps(BaseModel):
    """Props for the ``status_card`` widget."""

    title: str = Field(..., min_length=1, max_length=120)
    state: Literal["idle", "running", "success", "warning", "error", "info"]
    message: str | None = Field(default=None, max_length=500)
    progress: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


class TaskListProps(BaseModel):
    """Props for the ``task_list`` widget."""

    title: str = Field(..., min_length=1, max_length=120)
    tasks: Annotated[list[dict[str, Any]], Field(default_factory=list, max_length=100)]
    show_completed: bool = True

    model_config = {"extra": "forbid"}


class KVTableProps(BaseModel):
    """Props for the ``kv_table`` widget."""

    title: str = Field(..., min_length=1, max_length=120)
    rows: Annotated[list[dict[str, Any]], Field(default_factory=list, max_length=200)]
    striped: bool = True

    model_config = {"extra": "forbid"}


_COMPONENT_PROP_SCHEMAS: dict[str, type[BaseModel]] = {
    "status_card": StatusCardProps,
    "task_list": TaskListProps,
    "kv_table": KVTableProps,
}


def validate_component_props(component: str, props: dict[str, Any] | None) -> dict[str, Any]:
    """Validate *props* against the component's schema.

    Returns the validated (normalised) props dict.
    Raises :exc:`ValueError` for unknown components or invalid props.
    """
    schema_cls = _COMPONENT_PROP_SCHEMAS.get(component)
    if schema_cls is None:
        raise ValueError(f"Unknown A2UI component: {component!r}. Valid: {sorted(_COMPONENT_PROP_SCHEMAS)}")
    validated = schema_cls.model_validate(props or {})
    return validated.model_dump()


# ---------------------------------------------------------------------------
# A2UIMessage
# ---------------------------------------------------------------------------


class A2UIMessage(BaseModel):
    """Full A2UI event message emitted by an agent."""

    ui_event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    op: A2UIOp
    target: str
    widget_id: str | None = None
    component: A2UIComponentType | None = None
    props: dict[str, Any] | None = None
    seq: int = Field(default=0, ge=0)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    model_config = {"extra": "forbid"}

    @field_validator("target")
    @classmethod
    def _validate_target(cls, v: str) -> str:
        if not _TARGET_RE.match(v):
            raise ValueError(f"target must match 'canvas/<identifier>' (alphanumeric, - or _), got: {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_op_requirements(self) -> A2UIMessage:
        if self.op in _OPS_REQUIRING_COMPONENT:
            if not self.component:
                raise ValueError(f"op={self.op!r} requires 'component'")
            if not self.widget_id:
                raise ValueError(f"op={self.op!r} requires 'widget_id'")
            # Validate props against per-component schema
            self.props = validate_component_props(self.component, self.props)
        return self


# ---------------------------------------------------------------------------
# A2UIAction — widget interaction callback (Sprint 5.4)
# ---------------------------------------------------------------------------


class A2UIAction(BaseModel):
    """Widget interaction sent from the frontend to the backend."""

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    widget_id: str = Field(..., min_length=1)
    target: str
    action_type: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    agent_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    model_config = {"extra": "forbid"}

    @field_validator("target")
    @classmethod
    def _validate_target(cls, v: str) -> str:
        if not _TARGET_RE.match(v):
            raise ValueError(f"target must match 'canvas/<identifier>', got: {v!r}")
        return v
