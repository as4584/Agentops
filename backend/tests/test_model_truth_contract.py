from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.server as server_module
from backend.models import ChatRequest
from backend.tasks import TaskTracker


@pytest.mark.asyncio
async def test_set_team_model_preference_fans_out_mapped_agents() -> None:
    with (
        patch.dict(server_module._team_model_preferences, {"orchad": "qwen2.5-coder:7b"}, clear=True),
        patch.dict(server_module._agent_model_overrides, {}, clear=True),
        patch.object(server_module, "save_team_model_preferences"),
        patch.object(server_module, "save_agent_model_overrides"),
    ):
        result = await server_module.set_team_model_preference("social", {"model_id": "deepseek-r1:7b"})

    assert result["team_id"] == "social"
    assert result["selected_model"] == "deepseek-r1:7b"
    assert result["resolved_agent_models"]["comms_agent"] == "deepseek-r1:7b"
    assert result["resolved_agent_models"]["cs_agent"] == "deepseek-r1:7b"
    assert "webgen" not in server_module._agent_model_overrides


@pytest.mark.asyncio
async def test_chat_returns_truthful_model_metadata_for_routed_team_default() -> None:
    orchestrator = MagicMock()
    orchestrator.process_message = AsyncMock(
        return_value={
            "response": "Deployment queued.",
            "drift_status": "GREEN",
            "model_execution": {
                "selected_model": "mistral:7b",
                "answering_model": "mistral:7b",
                "runtime_model": "mistral:7b-instruct-q4_K_M",
                "execution_role": "executor",
                "model_source": "team_default",
            },
        }
    )

    req = ChatRequest(agent_id="auto", message="deploy the latest build")
    resolve_agent = AsyncMock(return_value={"agent_id": "devops_agent"})

    with (
        patch.object(server_module, "_orchestrator", orchestrator),
        patch.object(server_module, "_execution_recorder", None),
        patch.object(server_module, "_execution_analyzer", None),
        patch.dict(
            server_module._team_model_preferences,
            {"orchad": "qwen2.5-coder:7b", "dev": "mistral:7b", "social": "llama3.2"},
            clear=True,
        ),
        patch.dict(server_module._agent_model_overrides, {}, clear=True),
        patch.object(server_module.task_tracker, "create_or_attach_conversation", return_value="conv-1"),
        patch.object(server_module.task_tracker, "append_message", side_effect=["msg-user", "msg-assistant"]) as append_mock,
        patch.object(server_module.task_tracker, "emit_activity"),
        patch("backend.orchestrator.lex_router.resolve_agent", resolve_agent),
    ):
        result = await server_module.chat(req)

    _, kwargs = orchestrator.process_message.await_args
    assert kwargs["agent_id"] == "devops_agent"
    assert kwargs["context"]["model"] == "mistral:7b"
    assert kwargs["context"]["_model_selection"]["model_source"] == "team_default"

    assert result.agent_id == "devops_agent"
    assert result.selected_model == "mistral:7b"
    assert result.answering_model == "mistral:7b"
    assert result.runtime_model == "mistral:7b-instruct-q4_K_M"
    assert result.execution_role == "executor"
    assert result.model_source == "team_default"
    assert result.model_used == "mistral:7b"

    assistant_call = append_mock.call_args_list[1]
    persisted_meta = assistant_call.kwargs["message_meta"]
    assert persisted_meta["selected_model"] == "mistral:7b"
    assert persisted_meta["answering_model"] == "mistral:7b"
    assert persisted_meta["runtime_model"] == "mistral:7b-instruct-q4_K_M"
    assert persisted_meta["execution_role"] == "executor"
    assert persisted_meta["model_source"] == "team_default"


@pytest.mark.asyncio
async def test_list_model_registry_resolves_runtime_model_alias() -> None:
    mock_llm = MagicMock()
    mock_llm.list_models = AsyncMock(return_value=["mistral:7b-instruct-q4_K_M"])

    with patch.object(server_module, "_llm_client", mock_llm):
        result = await server_module.list_model_registry()

    mistral = next(model for model in result["models"] if model["model_id"] == "mistral:7b")
    assert mistral["available_locally"] is True
    assert mistral["runtime_model_id"] == "mistral:7b-instruct-q4_K_M"


def test_task_tracker_round_trips_message_meta(tmp_path: Path) -> None:
    tracker = TaskTracker(db_path=tmp_path / "tasks.db")
    conversation_id = tracker.create_or_attach_conversation(agent_id="soul_core")

    tracker.append_message(
        conversation_id,
        "assistant",
        "Hello from Orchad",
        "soul_core",
        "run-1",
        message_meta={
            "selected_model": "qwen2.5-coder:7b",
            "answering_model": "qwen2.5-coder:7b",
            "runtime_model": "qwen2.5-coder:7b",
            "execution_role": "executor",
            "model_source": "team_default",
            "routing_method": "lex",
        },
    )

    messages = tracker.get_messages(conversation_id)
    assert len(messages) == 1
    assert messages[0]["selected_model"] == "qwen2.5-coder:7b"
    assert messages[0]["answering_model"] == "qwen2.5-coder:7b"
    assert messages[0]["runtime_model"] == "qwen2.5-coder:7b"
    assert messages[0]["execution_role"] == "executor"
    assert messages[0]["model_source"] == "team_default"
    assert messages[0]["routing_method"] == "lex"
