"""
Structured response rendering for Discord (Week 2 sprint B1).

The Discord bot used to inject a brittle ``[DISCORD CONTEXT] ... [/DISCORD CONTEXT]``
text prefix into every user message. Small local models (qwen3:4b, lex-v2)
frequently *echoed* that prefix back, hallucinated agent names from the rules
list, or ignored the brevity instructions entirely.

This module replaces that prose-based contract with a typed one:

  1. The brevity rules now travel as ``ChatRequest.context['surface_rules']``
     — the agent can read them, the prompt cannot leak them.
  2. The backend's ``ChatResponse`` already carries structured fields
     (``message``, ``citations``, ``proposed_action``) — A4 wired the latter
     two through the orchestrator. We deserialize them into ``DiscordResponse``
     here and validate; if validation fails we degrade gracefully to a
     fallback that still renders something useful and marks itself with an
     ``⚠️ unstructured`` badge so operators know the safety rails were off.

Note on the sprint's "malformed Ollama JSON → retry once" language: the bot
talks to the FastAPI gateway, not to Ollama directly. The retry-equivalent
here is *salvage on partial validity, fallback on total invalidity*. The
underlying schema-coerced LLM call lives in ``OllamaClient.chat_with_schema``
and is exercised by agents that opt in (knowledge_agent today).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

# Hard ceiling for the rendered Discord reply. Discord allows 2000 chars; we
# leave headroom for the agent header and an optional badge.
_DISCORD_BODY_LIMIT = 1700

# Surface rules previously hard-coded into the [DISCORD CONTEXT] prefix. They
# now travel as structured context so the agent can read them and the prompt
# cannot leak them back to the user.
DISCORD_SURFACE_RULES: dict[str, Any] = {
    "surface": "discord",
    "max_chars": 500,
    "format": "plain",
    "forbid": ["hallucinated_tools", "hallucinated_agent_names"],
    "tone": "direct, helpful, no preamble",
}


class DiscordResponse(BaseModel):
    """Validated payload the Discord renderer consumes.

    Built from a backend ``/chat`` response dict via ``parse_backend_response``.
    On validation failure the caller receives a fallback instance with
    ``warnings=['unstructured']`` instead of an exception — the bot must
    never crash on a malformed agent response.
    """

    agent_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    drift_status: str = "GREEN"
    citations: list[str] = Field(default_factory=list)
    proposed_action: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_fallback(self) -> bool:
        return "unstructured" in self.warnings


def parse_backend_response(data: Any, *, fallback_agent: str = "auto") -> DiscordResponse:
    """Validate the backend's ``/chat`` JSON into a ``DiscordResponse``.

    Salvage rules (in priority order):
      - If ``data`` is a dict with a usable ``message``/``answer`` field,
        build a strict ``DiscordResponse``.
      - On Pydantic validation failure, retry once after coercing the obvious
        renames (``message`` → ``answer``) and dropping malformed sub-fields.
      - On total failure, return a fallback whose answer is the best string
        we can extract and whose ``warnings`` contain ``"unstructured"``.
    """
    if not isinstance(data, dict):
        return _fallback(str(data)[:_DISCORD_BODY_LIMIT], agent=fallback_agent)

    # First attempt: strict.
    try:
        return DiscordResponse(
            agent_id=str(data.get("agent_id") or fallback_agent),
            answer=str(data.get("message") or data.get("answer") or "").strip(),
            drift_status=str(data.get("drift_status") or "GREEN"),
            citations=_coerce_str_list(data.get("citations")),
            proposed_action=_coerce_action(data.get("proposed_action")),
        )
    except ValidationError:
        pass

    # Second attempt: salvage with explicit coercion + sub-field drops.
    try:
        return DiscordResponse(
            agent_id=str(data.get("agent_id") or fallback_agent) or fallback_agent,
            answer=_first_nonempty_string(data) or "(empty response)",
            drift_status=str(data.get("drift_status") or "GREEN"),
            citations=[],
            proposed_action=None,
            warnings=["unstructured"],
        )
    except ValidationError:
        return _fallback("(unparseable response)", agent=fallback_agent)


def render_for_discord(resp: DiscordResponse) -> str:
    """Render a ``DiscordResponse`` into the final string posted to Discord."""
    header = f"**[{resp.agent_id}]**"
    if resp.drift_status and resp.drift_status != "GREEN":
        header += f" ⚠️ Drift: {resp.drift_status}"
    if resp.is_fallback:
        header += " ⚠️ unstructured"

    body = resp.answer.strip()
    if len(body) > _DISCORD_BODY_LIMIT:
        body = body[:_DISCORD_BODY_LIMIT] + "\n\n*...truncated for Discord*"

    lines = [header, body]

    if resp.citations:
        cited = ", ".join(f"`{c}`" for c in resp.citations[:5])
        lines.append(f"📎 Sources: {cited}")

    action = resp.proposed_action
    if isinstance(action, dict) and action.get("id") and action.get("action_type"):
        params = action.get("parameters") or {}
        target = params.get("process_name") or params.get("target") or "?"
        action_id = action["id"]
        lines.append(
            f"🛡 Pending action `{action_id}` — `{action['action_type']}` on `{target}`.\n"
            f"   `!approve {action_id}` to run · `!reject {action_id} <reason>` to discard."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _fallback(answer: str, *, agent: str) -> DiscordResponse:
    return DiscordResponse(
        agent_id=agent or "auto",
        answer=answer or "(empty response)",
        warnings=["unstructured"],
    )


def _coerce_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    return []


def _coerce_action(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if not value.get("id") or not value.get("action_type"):
        return None
    return value


def _first_nonempty_string(data: dict[str, Any]) -> str:
    for key in ("message", "answer", "response", "detail", "error"):
        candidate = data.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""
