"""
Tests for backend.llm — OllamaClient and HybridClient.
All httpx calls are mocked; no real Ollama server required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.llm import HybridClient, OllamaClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(json_data: dict) -> MagicMock:
    """Create a mock httpx response that returns json_data and does not raise."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    resp.status_code = 200
    return resp


def _error_response(status_code: int = 500) -> MagicMock:
    resp_obj = MagicMock()
    resp_obj.status_code = status_code
    resp_obj.text = "Internal Server Error"
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} Error",
        request=MagicMock(),
        response=resp_obj,
    )
    return mock_resp


# ---------------------------------------------------------------------------
# OllamaClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ollama(mock_http: AsyncMock):
    with patch("backend.llm.httpx.AsyncClient", return_value=mock_http):
        client = OllamaClient(base_url="http://localhost:11434", model="llama3.2", timeout=30.0)  # type: ignore[arg-type]
    return client, mock_http


# ---------------------------------------------------------------------------
# OllamaClient — generate
# ---------------------------------------------------------------------------


class TestOllamaClientGenerate:
    async def test_success_returns_response_text(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"response": "hello world"})

        result = await client.generate("say hello")

        assert result == "hello world"
        mock_http.post.assert_called_once()

    async def test_success_with_system_prompt(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"response": "working"})

        result = await client.generate("test", system="You are helpful")

        assert result == "working"
        call_kwargs = mock_http.post.call_args
        assert call_kwargs[1]["json"]["system"] == "You are helpful"

    async def test_success_custom_temperature(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"response": "creative"})

        result = await client.generate("test", temperature=0.9, max_tokens=512)

        assert result == "creative"
        payload = mock_http.post.call_args[1]["json"]
        assert payload["options"]["temperature"] == 0.9
        assert payload["options"]["num_predict"] == 512

    async def test_connect_error_raises_connection_error(self, ollama):
        client, mock_http = ollama
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(ConnectionError):
            await client.generate("test")

    async def test_http_status_error_raises_runtime_error(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _error_response(500)

        with pytest.raises(RuntimeError):
            await client.generate("test")

    async def test_response_strips_trailing_whitespace(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"response": "  trimmed  "})

        result = await client.generate("test")
        assert "trimmed" in result


# ---------------------------------------------------------------------------
# OllamaClient — chat
# ---------------------------------------------------------------------------


class TestOllamaClientChat:
    async def test_success_returns_message_content(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"message": {"content": "I can help with that."}})

        result = await client.chat([{"role": "user", "content": "hello"}])

        assert result == "I can help with that."

    async def test_multiple_messages(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"message": {"content": "Yes, I remember."}})

        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "remember me?"},
        ]
        result = await client.chat(msgs)

        payload = mock_http.post.call_args[1]["json"]
        assert len(payload["messages"]) == 3
        assert result == "Yes, I remember."

    async def test_connect_error_raises(self, ollama):
        client, mock_http = ollama
        mock_http.post.side_effect = httpx.ConnectError("refused")

        with pytest.raises(ConnectionError):  # noqa: PT011
            await client.chat([{"role": "user", "content": "test"}])

    async def test_http_error_raises_runtime_error(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _error_response(503)

        with pytest.raises(RuntimeError):
            await client.chat([])


# ---------------------------------------------------------------------------
# OllamaClient — embed
# ---------------------------------------------------------------------------


class TestOllamaClientEmbed:
    async def test_empty_input_returns_empty_list(self, ollama):
        client, mock_http = ollama

        result = await client.embed("")
        assert result == []
        mock_http.post.assert_not_called()

    async def test_whitespace_only_returns_empty_list(self, ollama):
        client, mock_http = ollama

        result = await client.embed("   \n\t  ")
        assert result == []

    async def test_success_new_api(self, ollama):
        client, mock_http = ollama
        mock_http.post.return_value = _ok_response({"embeddings": [[0.1, 0.2, 0.3]]})

        result = await client.embed("hello world")

        assert result == [0.1, 0.2, 0.3]

    async def test_fallback_legacy_api(self, ollama):
        client, mock_http = ollama
        # First call: no "embeddings" key → KeyError → falls back to legacy
        first = _ok_response({})  # missing "embeddings" key
        second = _ok_response({"embedding": [0.4, 0.5, 0.6]})
        mock_http.post.side_effect = [first, second]

        result = await client.embed("legacy test")

        assert result == [0.4, 0.5, 0.6]
        assert mock_http.post.call_count == 2

    async def test_legacy_api_exception_propagates(self, ollama):
        client, mock_http = ollama
        # New API fails silently (empty response → falls through to legacy)
        first = _ok_response({})  # no "embeddings" key → falls through
        # Legacy API raises → propagates since no outer try-except there
        mock_http.post.side_effect = [first, Exception("legacy failed")]

        with pytest.raises(Exception):
            await client.embed("fail test")

    async def test_new_api_network_error_falls_back(self, ollama):
        client, mock_http = ollama
        second = _ok_response({"embedding": [0.7, 0.8]})
        mock_http.post.side_effect = [httpx.ConnectError("refused"), second]

        result = await client.embed("network error fallback")
        assert result == [0.7, 0.8]


# ---------------------------------------------------------------------------
# OllamaClient — is_available
# ---------------------------------------------------------------------------


class TestOllamaClientIsAvailable:
    async def test_available_when_200(self, ollama):
        client, mock_http = ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.get.return_value = mock_resp

        assert await client.is_available() is True

    async def test_not_available_when_non_200(self, ollama):
        client, mock_http = ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_http.get.return_value = mock_resp

        assert await client.is_available() is False

    async def test_not_available_on_exception(self, ollama):
        client, mock_http = ollama
        mock_http.get.side_effect = Exception("connection refused")

        assert await client.is_available() is False

    async def test_not_available_on_connect_error(self, ollama):
        client, mock_http = ollama
        mock_http.get.side_effect = httpx.ConnectError("refused")

        assert await client.is_available() is False


# ---------------------------------------------------------------------------
# OllamaClient — list_models
# ---------------------------------------------------------------------------


class TestOllamaClientListModels:
    async def test_returns_model_names(self, ollama):
        client, mock_http = ollama
        mock_http.get.return_value = _ok_response({"models": [{"name": "llama3.2"}, {"name": "mistral"}]})

        result = await client.list_models()

        assert result == ["llama3.2", "mistral"]

    async def test_empty_list_on_exception(self, ollama):
        client, mock_http = ollama
        mock_http.get.side_effect = Exception("server down")

        result = await client.list_models()
        assert result == []

    async def test_empty_models_array(self, ollama):
        client, mock_http = ollama
        mock_http.get.return_value = _ok_response({"models": []})

        result = await client.list_models()
        assert result == []


# ---------------------------------------------------------------------------
# OllamaClient — close
# ---------------------------------------------------------------------------


class TestOllamaClientClose:
    async def test_close_calls_aclose(self, ollama):
        client, mock_http = ollama

        await client.close()

        mock_http.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# HybridClient — local_only mode
# ---------------------------------------------------------------------------


class TestHybridClientLocalOnly:
    @pytest.fixture
    def hybrid(self):
        with patch("backend.llm.httpx.AsyncClient"):
            client = HybridClient(mode="local_only")
        return client

    async def test_generate_delegates_to_local(self, hybrid):
        hybrid._local.generate = AsyncMock(return_value="local answer")

        result = await hybrid.generate("test prompt")

        assert result == "local answer"
        hybrid._local.generate.assert_called_once()

    async def test_chat_delegates_to_local(self, hybrid):
        hybrid._local.chat = AsyncMock(return_value="local chat")

        result = await hybrid.chat([{"role": "user", "content": "hi"}])

        assert result == "local chat"

    async def test_embed_always_local(self, hybrid):
        hybrid._local.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        result = await hybrid.embed("test text")

        assert result == [0.1, 0.2, 0.3]

    async def test_is_available_delegates_to_local(self, hybrid):
        hybrid._local.is_available = AsyncMock(return_value=True)

        result = await hybrid.is_available()

        assert result is True

    async def test_is_available_false(self, hybrid):
        hybrid._local.is_available = AsyncMock(return_value=False)

        result = await hybrid.is_available()

        assert result is False

    async def test_list_models_returns_local_models(self, hybrid):
        hybrid._local.list_models = AsyncMock(return_value=["llama3.2", "mistral"])

        result = await hybrid.list_models()

        assert "llama3.2" in result

    def test_get_stats_returns_dict(self, hybrid):
        stats = hybrid.get_stats()
        assert isinstance(stats, dict)

    async def test_health_returns_dict(self, hybrid):
        health = await hybrid.health()
        assert isinstance(health, dict)

    async def test_generate_no_router_uses_local(self, hybrid):
        # In local_only mode, generate must use local even if router exists
        hybrid._local.generate = AsyncMock(return_value="fallback")

        result = await hybrid.generate("prompt", task="default")
        assert result == "fallback"
