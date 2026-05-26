"""
Week 2 sprint B2 + B4 — retry, circuit breaker, and cold-start UX.

These tests exercise ``BackendHttpClient`` deterministically (mock httpx
client + injected sleep + fake monotonic clock) and verify the Discord
``_handle_chat`` integration goes silent during an open breaker and emits
the warming indicator only after the configured cold-start delay.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.discord.backend_client import (
    BackendHttpClient,
    CircuitBreakerOpen,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic monotonic clock the tests can advance manually."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _ok_response(status: int = 200) -> Any:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    return resp


def _make_client(
    request_side_effect: Any,
    *,
    clock: FakeClock | None = None,
) -> tuple[BackendHttpClient, MagicMock, FakeClock, AsyncMock]:
    fake_httpx = MagicMock()
    fake_httpx.request = AsyncMock(side_effect=request_side_effect)
    fake_sleep = AsyncMock()
    clock = clock or FakeClock()
    bc = BackendHttpClient(
        "http://test",
        client=fake_httpx,
        sleep=fake_sleep,
        clock=clock,
    )
    return bc, fake_httpx, clock, fake_sleep


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_three_times_on_connect_error_then_succeeds() -> None:
    calls = [
        httpx.ConnectError("nope"),
        httpx.ConnectError("nope"),
        _ok_response(200),
    ]
    bc, fake_httpx, _, fake_sleep = _make_client(calls)

    resp = await bc.post_tracked("/chat", json={"x": 1})

    assert resp.status_code == 200
    assert fake_httpx.request.await_count == 3
    # Two retries → two backoff sleeps with the documented delays.
    assert [c.args[0] for c in fake_sleep.await_args_list] == [0.05, 0.2]
    assert bc.consecutive_failures == 0


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds() -> None:
    calls = [_ok_response(503), _ok_response(502), _ok_response(200)]
    bc, fake_httpx, _, _ = _make_client(calls)

    resp = await bc.post_tracked("/chat", json={})

    assert resp.status_code == 200
    assert fake_httpx.request.await_count == 3


@pytest.mark.asyncio
async def test_gives_up_after_four_attempts_and_raises_last_exception() -> None:
    err = httpx.ConnectError("backend down")
    bc, fake_httpx, _, fake_sleep = _make_client([err] * 10)

    with pytest.raises(httpx.ConnectError):
        await bc.post_tracked("/chat", json={})

    # 4 attempts = initial + 3 retries (50/200/800ms).
    assert fake_httpx.request.await_count == 4
    assert [c.args[0] for c in fake_sleep.await_args_list] == [0.05, 0.2, 0.8]
    assert bc.consecutive_failures == 1


@pytest.mark.asyncio
async def test_4xx_is_not_retried() -> None:
    bc, fake_httpx, _, _ = _make_client([_ok_response(404)])
    resp = await bc.post_tracked("/chat", json={})
    assert resp.status_code == 404
    assert fake_httpx.request.await_count == 1


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_opens_after_five_consecutive_failures() -> None:
    clock = FakeClock()
    err = httpx.ConnectError("dead")
    # Each tracked call exhausts 4 attempts → re-raises → counts as 1 failure.
    bc, _, _, _ = _make_client([err] * 100, clock=clock)

    for _ in range(BackendHttpClient.FAILURE_THRESHOLD):
        with pytest.raises(httpx.ConnectError):
            await bc.post_tracked("/chat", json={})

    assert bc.is_open() is True
    # One-shot notice fires exactly once.
    assert bc.consume_breaker_notice() is True
    assert bc.consume_breaker_notice() is False


@pytest.mark.asyncio
async def test_breaker_blocks_calls_while_open() -> None:
    clock = FakeClock()
    err = httpx.ConnectError("dead")
    bc, fake_httpx, _, _ = _make_client([err] * 100, clock=clock)

    for _ in range(BackendHttpClient.FAILURE_THRESHOLD):
        with pytest.raises(httpx.ConnectError):
            await bc.post_tracked("/chat", json={})
    call_count_at_open = fake_httpx.request.await_count

    with pytest.raises(CircuitBreakerOpen):
        await bc.post_tracked("/chat", json={})

    # No new HTTP attempts while breaker is open.
    assert fake_httpx.request.await_count == call_count_at_open


@pytest.mark.asyncio
async def test_breaker_allows_probe_after_open_window_and_closes_on_success() -> None:
    clock = FakeClock()
    # 5 failures, then one success on probe.
    err = httpx.ConnectError("dead")
    calls: list[Any] = [err] * (4 * BackendHttpClient.FAILURE_THRESHOLD) + [_ok_response(200)]
    bc, _, _, _ = _make_client(calls, clock=clock)

    for _ in range(BackendHttpClient.FAILURE_THRESHOLD):
        with pytest.raises(httpx.ConnectError):
            await bc.post_tracked("/chat", json={})

    assert bc.is_open() is True
    clock.advance(BackendHttpClient.OPEN_DURATION + 0.1)
    # is_open() should return False once the open window has elapsed.
    assert bc.is_open() is False

    resp = await bc.post_tracked("/chat", json={})
    assert resp.status_code == 200
    # Success resets the breaker state fully.
    assert bc.consecutive_failures == 0
    assert bc.is_open() is False


@pytest.mark.asyncio
async def test_failures_outside_window_reset_counter() -> None:
    clock = FakeClock()
    err = httpx.ConnectError("flap")
    bc, _, _, _ = _make_client([err] * 100, clock=clock)

    with pytest.raises(httpx.ConnectError):
        await bc.post_tracked("/chat", json={})
    assert bc.consecutive_failures == 1

    # Advance past the 30s failure window.
    clock.advance(BackendHttpClient.FAILURE_WINDOW + 1.0)
    with pytest.raises(httpx.ConnectError):
        await bc.post_tracked("/chat", json={})

    # New failure should restart the counter at 1, not bump to 2.
    assert bc.consecutive_failures == 1
    assert bc.is_open() is False


# ---------------------------------------------------------------------------
# Bot integration — breaker silences error spam, warmup indicator fires
# ---------------------------------------------------------------------------


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

    async def _reply(content: str) -> Any:
        sent.append(content)
        warmup = MagicMock()
        warmup.edit = AsyncMock()
        warmup.delete = AsyncMock()
        return warmup

    msg.reply = AsyncMock(side_effect=_reply)

    class _TypingCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    msg.channel.typing = MagicMock(return_value=_TypingCtx())
    msg._sent = sent
    return msg


@pytest.mark.asyncio
async def test_handle_chat_stays_silent_while_breaker_open() -> None:
    from backend.discord.backend_client import BackendHttpClient
    from backend.discord_bot import AgentopBot

    bot = AgentopBot.__new__(AgentopBot)
    bot._http_client = MagicMock()
    bot._conversation_agents = {}
    bot._WARMUP_DELAY_SECONDS = 9999.0
    fake_client = MagicMock()
    fake_client.request = AsyncMock(side_effect=httpx.ConnectError("dead"))
    bot._backend = BackendHttpClient("http://test", client=fake_client, sleep=AsyncMock())

    # Force breaker open by running 5 failing tracked calls.
    for _ in range(BackendHttpClient.FAILURE_THRESHOLD):
        with pytest.raises(httpx.ConnectError):
            await bot._backend.post_tracked("/chat", json={})
    assert bot._backend.is_open()

    msg1 = _make_message("hi")
    await bot._handle_chat(msg1, "hi", agent_id="auto")
    # First open-window reply: ONE notice message.
    assert len(msg1._sent) == 1
    assert "operator notified" in msg1._sent[0]

    msg2 = _make_message("still nope")
    await bot._handle_chat(msg2, "still nope", agent_id="auto")
    # Subsequent calls while open: completely silent.
    assert msg2._sent == []


@pytest.mark.asyncio
async def test_handle_chat_warmup_message_is_edited_with_final_answer() -> None:
    """Verifies the warmup placeholder is replaced with the final response."""
    from backend.discord.backend_client import BackendHttpClient
    from backend.discord_bot import AgentopBot

    bot = AgentopBot.__new__(AgentopBot)
    bot._http_client = MagicMock()
    bot._conversation_agents = {}
    bot._WARMUP_DELAY_SECONDS = 0.01

    warmup_holder: dict[str, Any] = {}

    async def _slow_request(method: str, url: str, json: dict[str, Any]) -> Any:
        await asyncio.sleep(0.05)
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {
            "agent_id": "knowledge_agent",
            "message": "warm answer",
            "drift_status": "GREEN",
            "citations": [],
            "proposed_action": None,
        }
        return resp

    fake_client = MagicMock()
    fake_client.request = AsyncMock(side_effect=_slow_request)
    bot._backend = BackendHttpClient("http://test", client=fake_client, sleep=AsyncMock())

    msg = MagicMock()
    msg.author = MagicMock()
    msg.author.__str__ = lambda self: "lex"
    msg.author.id = 1
    msg.channel = MagicMock()
    msg.channel.id = 1
    msg.channel.__str__ = lambda self: "c"
    msg.guild = MagicMock()
    msg.guild.name = "g"

    async def _reply(content: str) -> Any:
        warmup = MagicMock()
        warmup.content = content
        warmup.edit = AsyncMock()
        warmup.delete = AsyncMock()
        warmup_holder["msg"] = warmup
        return warmup

    msg.reply = AsyncMock(side_effect=_reply)

    class _TypingCtx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    msg.channel.typing = MagicMock(return_value=_TypingCtx())

    await bot._handle_chat(msg, "hi", agent_id="auto")

    assert "msg" in warmup_holder, "warmup reply must have been posted"
    warmup_holder["msg"].edit.assert_awaited_once()
    edited_content = warmup_holder["msg"].edit.await_args.kwargs.get("content", "")
    assert "warm answer" in edited_content
    assert "[knowledge_agent]" in edited_content


@pytest.mark.asyncio
async def test_handle_chat_no_warmup_when_response_is_fast() -> None:
    """B4: fast responses should not produce a warmup placeholder."""
    from backend.discord.backend_client import BackendHttpClient
    from backend.discord_bot import AgentopBot

    bot = AgentopBot.__new__(AgentopBot)
    bot._http_client = MagicMock()
    bot._conversation_agents = {}
    bot._WARMUP_DELAY_SECONDS = 10.0  # never fires within the fast call

    async def _fast_request(method: str, url: str, json: dict[str, Any]) -> Any:
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {
            "agent_id": "knowledge_agent",
            "message": "fast",
            "drift_status": "GREEN",
            "citations": [],
            "proposed_action": None,
        }
        return resp

    fake_client = MagicMock()
    fake_client.request = AsyncMock(side_effect=_fast_request)
    bot._backend = BackendHttpClient("http://test", client=fake_client, sleep=AsyncMock())

    msg = _make_message("hi")
    await bot._handle_chat(msg, "hi", agent_id="auto")

    # Exactly one reply — the final answer. No warmup placeholder.
    assert len(msg._sent) == 1
    assert "Warming up" not in msg._sent[0]
    assert "fast" in msg._sent[0]
