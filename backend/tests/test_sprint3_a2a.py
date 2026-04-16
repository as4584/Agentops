"""
Sprint 3 Acceptance Tests — Durable A2A Execution
==================================================
Validates that agent-to-agent messaging produces real execution results
(not just envelope storage) and that all safety invariants hold.

PR coverage:
  PR1  A2ADispatchResult model contract
  PR2  Orchestrator.dispatch_a2a_message() actually calls process_message
  PR3  Depth limits and thread safety
  PR4  Inbox retrieval and ack persistence in shared_events
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_orchestrator() -> Any:
    """Build a minimal orchestrator with mocked LLM and agents."""

    from backend.orchestrator import AgentOrchestrator

    mock_llm = MagicMock()
    mock_llm.is_available = AsyncMock(return_value=False)
    mock_llm.generate = AsyncMock(return_value="mock response")

    # Patch heavy init to avoid Ollama/DB side-effects
    with (
        patch("backend.orchestrator.AgentOrchestrator._initialize_agents"),
        patch("backend.orchestrator.AgentOrchestrator._build_graph") as mock_build,
        patch("backend.orchestrator.AgentOrchestrator._compiled_graph", create=True),
        patch("backend.knowledge.KnowledgeVectorStore.__init__", return_value=None),
    ):
        mock_build.return_value = MagicMock()
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch.llm_client = mock_llm
        orch._agents = {
            "devops_agent": MagicMock(),
            "monitor_agent": MagicMock(),
            "security_agent": MagicMock(),
            "knowledge_agent": MagicMock(),
        }
        orch._gatekeeper = MagicMock()
        orch._knowledge_store = MagicMock()
        orch._knowledge_agent_id = "knowledge_agent"
        orch._factory = MagicMock()
        orch._factory.list_agents.return_value = []
        orch._graph = MagicMock()
        orch._compiled_graph = MagicMock()

    return orch


# ---------------------------------------------------------------------------
# PR1 — A2ADispatchResult Model Contract
# ---------------------------------------------------------------------------


class TestA2ADispatchResultModel:
    def test_model_fields_present(self) -> None:
        from backend.models import A2ADispatchResult

        r = A2ADispatchResult(
            message_id="msg_001",
            thread_id="thread_001",
            from_agent="devops_agent",
            to_agent="monitor_agent",
            response="done",
            acked=True,
            ack_at="2026-04-16T00:00:00+00:00",
            duration_ms=12.5,
        )
        assert r.message_id == "msg_001"
        assert r.acked is True
        assert r.error is None

    def test_failed_dispatch_result(self) -> None:
        from backend.models import A2ADispatchResult

        r = A2ADispatchResult(
            message_id="msg_002",
            thread_id="thread_002",
            from_agent="devops_agent",
            to_agent="monitor_agent",
            acked=False,
            ack_at=None,
            error="execution timeout",
            duration_ms=5000.0,
        )
        assert r.acked is False
        assert r.error == "execution timeout"
        assert r.ack_at is None
        assert r.response == ""

    def test_retry_count_default_zero(self) -> None:
        from backend.models import A2ADispatchResult

        r = A2ADispatchResult(
            message_id="m",
            thread_id="t",
            from_agent="a",
            to_agent="b",
        )
        assert r.retry_count == 0

    def test_retry_count_non_negative(self) -> None:
        from pydantic import ValidationError

        from backend.models import A2ADispatchResult

        with pytest.raises(ValidationError):
            A2ADispatchResult(
                message_id="m",
                thread_id="t",
                from_agent="a",
                to_agent="b",
                retry_count=-1,
            )

    def test_duration_ms_non_negative(self) -> None:
        from pydantic import ValidationError

        from backend.models import A2ADispatchResult

        with pytest.raises(ValidationError):
            A2ADispatchResult(
                message_id="m",
                thread_id="t",
                from_agent="a",
                to_agent="b",
                duration_ms=-1.0,
            )

    def test_model_round_trips_json(self) -> None:
        from backend.models import A2ADispatchResult

        r = A2ADispatchResult(
            message_id="m",
            thread_id="t",
            from_agent="devops_agent",
            to_agent="monitor_agent",
            response="ok",
            acked=True,
            ack_at="2026-04-16T00:00:00+00:00",
            duration_ms=10.0,
        )
        data = r.model_dump(mode="json")
        r2 = A2ADispatchResult(**data)
        assert r2.acked == r.acked
        assert r2.response == r.response


# ---------------------------------------------------------------------------
# PR2 — dispatch_a2a_message calls process_message
# ---------------------------------------------------------------------------


class TestDispatchA2AExecution:
    def test_dispatch_calls_process_message(self) -> None:
        """dispatch_a2a_message must invoke process_message on the target agent."""
        orch = _make_orchestrator()

        async def _run() -> None:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_exec_001",
                        "thread_id": "thread_exec_001",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    return_value={"response": "health ok", "error": None},
                ) as mock_pm,
            ):
                result = await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="check health",
                    payload={"message": "are you alive?"},
                )
                mock_pm.assert_awaited_once()
                assert result.acked is True
                assert result.response == "health ok"

        asyncio.run(_run())

    def test_dispatch_result_has_ack_at_on_success(self) -> None:
        orch = _make_orchestrator()

        async def _run() -> None:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_ack_001",
                        "thread_id": "thread_ack_001",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    return_value={"response": "pong", "error": None},
                ),
            ):
                result = await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="ping",
                    payload={"message": "ping"},
                )
            assert result.ack_at is not None
            assert "2026" in result.ack_at or "T" in result.ack_at

        asyncio.run(_run())

    def test_dispatch_duration_ms_positive(self) -> None:
        orch = _make_orchestrator()

        async def _run() -> Any:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_dur_001",
                        "thread_id": "thread_dur_001",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    return_value={"response": "ok"},
                ),
            ):
                return await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="test",
                    payload={"message": "hello"},
                )

        result = asyncio.run(_run())
        assert result.duration_ms >= 0.0

    def test_dispatch_ack_event_persisted_on_success(self) -> None:
        """A2A_ACK event must appear in shared_events after dispatch."""
        from backend.memory import memory_store

        orch = _make_orchestrator()
        mid = f"msg_ack_persist_{uuid.uuid4().hex[:8]}"

        async def _run() -> None:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": mid,
                        "thread_id": "thread_ack_persist",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    return_value={"response": "persisted ok"},
                ),
            ):
                await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="persist test",
                    payload={"message": "test"},
                )

        asyncio.run(_run())

        events = memory_store.get_shared_events(limit=200)
        ack_events = [
            e for e in events if isinstance(e, dict) and e.get("type") == "A2A_ACK" and e.get("message_id") == mid
        ]
        assert len(ack_events) == 1
        assert ack_events[0]["acked"] is True

    def test_dispatch_failure_sets_acked_false(self) -> None:
        """When process_message raises, acked must be False with error set."""
        orch = _make_orchestrator()

        async def _run() -> Any:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_fail_001",
                        "thread_id": "thread_fail_001",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("agent exploded"),
                ),
            ):
                return await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="will fail",
                    payload={"message": "trigger error"},
                )

        result = asyncio.run(_run())
        assert result.acked is False
        assert result.error is not None
        assert "agent exploded" in result.error

    def test_dispatch_failure_ack_event_persisted_with_error(self) -> None:
        """Failed dispatch still persists A2A_ACK event with acked=False."""
        from backend.memory import memory_store

        orch = _make_orchestrator()
        mid = f"msg_fail_persist_{uuid.uuid4().hex[:8]}"

        async def _run() -> None:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": mid,
                        "thread_id": "thread_fail_persist",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("boom"),
                ),
            ):
                await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="fail persist",
                    payload={"message": "fail"},
                )

        asyncio.run(_run())

        events = memory_store.get_shared_events(limit=200)
        ack_events = [
            e for e in events if isinstance(e, dict) and e.get("type") == "A2A_ACK" and e.get("message_id") == mid
        ]
        assert len(ack_events) == 1
        assert ack_events[0]["acked"] is False
        assert ack_events[0]["error"] is not None

    def test_dispatch_passes_a2a_context_to_process_message(self) -> None:
        """process_message must receive a2a=True and from_agent in context."""
        orch = _make_orchestrator()
        captured_context: dict[str, Any] = {}

        async def _mock_pm(agent_id: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
            captured_context.update(context or {})
            return {"response": "ok"}

        async def _run() -> None:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_ctx_001",
                        "thread_id": "thread_ctx_001",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(orch, "process_message", side_effect=_mock_pm),
            ):
                await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="context test",
                    payload={"message": "hello"},
                    depth=1,
                    thread_id="thread_ctx_001",
                )

        asyncio.run(_run())
        assert captured_context.get("a2a") is True
        assert captured_context.get("from_agent") == "devops_agent"
        assert captured_context.get("depth") == 1


# ---------------------------------------------------------------------------
# PR3 — Depth Limits and Send Validation
# ---------------------------------------------------------------------------


class TestA2ADepthLimits:
    def test_depth_exceeded_raises_value_error(self) -> None:
        from backend.config import A2A_MAX_DEPTH

        orch = _make_orchestrator()

        with pytest.raises(ValueError, match="A2A depth exceeded"):
            orch.send_agent_message(
                from_agent="devops_agent",
                to_agent="monitor_agent",
                purpose="overflow",
                payload={},
                depth=A2A_MAX_DEPTH + 1,
            )

    def test_depth_at_max_is_allowed(self) -> None:
        from backend.config import A2A_MAX_DEPTH

        orch = _make_orchestrator()

        # Should not raise
        result = orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="at max depth",
            payload={"message": "ok"},
            depth=A2A_MAX_DEPTH,
            message_id=f"msg_maxdepth_{uuid.uuid4().hex[:8]}",
        )
        assert result["depth"] == A2A_MAX_DEPTH

    def test_unknown_from_agent_raises(self) -> None:
        orch = _make_orchestrator()
        with pytest.raises(ValueError, match="Unknown from_agent"):
            orch.send_agent_message(
                from_agent="phantom_agent",
                to_agent="monitor_agent",
                purpose="test",
                payload={},
            )

    def test_unknown_to_agent_raises(self) -> None:
        orch = _make_orchestrator()
        with pytest.raises(ValueError, match="Unknown to_agent"):
            orch.send_agent_message(
                from_agent="devops_agent",
                to_agent="phantom_agent",
                purpose="test",
                payload={},
            )

    def test_self_send_without_allow_self_raises(self) -> None:
        orch = _make_orchestrator()
        with pytest.raises(ValueError, match="Self-send"):
            orch.send_agent_message(
                from_agent="devops_agent",
                to_agent="devops_agent",
                purpose="self",
                payload={},
            )

    def test_self_send_with_allow_self_passes(self) -> None:
        orch = _make_orchestrator()
        mid = f"msg_self_{uuid.uuid4().hex[:8]}"
        result = orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="devops_agent",
            purpose="self-reflect",
            payload={"message": "think"},
            allow_self=True,
            message_id=mid,
        )
        assert result["from_agent"] == result["to_agent"] == "devops_agent"

    def test_duplicate_message_id_raises(self) -> None:
        orch = _make_orchestrator()
        mid = f"dup_test_{uuid.uuid4().hex[:8]}"

        # First send succeeds
        orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="first",
            payload={"message": "hello"},
            message_id=mid,
        )

        # Second with same ID must raise
        with pytest.raises(ValueError, match="Duplicate message_id"):
            orch.send_agent_message(
                from_agent="devops_agent",
                to_agent="monitor_agent",
                purpose="duplicate",
                payload={"message": "again"},
                message_id=mid,
            )


# ---------------------------------------------------------------------------
# PR4 — Inbox Retrieval and Thread History
# ---------------------------------------------------------------------------


class TestA2AInboxRetrieval:
    def test_list_agent_inbox_returns_messages_to_agent(self) -> None:
        orch = _make_orchestrator()
        mid = f"inbox_{uuid.uuid4().hex[:8]}"

        orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="check logs",
            payload={"message": "tail logs"},
            message_id=mid,
        )

        inbox = orch.list_agent_inbox("monitor_agent", limit=100)
        ids = [m["message_id"] for m in inbox]
        assert mid in ids

    def test_list_agent_inbox_excludes_messages_from_other_agents(self) -> None:
        orch = _make_orchestrator()
        mid_to_monitor = f"inbox_monitor_{uuid.uuid4().hex[:8]}"
        mid_to_devops = f"inbox_devops_{uuid.uuid4().hex[:8]}"

        orch.send_agent_message(
            from_agent="security_agent",
            to_agent="monitor_agent",
            purpose="alert",
            payload={"message": "alert!"},
            message_id=mid_to_monitor,
        )
        orch.send_agent_message(
            from_agent="security_agent",
            to_agent="devops_agent",
            purpose="deploy",
            payload={"message": "deploy!"},
            message_id=mid_to_devops,
        )

        monitor_inbox = orch.list_agent_inbox("monitor_agent", limit=100)
        monitor_ids = [m["message_id"] for m in monitor_inbox]
        assert mid_to_monitor in monitor_ids
        assert mid_to_devops not in monitor_ids

    def test_get_message_history_returns_thread_messages(self) -> None:
        orch = _make_orchestrator()
        thread = f"thread_{uuid.uuid4().hex[:8]}"
        mid1 = f"t1_{uuid.uuid4().hex[:8]}"
        mid2 = f"t2_{uuid.uuid4().hex[:8]}"

        orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="step1",
            payload={"message": "first"},
            message_id=mid1,
            thread_id=thread,
        )
        orch.send_agent_message(
            from_agent="monitor_agent",
            to_agent="devops_agent",
            purpose="step2",
            payload={"message": "second"},
            message_id=mid2,
            thread_id=thread,
        )

        history = orch.get_message_history(thread)
        history_ids = [m["message_id"] for m in history]
        assert mid1 in history_ids
        assert mid2 in history_ids

    def test_envelope_depth_preserved(self) -> None:
        orch = _make_orchestrator()
        mid = f"depth_check_{uuid.uuid4().hex[:8]}"

        result = orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="depth test",
            payload={"message": "hello"},
            depth=2,
            message_id=mid,
        )
        assert result["depth"] == 2

    def test_envelope_thread_id_defaults_to_message_id(self) -> None:
        orch = _make_orchestrator()
        mid = f"thread_default_{uuid.uuid4().hex[:8]}"

        result = orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="thread default test",
            payload={"message": "ping"},
            message_id=mid,
        )
        # When no thread_id and no parent, thread_id == message_id
        assert result["thread_id"] == mid

    def test_envelope_has_required_fields(self) -> None:
        orch = _make_orchestrator()
        mid = f"fields_{uuid.uuid4().hex[:8]}"

        result = orch.send_agent_message(
            from_agent="devops_agent",
            to_agent="monitor_agent",
            purpose="field test",
            payload={"message": "test"},
            message_id=mid,
        )
        required_fields = {"message_id", "thread_id", "from_agent", "to_agent", "purpose", "depth", "created_at"}
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_dispatch_a2a_returns_a2a_dispatch_result_type(self) -> None:
        from backend.models import A2ADispatchResult

        orch = _make_orchestrator()

        async def _run() -> Any:
            with (
                patch.object(
                    orch,
                    "send_agent_message",
                    return_value={
                        "message_id": "msg_type_check",
                        "thread_id": "thread_type_check",
                        "from_agent": "devops_agent",
                        "to_agent": "monitor_agent",
                    },
                ),
                patch.object(
                    orch,
                    "process_message",
                    new_callable=AsyncMock,
                    return_value={"response": "done"},
                ),
            ):
                return await orch.dispatch_a2a_message(
                    from_agent="devops_agent",
                    to_agent="monitor_agent",
                    purpose="type check",
                    payload={"message": "hello"},
                )

        result = asyncio.run(_run())
        assert isinstance(result, A2ADispatchResult)
