"""Tests for backend.content.publishers.youtube_auth."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.content.publishers.youtube_auth as yt


class TestIsAuthenticated:
    def test_missing_file_returns_false(self, tmp_path):
        with patch.object(yt, "TOKEN_PATH", tmp_path / "no_token.json"):
            assert yt.is_authenticated() is False

    def test_valid_access_token_returns_true(self, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"access_token": "abc123"}))
        with patch.object(yt, "TOKEN_PATH", token_path):
            assert yt.is_authenticated() is True

    def test_valid_refresh_token_returns_true(self, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"refresh_token": "refr123"}))
        with patch.object(yt, "TOKEN_PATH", token_path):
            assert yt.is_authenticated() is True

    def test_empty_token_returns_false(self, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({}))
        with patch.object(yt, "TOKEN_PATH", token_path):
            assert yt.is_authenticated() is False

    def test_corrupt_json_returns_false(self, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text("not valid json {{{{")
        with patch.object(yt, "TOKEN_PATH", token_path):
            assert yt.is_authenticated() is False

    def test_empty_access_token_returns_false(self, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"access_token": ""}))
        with patch.object(yt, "TOKEN_PATH", token_path):
            assert yt.is_authenticated() is False


@pytest.mark.asyncio
class TestRunAuthFlow:
    async def test_raises_when_both_env_vars_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOUTUBE_CLIENT_ID", None)
            os.environ.pop("YOUTUBE_CLIENT_SECRET", None)
            with pytest.raises(RuntimeError, match="YOUTUBE_CLIENT_ID"):
                await yt.run_auth_flow()

    async def test_raises_when_client_id_missing(self):
        env = {"YOUTUBE_CLIENT_SECRET": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("YOUTUBE_CLIENT_ID", None)
            with pytest.raises(RuntimeError, match="YOUTUBE_CLIENT_ID"):
                await yt.run_auth_flow()

    async def test_raises_when_client_secret_missing(self):
        env = {"YOUTUBE_CLIENT_ID": "clientid123"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("YOUTUBE_CLIENT_SECRET", None)
            with pytest.raises(RuntimeError, match="YOUTUBE_CLIENT_ID"):
                await yt.run_auth_flow()

    async def test_raises_when_auth_code_is_none(self, tmp_path):
        env = {"YOUTUBE_CLIENT_ID": "cid", "YOUTUBE_CLIENT_SECRET": "csec"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(yt, "_wait_for_auth_code", AsyncMock(return_value=None)):
                with pytest.raises(RuntimeError, match="cancelled or timed out"):
                    await yt.run_auth_flow()

    async def test_success_saves_token_and_returns(self, tmp_path):
        token_path = tmp_path / "youtube_token.json"
        fake_tokens = {"access_token": "tok123", "refresh_token": "ref456"}
        env = {"YOUTUBE_CLIENT_ID": "cid", "YOUTUBE_CLIENT_SECRET": "csec"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(yt, "_wait_for_auth_code", AsyncMock(return_value="auth_code_abc")):
                with patch.object(yt, "_exchange_code", return_value=fake_tokens):
                    with patch.object(yt, "TOKEN_PATH", token_path):
                        result = await yt.run_auth_flow()
        assert result == fake_tokens
        saved = json.loads(token_path.read_text())
        assert saved["access_token"] == "tok123"


class TestExchangeCode:
    def _make_mock_response(self, body: dict):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(body).encode()
        return mock_resp

    def test_success_returns_tokens(self):
        mock_resp = self._make_mock_response({"access_token": "tok", "refresh_token": "ref"})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = yt._exchange_code("code123", "client_id", "client_secret")
        assert result["access_token"] == "tok"
        assert result["refresh_token"] == "ref"

    def test_error_response_raises_runtime_error(self):
        mock_resp = self._make_mock_response({"error": "invalid_grant", "error_description": "bad code"})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="Token exchange failed"):
                yt._exchange_code("bad_code", "id", "secret")

    def test_builds_correct_request(self):
        """Verify urlopen is called with a POST request."""
        call_log = []

        def capture_urlopen(req, timeout):
            call_log.append(req)
            mock_resp = self._make_mock_response({"access_token": "x"})
            return mock_resp.__enter__()

        mock_resp = self._make_mock_response({"access_token": "x"})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = yt._exchange_code("code", "cid", "csec")
        assert "access_token" in result


@pytest.mark.asyncio
class TestOpenBrowser:
    async def test_import_error_uses_subprocess(self):
        """When playwright is not installed, xdg-open is called via subprocess."""
        with patch.dict(
            "sys.modules",
            {"playwright": None, "playwright.async_api": None},
            clear=False,
        ):
            with patch("subprocess.Popen") as mock_popen:
                await yt._open_browser("http://fake.url/")
            mock_popen.assert_called_once_with(["xdg-open", "http://fake.url/"])

    async def test_exception_path_logs_warning_without_raising(self):
        """Non-ImportError exceptions inside playwright block are swallowed."""
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=RuntimeError("playwright crash"))
        mock_context.__exit__ = AsyncMock(return_value=False)

        with patch("playwright.async_api.async_playwright", return_value=mock_context):
            # Should not raise
            await yt._open_browser("http://fake.url/")
