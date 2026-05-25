"""
Tests for chat_failure_log module and the chat route failure capture path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Unit tests — write_chat_failure
# ---------------------------------------------------------------------------

class TestWriteChatFailure:
    """Tests for the write_chat_failure JSONL writer."""

    def test_creates_file_and_writes_record(self, tmp_path: Path) -> None:
        """A failure record is persisted to the monthly JSONL file."""
        import backend.utils.chat_failure_log as _mod

        with patch.object(_mod, "_DPO_DIR", tmp_path):
            _mod.write_chat_failure(
                request_id="abc12345",
                user_message="hello",
                chosen_agent="cs_agent",
                selected_model="lex-v3",
                last_live_step="step 1: thinking",
                ordo_trace={"lane": "support", "confidence": 0.9},
                error_class="ConnectionError",
                error_detail="Cannot connect to Ollama",
                route_path="/chat",
                pipeline_stage="llm_connect",
            )

        now = datetime.now(UTC)
        month_tag = now.strftime("%Y-%m")
        output = tmp_path / f"chat_failures_{month_tag}.jsonl"
        assert output.exists()

        lines = output.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])

        assert record["request_id"] == "abc12345"
        assert record["user_message"] == "hello"
        assert record["chosen_agent"] == "cs_agent"
        assert record["selected_model"] == "lex-v3"
        assert record["last_live_step"] == "step 1: thinking"
        assert record["ordo_trace"]["lane"] == "support"
        assert record["error_class"] == "ConnectionError"
        assert record["error_detail"] == "Cannot connect to Ollama"
        assert record["route_path"] == "/chat"
        assert record["pipeline_stage"] == "llm_connect"
        # Good response must NOT be present — only negatives
        assert "good_response" not in record

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        """Multiple failures are appended to the same file without overwriting."""
        import backend.utils.chat_failure_log as _mod

        with patch.object(_mod, "_DPO_DIR", tmp_path):
            for i in range(3):
                _mod.write_chat_failure(
                    request_id=f"req{i}",
                    user_message=f"msg {i}",
                    chosen_agent="cs_agent",
                    selected_model=None,
                    last_live_step=None,
                    ordo_trace=None,
                    error_class="TimeoutError",
                    error_detail="timed out",
                )

        month_tag = datetime.now(UTC).strftime("%Y-%m")
        output = tmp_path / f"chat_failures_{month_tag}.jsonl"
        lines = output.read_text().splitlines()
        assert len(lines) == 3
        ids = [json.loads(ln)["request_id"] for ln in lines]
        assert ids == ["req0", "req1", "req2"]

    def test_truncates_long_user_message(self, tmp_path: Path) -> None:
        """User messages longer than 500 chars are truncated."""
        import backend.utils.chat_failure_log as _mod

        long_msg = "x" * 1000
        with patch.object(_mod, "_DPO_DIR", tmp_path):
            _mod.write_chat_failure(
                request_id="trunc",
                user_message=long_msg,
                chosen_agent=None,
                selected_model=None,
                last_live_step=None,
                ordo_trace=None,
                error_class="RuntimeError",
                error_detail="oops",
            )

        month_tag = datetime.now(UTC).strftime("%Y-%m")
        output = tmp_path / f"chat_failures_{month_tag}.jsonl"
        record = json.loads(output.read_text())
        assert len(record["user_message"]) == 500

    def test_none_values_are_preserved(self, tmp_path: Path) -> None:
        """Optional fields can be None without error."""
        import backend.utils.chat_failure_log as _mod

        with patch.object(_mod, "_DPO_DIR", tmp_path):
            _mod.write_chat_failure(
                request_id="null-test",
                user_message="hi",
                chosen_agent=None,
                selected_model=None,
                last_live_step=None,
                ordo_trace=None,
                error_class="UnknownError",
                error_detail="something",
            )

        month_tag = datetime.now(UTC).strftime("%Y-%m")
        output = tmp_path / f"chat_failures_{month_tag}.jsonl"
        record = json.loads(output.read_text())
        assert record["chosen_agent"] is None
        assert record["ordo_trace"] is None

    def test_io_error_does_not_propagate(self, tmp_path: Path) -> None:
        """An IO failure in the writer is silently swallowed."""
        import backend.utils.chat_failure_log as _mod

        # Point to a non-writable path
        bad_path = tmp_path / "readonly_dir"
        bad_path.mkdir()
        bad_path.chmod(0o555)

        try:
            with patch.object(_mod, "_DPO_DIR", bad_path / "subdir"):
                # Should NOT raise
                _mod.write_chat_failure(
                    request_id="io-err",
                    user_message="test",
                    chosen_agent=None,
                    selected_model=None,
                    last_live_step=None,
                    ordo_trace=None,
                    error_class="IOError",
                    error_detail="write failed",
                )
        finally:
            bad_path.chmod(0o755)

    def test_record_has_timestamp(self, tmp_path: Path) -> None:
        """Every record has an ISO timestamp."""
        import backend.utils.chat_failure_log as _mod

        with patch.object(_mod, "_DPO_DIR", tmp_path):
            _mod.write_chat_failure(
                request_id="ts-test",
                user_message="check timestamp",
                chosen_agent="soul_core",
                selected_model="lex-v3",
                last_live_step=None,
                ordo_trace=None,
                error_class="ValueError",
                error_detail="bad value",
            )

        month_tag = datetime.now(UTC).strftime("%Y-%m")
        output = tmp_path / f"chat_failures_{month_tag}.jsonl"
        record = json.loads(output.read_text())
        ts = record.get("timestamp")
        assert ts is not None
        # Should parse as an ISO datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt.year >= 2024


# ---------------------------------------------------------------------------
# Integration tests — chat route failure capture path
# ---------------------------------------------------------------------------

class TestChatRouteWiring:
    """Verify that the chat route wires write_chat_failure without importing the server app."""

    def _server_src(self) -> str:
        """Read server.py source — parents[2] from backend/tests/ is the repo root."""
        return (__import__("pathlib").Path(__file__).parents[1] / "server.py").read_text()

    def test_chat_failure_log_imported_in_server(self) -> None:
        """write_chat_failure is imported in server.py (wired up)."""
        assert "from backend.utils.chat_failure_log import write_chat_failure" in self._server_src()

    def test_connection_error_handled_in_chat_route(self) -> None:
        """The chat route has a ConnectionError handler that calls write_chat_failure."""
        src = self._server_src()
        assert "except ConnectionError as _conn_exc:" in src
        assert "write_chat_failure(" in src
        assert 'pipeline_stage="llm_connect"' in src
        assert "status_code=503" in src

    def test_orchestrator_exception_re_raises(self) -> None:
        """Unexpected orchestrator exceptions are caught, logged, then re-raised (not swallowed)."""
        src = self._server_src()
        assert 'pipeline_stage="orchestrator"' in src
        handler_block = src[
            src.index('pipeline_stage="orchestrator"'):
            src.index('pipeline_stage="orchestrator"') + 200
        ]
        assert "raise" in handler_block
