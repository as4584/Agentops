"""WebSocket protocol models for the Agentop control plane."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SubscribeMessage(BaseModel):
    """Client → Server: subscribe to one or more channels."""

    type: Literal["subscribe"]
    channels: list[str] = Field(default_factory=list)
    session_id: str | None = None


class PongMessage(BaseModel):
    """Client → Server: response to a server ping."""

    type: Literal["pong"]


class WelcomeMessage(BaseModel):
    """Server → Client: sent immediately after connection is accepted."""

    type: Literal["connected"] = "connected"
    client_id: str
    channels: list[str] = Field(default_factory=list)


class PingMessage(BaseModel):
    """Server → Client: heartbeat ping every 20s."""

    type: Literal["ping"] = "ping"


class ErrorMessage(BaseModel):
    """Server → Client: error notification."""

    type: Literal["error"] = "error"
    detail: str


class OutboundEvent(BaseModel):
    """Server → Client: a channel event."""

    type: Literal["event"] = "event"
    channel: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


# All channels the server recognises
VALID_CHANNELS: frozenset[str] = frozenset({"tasks", "agents", "logs", "canvas", "*"})
