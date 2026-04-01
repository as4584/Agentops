"""
Mock Ollama Server — deterministic LLM responses for testing.

Provides a pytest fixture that intercepts all httpx calls to Ollama
and returns canned responses. Zero network. Zero GPU. Fully deterministic.

Usage in tests:
    def test_something(mock_ollama):
        # All OllamaClient calls now return deterministic responses
        client = OllamaClient()
        result = await client.generate("deploy to prod")
        assert "devops_agent" in result
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

# ── Canned routing responses keyed by keyword patterns ───────────────────────

_ROUTING_RESPONSES: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (
        re.compile(r"deploy|ci.?cd|git push|build|pipeline", re.I),
        {
            "agent_id": "devops_agent",
            "reasoning": "Deployment and CI/CD operations require devops expertise",
            "tools_needed": ["git_ops", "safe_shell"],
            "confidence": 0.95,
        },
    ),
    (
        re.compile(r"scan.*secret|vulnerab|cve|security audit", re.I),
        {
            "agent_id": "security_agent",
            "reasoning": "Security-focused task requiring vulnerability scanning",
            "tools_needed": ["secret_scanner"],
            "confidence": 0.97,
        },
    ),
    (
        re.compile(r"health|monitor|alert|metric|cpu|memory usage", re.I),
        {
            "agent_id": "monitor_agent",
            "reasoning": "Health monitoring and alerting task",
            "tools_needed": ["health_check", "log_tail"],
            "confidence": 0.92,
        },
    ),
    (
        re.compile(r"crash|restart|fix.*process|self.?heal|recover", re.I),
        {
            "agent_id": "self_healer_agent",
            "reasoning": "Process recovery requiring automated remediation",
            "tools_needed": ["process_restart", "health_check"],
            "confidence": 0.94,
        },
    ),
    (
        re.compile(r"review.*code|diff|pr |pull request|lint", re.I),
        {
            "agent_id": "code_review_agent",
            "reasoning": "Code review and quality enforcement",
            "tools_needed": ["file_reader", "git_ops"],
            "confidence": 0.91,
        },
    ),
    (
        re.compile(r"query|sql|schema|etl|database|table", re.I),
        {
            "agent_id": "data_agent",
            "reasoning": "Data operations requiring database access",
            "tools_needed": ["db_query"],
            "confidence": 0.93,
        },
    ),
    (
        re.compile(r"webhook|notify|incident|slack|email", re.I),
        {
            "agent_id": "comms_agent",
            "reasoning": "Communication and notification task",
            "tools_needed": ["webhook_send", "alert_dispatch"],
            "confidence": 0.90,
        },
    ),
    (
        re.compile(r"customer|support|faq|ticket|help desk", re.I),
        {
            "agent_id": "cs_agent",
            "reasoning": "Customer support inquiry",
            "tools_needed": ["db_query", "file_reader"],
            "confidence": 0.89,
        },
    ),
    (
        re.compile(r"network|dns|port|infra|diagnostic|ping", re.I),
        {
            "agent_id": "it_agent",
            "reasoning": "Infrastructure diagnostics",
            "tools_needed": ["system_info", "health_check"],
            "confidence": 0.91,
        },
    ),
    (
        re.compile(r"search.*doc|knowledge|semantic|find.*info", re.I),
        {
            "agent_id": "knowledge_agent",
            "reasoning": "Semantic search over knowledge base",
            "tools_needed": ["file_reader"],
            "confidence": 0.88,
        },
    ),
    (
        re.compile(r"reflect|trust|purpose|goal|soul|meaning|who am i", re.I),
        {
            "agent_id": "soul_core",
            "reasoning": "Reflection and purpose-level reasoning",
            "tools_needed": [],
            "confidence": 0.96,
        },
    ),
]

# Default fallback
_DEFAULT_ROUTING = {
    "agent_id": "soul_core",
    "reasoning": "Ambiguous task routed to soul for arbitration",
    "tools_needed": [],
    "confidence": 0.60,
}


def _match_routing(prompt: str) -> str:
    """Return a JSON routing response for the given prompt."""
    for pattern, response in _ROUTING_RESPONSES:
        if pattern.search(prompt):
            return json.dumps(response)
    return json.dumps(_DEFAULT_ROUTING)


def _make_generate_response(prompt: str) -> dict[str, Any]:
    """Build a full /api/generate response matching Ollama's schema."""
    text = _match_routing(prompt)
    return {
        "model": "lex-v2",
        "response": text,
        "done": True,
        "total_duration": 800_000_000,  # 800ms
        "load_duration": 50_000_000,
        "prompt_eval_count": len(prompt.split()),
        "prompt_eval_duration": 100_000_000,
        "eval_count": len(text.split()),
        "eval_duration": 700_000_000,
    }


def _make_chat_response(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Build a full /api/chat response matching Ollama's schema."""
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = msg.get("content", "")
            break
    text = _match_routing(last_user)
    return {
        "model": "lex-v2",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "total_duration": 800_000_000,
        "load_duration": 50_000_000,
        "prompt_eval_count": sum(len(m.get("content", "").split()) for m in messages),
        "prompt_eval_duration": 100_000_000,
        "eval_count": len(text.split()),
        "eval_duration": 700_000_000,
    }


def _make_embed_response(text: str) -> dict[str, Any]:
    """Build a mock /api/embed response — deterministic 384-dim vector."""
    import hashlib

    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    # Deterministic pseudo-random vector based on input hash
    vec = [(((seed * (i + 1) * 6364136223846793005) >> 33) % 10000) / 10000.0 - 0.5 for i in range(384)]
    return {
        "model": "lex-v2",
        "embeddings": [vec],
    }


def _make_tags_response() -> dict[str, Any]:
    """Build a mock /api/tags response (model list)."""
    return {
        "models": [
            {"name": "lex-v2", "size": 2_000_000_000, "parameter_size": "3B"},
            {"name": "llama3.2", "size": 2_000_000_000, "parameter_size": "3B"},
        ]
    }


class MockOllamaTransport(httpx.MockTransport):
    """
    httpx transport that intercepts all Ollama API calls.
    Drop-in replacement — no real network, fully deterministic.
    """

    def __init__(self) -> None:
        super().__init__(self._handler)
        self.call_log: list[dict[str, Any]] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        self.call_log.append({"path": path, "body": body})

        if path == "/api/generate":
            data = _make_generate_response(body.get("prompt", ""))
            return httpx.Response(200, json=data)

        elif path == "/api/chat":
            data = _make_chat_response(body.get("messages", []))
            return httpx.Response(200, json=data)

        elif path == "/api/embed":
            data = _make_embed_response(body.get("input", ""))
            return httpx.Response(200, json=data)

        elif path == "/api/tags":
            return httpx.Response(200, json=_make_tags_response())

        elif path == "/api/show":
            return httpx.Response(200, json={"modelfile": "FROM llama3.2"})

        elif path == "/":
            return httpx.Response(200, text="Ollama is running")

        else:
            return httpx.Response(404, json={"error": f"unknown endpoint: {path}"})


@pytest.fixture
def mock_ollama(monkeypatch: pytest.MonkeyPatch) -> MockOllamaTransport:
    """
    Pytest fixture that replaces all httpx.AsyncClient instances
    with a mock Ollama transport. No network calls escape.

    Usage:
        def test_agent_routing(mock_ollama):
            # OllamaClient will hit mock_ollama instead of real Ollama
            ...
            assert len(mock_ollama.call_log) == 1
    """
    transport = MockOllamaTransport()

    _original_init = httpx.AsyncClient.__init__

    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        # Remove any base_url that might conflict
        _original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)

    # Also patch sync client for any sync Ollama calls
    _original_sync_init = httpx.Client.__init__

    def _patched_sync_init(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        _original_sync_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", _patched_sync_init)

    return transport
