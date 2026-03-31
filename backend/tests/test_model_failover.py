from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_circuit_opens_after_three_failures():
    from backend.llm.unified_registry import UnifiedModelRouter

    router = UnifiedModelRouter()
    model_id = "llama3.2"
    record_failure = getattr(router, "_record_failure")
    is_circuit_open = getattr(router, "_is_circuit_open")

    record_failure(model_id, RuntimeError("first"))
    assert is_circuit_open(model_id) is False

    record_failure(model_id, RuntimeError("second"))
    assert is_circuit_open(model_id) is False

    record_failure(model_id, RuntimeError("third"))
    assert is_circuit_open(model_id) is True


def test_circuit_resets_after_timeout(monkeypatch: MonkeyPatch):
    import backend.llm.unified_registry as registry_module
    from backend.config import LLM_CIRCUIT_RESET_SECONDS
    from backend.llm.unified_registry import UnifiedModelRouter

    now = 1000.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr(registry_module.time, "monotonic", fake_monotonic)

    router = UnifiedModelRouter()
    model_id = "llama3.2"
    record_failure = getattr(router, "_record_failure")
    is_circuit_open = getattr(router, "_is_circuit_open")

    record_failure(model_id, RuntimeError("first"))
    record_failure(model_id, RuntimeError("second"))
    record_failure(model_id, RuntimeError("third"))

    assert is_circuit_open(model_id) is True

    now += LLM_CIRCUIT_RESET_SECONDS + 1
    assert is_circuit_open(model_id) is False

    state = router.get_health_summary()[model_id]
    assert state["circuit_open"] is False
    assert state["consecutive_failures"] == 0
    assert state["healthy"] is True


def test_is_model_healthy_false_for_open_circuit_without_client_calls():
    from backend.llm.unified_registry import UnifiedModelRouter

    class BombClient:
        async def is_available(self) -> bool:  # pragma: no cover
            raise AssertionError("is_available should not be called when circuit is open")

        async def list_models(self) -> list[str]:  # pragma: no cover
            raise AssertionError("list_models should not be called when circuit is open")

    router = UnifiedModelRouter()
    router._local_client = BombClient()  # type: ignore[assignment]

    model_id = "llama3.2"
    record_failure = getattr(router, "_record_failure")
    record_failure(model_id, RuntimeError("first"))
    record_failure(model_id, RuntimeError("second"))
    record_failure(model_id, RuntimeError("third"))

    is_model_healthy = getattr(router, "_is_model_healthy")
    healthy = asyncio.run(is_model_healthy(model_id))
    assert healthy is False


def test_generate_uses_fallback_when_primary_fails(monkeypatch: MonkeyPatch):
    from backend.llm.unified_registry import UnifiedModelRouter

    router = UnifiedModelRouter()

    async def always_healthy(model_id: str) -> bool:
        return True

    async def fake_call_model(
        *,
        spec: Any,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if spec.model_id == "llama3.2:1b":
            raise RuntimeError("primary failed")
        return {
            "model_id": spec.model_id,
            "provider": spec.provider.value,
            "output": "fallback ok",
            "estimated_cost_usd": 0.0,
        }

    monkeypatch.setattr(router, "_is_model_healthy", always_healthy)
    monkeypatch.setattr(router, "_call_model", fake_call_model)

    result = asyncio.run(
        router.generate(
            prompt="test",
            model="llama3.2:1b",
        )
    )

    assert result["output"] == "fallback ok"
    assert result["fallback_used"] == "llama3.2"
    assert result["effective_model"] == "llama3.2"


def test_generate_raises_when_all_candidates_fail(monkeypatch: MonkeyPatch):
    from backend.llm.unified_registry import AllModelsFailedError, UnifiedModelRouter

    router = UnifiedModelRouter()

    async def always_healthy(model_id: str) -> bool:
        return True

    async def always_fail(
        *,
        spec: Any,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        raise RuntimeError(f"failure: {spec.model_id}")

    monkeypatch.setattr(router, "_is_model_healthy", always_healthy)
    monkeypatch.setattr(router, "_call_model", always_fail)

    with pytest.raises(AllModelsFailedError) as exc:
        asyncio.run(router.generate(prompt="test", model="llama3.2:1b"))

    assert "All candidates exhausted" in str(exc.value)


def test_generate_with_tools_sets_fallback_metadata(monkeypatch: MonkeyPatch):
    from backend.llm.unified_registry import UnifiedModelRouter

    router = UnifiedModelRouter()

    async def always_healthy(model_id: str) -> bool:
        return True

    async def fake_call_with_tools(
        *,
        spec: Any,
        messages: list[dict[str, Any]],
        sanitized_tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        reg: Any,
    ) -> dict[str, Any]:
        if spec.model_id == "openai:gpt-4o":
            raise RuntimeError("primary tools model failed")
        return {
            "model_id": spec.model_id,
            "provider": spec.provider.value,
            "output": "tool fallback ok",
            "tool_calls": [],
            "estimated_cost_usd": 0.0,
            "registry": reg,
        }

    monkeypatch.setattr(router, "_is_model_healthy", always_healthy)
    monkeypatch.setattr(router, "_call_model_with_tools", fake_call_with_tools)

    result = asyncio.run(
        router.generate_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "sample_tool",
                        "description": "sample",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            model="openai:gpt-4o",
        )
    )

    assert result["output"] == "tool fallback ok"
    assert result["fallback_used"] == "claude-sonnet"
    assert result["effective_model"] == "claude-sonnet"
