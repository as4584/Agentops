"""
Week 2 sprint B1 — Discord bot must use structured outputs, never echo a
prompt prefix, and degrade gracefully when an agent returns a malformed
payload.

These tests cover both the pure renderer (DiscordResponse + render_for_discord)
and the bot's _handle_chat integration with a mocked httpx client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.structured_response import (
    DISCORD_SURFACE_RULES,
    DiscordResponse,
    parse_backend_response,
    render_for_discord,
)

# ---------------------------------------------------------------------------
# Pure parser / renderer
# ---------------------------------------------------------------------------


def test_parses_well_formed_backend_response() -> None:
    resp = parse_backend_response(
        {
            "agent_id": "knowledge_agent",
            "message": "Backend logs show 502 from upstream.",
            "drift_status": "GREEN",
            "citations": ["docs/SOURCE_OF_TRUTH.md", "backend/server.py"],
            "proposed_action": None,
        }
    )
    assert isinstance(resp, DiscordResponse)
    assert resp.agent_id == "knowledge_agent"
    assert resp.answer.startswith("Backend logs")
    assert resp.citations == ["docs/SOURCE_OF_TRUTH.md", "backend/server.py"]
    assert resp.proposed_action is None
    assert not resp.is_fallback


def test_falls_back_when_message_is_missing() -> None:
    resp = parse_backend_response({"agent_id": "knowledge_agent", "drift_status": "GREEN"})
    assert resp.is_fallback
    assert "unstructured" in resp.warnings
    # Renderer must not raise on the fallback
    rendered = render_for_discord(resp)
    assert "⚠️ unstructured" in rendered


def test_falls_back_when_payload_is_not_a_dict() -> None:
    resp = parse_backend_response("totally broken")
    assert resp.is_fallback
    assert "totally broken" in resp.answer


def test_render_includes_drift_warning_and_citations() -> None:
    resp = DiscordResponse(
        agent_id="security_agent",
        answer="Found a hard-coded API key in config.py.",
        drift_status="YELLOW",
        citations=["backend/config.py"],
    )
    text = render_for_discord(resp)
    assert "[security_agent]" in text
    assert "Drift: YELLOW" in text
    assert "📎 Sources:" in text
    assert "`backend/config.py`" in text


def test_render_includes_approval_hint_when_action_present() -> None:
    resp = DiscordResponse(
        agent_id="knowledge_agent",
        answer="nginx looks unreachable on :80.",
        proposed_action={
            "id": "act_abc123def456",
            "action_type": "process_restart",
            "parameters": {"process_name": "nginx"},
        },
    )
    text = render_for_discord(resp)
    assert "🛡 Pending action `act_abc123def456`" in text
    assert "`!approve act_abc123def456`" in text
    assert "`!reject act_abc123def456 <reason>`" in text


def test_malformed_action_is_dropped_silently() -> None:
    # Missing id / action_type → drop the field, don't render it
    resp = parse_backend_response(
        {
            "agent_id": "knowledge_agent",
            "message": "ok",
            "proposed_action": {"action_type": "process_restart"},
        }
    )
    assert resp.proposed_action is None
    text = render_for_discord(resp)
    assert "Pending action" not in text


def test_surface_rules_are_structured_not_prose() -> None:
    # The Discord bot must NOT use a text prefix anymore — surface rules
    # travel as structured context. This sanity-checks the contract shape.
    assert DISCORD_SURFACE_RULES["surface"] == "discord"
    assert "max_chars" in DISCORD_SURFACE_RULES
    assert "forbid" in DISCORD_SURFACE_RULES


# ---------------------------------------------------------------------------
# Bot integration — _handle_chat
# ---------------------------------------------------------------------------


def _make_bot() -> Any:
    """Build an AgentopBot instance without invoking discord.py setup."""
    from backend.discord_bot import AgentopBot

    bot = AgentopBot.__new__(AgentopBot)
    bot._http_client = MagicMock()
    bot._conversation_agents = {}
    return bot


def _make_message(text: str = "hi") -> Any:
    msg = MagicMock()
    msg.author = MagicMock()
    msg.author.__str__ = lambda self: "lex"
    msg.author.id = 1234
    msg.channel = MagicMock()
    msg.channel.id = 9999
    msg.channel.__str__ = lambda self: "ops"
    msg.guild = MagicMock()
    msg.guild.name = "agentop"
    msg.content = text

    sent: list[str] = []

    async def _reply(content: str) -> None:
        sent.append(content)

    async def _send(content: str) -> None:
        sent.append(content)

    msg.reply = AsyncMock(side_effect=_reply)
    msg.channel.send = AsyncMock(side_effect=_send)

    # ``async with message.channel.typing()`` — return a no-op async ctx mgr
    class _TypingCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    msg.channel.typing = MagicMock(return_value=_TypingCtx())
    msg._sent = sent
    return msg


@pytest.mark.asyncio
async def test_handle_chat_does_not_inject_discord_context_prefix() -> None:
    bot = _make_bot()
    msg = _make_message("is nginx down?")

    captured: dict[str, Any] = {}

    async def _fake_post(url: str, json: dict[str, Any]) -> Any:
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {
            "agent_id": "knowledge_agent",
            "message": "Health endpoint returns 200.",
            "drift_status": "GREEN",
            "citations": [],
            "proposed_action": None,
        }
        return resp

    bot._http_client.post = AsyncMock(side_effect=_fake_post)
    await bot._handle_chat(msg, "is nginx down?", agent_id="auto")

    assert "[DISCORD CONTEXT]" not in captured["json"]["message"]
    assert captured["json"]["message"] == "is nginx down?"
    assert captured["json"]["context"]["surface_rules"]["surface"] == "discord"


@pytest.mark.asyncio
async def test_handle_chat_renders_unstructured_badge_on_malformed_payload() -> None:
    bot = _make_bot()
    msg = _make_message("anything")

    async def _fake_post(url: str, json: dict[str, Any]) -> Any:
        resp = MagicMock()
        resp.status_code = 200
        # Missing required 'message' field → must trigger fallback path
        resp.json = lambda: {"agent_id": "knowledge_agent"}
        return resp

    bot._http_client.post = AsyncMock(side_effect=_fake_post)
    await bot._handle_chat(msg, "anything", agent_id="auto")

    assert msg._sent, "bot must reply even on malformed payload"
    assert "⚠️ unstructured" in msg._sent[0]


@pytest.mark.asyncio
async def test_handle_chat_renders_approval_hint_when_action_proposed() -> None:
    bot = _make_bot()
    msg = _make_message("nginx is down, restart it")

    async def _fake_post(url: str, json: dict[str, Any]) -> Any:
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {
            "agent_id": "knowledge_agent",
            "message": "Proposing a restart for review.",
            "drift_status": "GREEN",
            "citations": [],
            "proposed_action": {
                "id": "act_999aaabbbccc",
                "action_type": "process_restart",
                "parameters": {"process_name": "nginx"},
            },
        }
        return resp

    bot._http_client.post = AsyncMock(side_effect=_fake_post)
    await bot._handle_chat(msg, "nginx is down, restart it", agent_id="auto")

    out = "\n".join(msg._sent)
    assert "Pending action `act_999aaabbbccc`" in out
    assert "!approve act_999aaabbbccc" in out
