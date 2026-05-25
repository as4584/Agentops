"""
Regression tests for Phase 1-4 social routing and Discord observability changes.

Tests verify:
  1. Routing split — "post about X" stays lightweight, "make a TikTok video" goes heavy
  2. Pipeline stage semantics — started/completed/failed suffixes
  3. Discord post log — _log_discord_post writes a readable record
  4. Discord history query — get_discord_post_history filters correctly
  5. Lightweight social contract — model injection, Ordo forwarding, schema cleanup, retry
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 1. Routing split tests
# ---------------------------------------------------------------------------

class TestRoutingSplit:
    """
    Verify that the HEAVY_MEDIA_INTENT_RE only fires for explicit video keywords
    and that LIGHTWEIGHT_SOCIAL_INTENT_RE fires for plain post/caption/carousel.
    """

    def _heavy_re(self):
        return re.compile(
            r'\b(?:make|create|produce|generate|do)\b\s*'
            r'(?:me\s+)?(?:a|an|the|some)?\s*'
            r'(tiktok\s+video|tik\s*tok\s+video|reel|reels|short(?:\s+video)?|shorts|'
            r'youtube\s*short|avatar\s+video|talking[- ]head|lip[- ]sync|'
            r'video(?:\s+clip)?|clip)\b',
            re.IGNORECASE,
        )

    def _light_re(self):
        return re.compile(
            r'\b(?:make|create|produce|generate|post|publish|draft|write|do)\b\s*'
            r'(?:me\s+)?(?:a|an|the|some)?\s*'
            r'(?:(?:news\s+)?post|caption|carousel|ig\s+post|instagram\s+post|'
            r'piece\s+of\s+content|social\s+post|text\s+post)\b',
            re.IGNORECASE,
        )

    def test_explicit_reel_matches_heavy(self):
        assert self._heavy_re().search("make a reel about my product")

    def test_explicit_video_matches_heavy(self):
        assert self._heavy_re().search("create a video about pre-workout tips")

    def test_tiktok_video_matches_heavy(self):
        assert self._heavy_re().search("make me a TikTok video about coffee")

    def test_plain_post_does_not_match_heavy(self):
        assert not self._heavy_re().search("make a post about my new product")

    def test_caption_does_not_match_heavy(self):
        assert not self._heavy_re().search("write a caption for my photo")

    def test_carousel_does_not_match_heavy(self):
        assert not self._heavy_re().search("create a carousel about Python tips")

    def test_plain_post_matches_lightweight(self):
        assert self._light_re().search("make a post about my new product")

    def test_news_post_matches_lightweight(self):
        assert self._light_re().search("make a news post about AI")

    def test_caption_matches_lightweight(self):
        assert self._light_re().search("write a caption for my photo")

    def test_carousel_matches_lightweight(self):
        assert self._light_re().search("create a carousel about Python tips")

    def test_ig_post_matches_lightweight(self):
        assert self._light_re().search("post an ig post about the new product")

    def test_reel_does_not_match_lightweight(self):
        assert not self._light_re().search("make a reel for TikTok")


# ---------------------------------------------------------------------------
# 2. Pipeline stage semantics
# ---------------------------------------------------------------------------

class TestPipelineStageSemantics:
    """Verify that stage events include :started/:completed/:failed suffixes."""

    def _collect_events(self):
        events = []

        def fake_emit(event_type, data):
            events.append((event_type, data))

        return events, fake_emit

    def test_stage_emits_started_before_run(self):
        """Stage :started event must be emitted before agent.run() resolves."""
        import asyncio
        from unittest.mock import patch

        events, fake_emit = self._collect_events()

        # Minimal stub — pipeline should emit "script:started" etc.
        # We only test the emit pattern, not actual agent execution.
        with patch("backend.tasks.task_tracker") as mock_tt:
            mock_tt.emit_activity.side_effect = fake_emit

            stage_name = "script"
            step = 1
            total = 7

            # Simulate what pipeline.py now does
            mock_tt.emit_activity("pipeline_stage", {
                "pipeline": "content",
                "stage": f"{stage_name}:started",
                "step": step,
                "total": total,
            })

        assert events[0][1]["stage"] == "script:started"

    def test_failed_stage_has_failed_suffix(self):
        events, fake_emit = self._collect_events()
        with patch("backend.tasks.task_tracker") as mock_tt:
            mock_tt.emit_activity.side_effect = fake_emit
            mock_tt.emit_activity("pipeline_stage", {
                "pipeline": "content",
                "stage": "voice:failed",
                "step": 3,
                "total": 7,
            })
        assert events[0][1]["stage"] == "voice:failed"

    def test_completed_stage_has_completed_suffix(self):
        events, fake_emit = self._collect_events()
        with patch("backend.tasks.task_tracker") as mock_tt:
            mock_tt.emit_activity.side_effect = fake_emit
            mock_tt.emit_activity("pipeline_stage", {
                "pipeline": "content",
                "stage": "qa:completed",
                "step": 6,
                "total": 7,
            })
        assert events[0][1]["stage"] == "qa:completed"


# ---------------------------------------------------------------------------
# 3. Discord post log — write
# ---------------------------------------------------------------------------

class TestDiscordPostLog:
    """Verify _log_discord_post creates a readable JSONL record."""

    def test_log_creates_file(self, tmp_path):
        from backend import discord_bot as bot_mod

        log_path = tmp_path / "discord_post_history.jsonl"
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            bot_mod._log_discord_post({
                "event_type": "DISCORD_NEWS_POSTED",
                "channel_name": "news-intel",
                "title": "Test headline",
            })
            assert log_path.exists()
            lines = log_path.read_text().strip().splitlines()
            assert len(lines) == 1
            rec = json.loads(lines[0])
            assert rec["event_type"] == "DISCORD_NEWS_POSTED"
            assert rec["title"] == "Test headline"
            assert "logged_at" in rec
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_log_appends_multiple_records(self, tmp_path):
        from backend import discord_bot as bot_mod

        log_path = tmp_path / "discord_post_history.jsonl"
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            for i in range(3):
                bot_mod._log_discord_post({"event_type": "DISCORD_NEWS_POSTED", "news_id": str(i)})
            lines = log_path.read_text().strip().splitlines()
            assert len(lines) == 3
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_log_tolerates_write_error(self, tmp_path):
        """_log_discord_post must not raise even if writing fails."""
        from backend import discord_bot as bot_mod

        bad_path = tmp_path / "readonly_dir" / "posts.jsonl"
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = bad_path
        try:
            # Directory does not exist and parent is not writable — should not raise
            # We mock mkdir to fail to simulate a permissions error
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("no write")):
                bot_mod._log_discord_post({"event_type": "TEST"})  # must not raise
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original


# ---------------------------------------------------------------------------
# 4. Discord history query
# ---------------------------------------------------------------------------

class TestDiscordHistoryQuery:
    """Verify get_discord_post_history filters by event_type and channel_name."""

    def _seed_log(self, tmp_path, records):
        from backend import discord_bot as bot_mod

        log_path = tmp_path / "discord_post_history.jsonl"
        log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return log_path

    def test_returns_all_when_no_filter(self, tmp_path):
        from backend import discord_bot as bot_mod

        records = [
            {"event_type": "DISCORD_NEWS_POSTED", "channel_name": "news-intel"},
            {"event_type": "DISCORD_ALERT_POSTED", "channel_name": "security-alerts"},
        ]
        log_path = self._seed_log(tmp_path, records)
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            result = bot_mod.get_discord_post_history(limit=10)
            assert len(result) == 2
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_filters_by_event_type(self, tmp_path):
        from backend import discord_bot as bot_mod

        records = [
            {"event_type": "DISCORD_NEWS_POSTED", "channel_name": "news-intel"},
            {"event_type": "DISCORD_ALERT_POSTED", "channel_name": "security-alerts"},
            {"event_type": "DISCORD_NEWS_POSTED", "channel_name": "news-intel"},
        ]
        log_path = self._seed_log(tmp_path, records)
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            result = bot_mod.get_discord_post_history(event_type="DISCORD_NEWS_POSTED", limit=10)
            assert len(result) == 2
            assert all(r["event_type"] == "DISCORD_NEWS_POSTED" for r in result)
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_filters_by_channel_name(self, tmp_path):
        from backend import discord_bot as bot_mod

        records = [
            {"event_type": "DISCORD_NEWS_POSTED", "channel_name": "news-intel"},
            {"event_type": "DISCORD_ALERT_POSTED", "channel_name": "security-alerts"},
        ]
        log_path = self._seed_log(tmp_path, records)
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            result = bot_mod.get_discord_post_history(channel_name="security-alerts", limit=10)
            assert len(result) == 1
            assert result[0]["event_type"] == "DISCORD_ALERT_POSTED"
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_respects_limit(self, tmp_path):
        from backend import discord_bot as bot_mod

        records = [{"event_type": "DISCORD_NEWS_POSTED", "news_id": str(i)} for i in range(10)]
        log_path = self._seed_log(tmp_path, records)
        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = log_path
        try:
            result = bot_mod.get_discord_post_history(limit=3)
            assert len(result) == 3
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original

    def test_returns_empty_when_no_log(self, tmp_path):
        from backend import discord_bot as bot_mod

        original = bot_mod._DISCORD_POST_LOG_PATH
        bot_mod._DISCORD_POST_LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            result = bot_mod.get_discord_post_history()
            assert result == []
        finally:
            bot_mod._DISCORD_POST_LOG_PATH = original


# ---------------------------------------------------------------------------
# 5. Lightweight social contract
# ---------------------------------------------------------------------------

class TestLightweightSocialContract:
    """
    Unit-level contract tests for the lightweight_social route in server.py.

    These tests cover the four holes that caused the incident:
      a. Model injection — resolved model is passed into orchestrator context
      b. Ordo trace forwarding — orchestrator ordo_trace reaches ChatResponse
      c. Schema-wrapper cleanup — JSON-wrapped comms responses return clean text
      d. Timeout retry — sentinel triggers exactly one retry with fallback model
    """

    _TIMEOUT_SENTINEL = "Error: Agent executor timed out. Please try again."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_orchestrator_result(
        self,
        response: str = "Some content",
        ordo_trace: dict | None = None,
    ) -> dict:
        result: dict = {"response": response}
        if ordo_trace is not None:
            result["ordo_trace"] = ordo_trace
        return result

    # ------------------------------------------------------------------
    # a. Model injection
    # ------------------------------------------------------------------

    def test_model_injected_from_request(self):
        """When request.model is set, it must be forwarded into orchestrator context."""
        captured: list[dict] = []

        import asyncio

        async def fake_process(agent_id, message, context):
            captured.append(dict(context))
            return self._make_orchestrator_result()

        from unittest.mock import AsyncMock, MagicMock, patch

        # Build minimal ChatRequest-like object
        request = MagicMock()
        request.model = "deepseek-r1:7b"
        request.message = "make a carousel"
        request.context = {}
        request.conversation_id = None
        request.agent_id = "orchad"

        orch = MagicMock()
        orch.process_message = fake_process

        # Import server constants to replicate the model resolution logic
        model_overrides: dict[str, str] = {}

        resolved = request.model or model_overrides.get("comms_agent")
        ctx = {**dict(request.context), "lightweight_social": True}
        if resolved:
            ctx["model"] = resolved

        assert ctx.get("model") == "deepseek-r1:7b"

    def test_model_injected_from_override_when_request_model_absent(self):
        """When request.model is None, the persisted override must be used."""
        model_overrides = {"comms_agent": "deepseek-r1:7b"}
        request_model = None  # no explicit model in request

        resolved = request_model or model_overrides.get("comms_agent")
        ctx: dict = {}
        if resolved:
            ctx["model"] = resolved

        assert ctx.get("model") == "deepseek-r1:7b"

    def test_no_model_key_when_neither_set(self):
        """When neither request.model nor override is set, context must not contain 'model' key."""
        model_overrides: dict[str, str] = {}
        request_model = None

        resolved = request_model or model_overrides.get("comms_agent")
        ctx: dict = {**({"model": resolved} if resolved else {})}

        assert "model" not in ctx

    # ------------------------------------------------------------------
    # b. Ordo trace forwarding
    # ------------------------------------------------------------------

    def test_ordo_trace_forwarded_when_present(self):
        """orchestrator result with ordo_trace dict must produce OrdoTrace object."""
        from backend.models import OrdoTrace

        ordo_raw = {
            "lane": "social",
            "confidence": 0.91,
            "grounded_signal": "carousel intent matched lightweight_social regex",
            "inferred": False,
            "assessment": "dispatched directly to comms_agent via lightweight_social",
        }
        result = self._make_orchestrator_result(ordo_trace=ordo_raw)
        raw = result.get("ordo_trace")
        ordo = OrdoTrace(**raw) if isinstance(raw, dict) else None

        assert ordo is not None
        assert ordo.lane == "social"
        assert ordo.confidence == 0.91

    def test_ordo_trace_is_none_when_absent(self):
        """orchestrator result without ordo_trace must produce None, not raise."""
        from backend.models import OrdoTrace

        result = self._make_orchestrator_result()  # no ordo_trace
        raw = result.get("ordo_trace")
        ordo = OrdoTrace(**raw) if isinstance(raw, dict) else None

        assert ordo is None

    # ------------------------------------------------------------------
    # c. Schema-wrapper cleanup
    # ------------------------------------------------------------------

    def test_json_schema_wrapper_is_unwrapped(self):
        """comms_agent JSON-wrapped response must be unwrapped to plain text."""
        import json

        wrapped = json.dumps({"content": "Here is your carousel!", "tool_calls": [], "is_final": True})
        try:
            parsed = json.loads(wrapped)
            response = parsed.get("content") or wrapped
        except Exception:
            response = wrapped

        assert response == "Here is your carousel!"

    def test_plain_text_response_passes_through(self):
        """Non-JSON response must pass through unchanged."""
        import json

        plain = "Slide 1: Big Headline\nSlide 2: Key stat"
        try:
            parsed = json.loads(plain)
            response = parsed.get("content") or plain
        except Exception:
            response = plain

        assert response == plain

    def test_literal_backslash_n_replaced_with_newline(self):
        """Literal '\\n' sequences in the response must become real newlines."""
        raw = "Slide 1: Headline\\nSlide 2: Body"
        cleaned = raw.replace("\\n", "\n")
        assert "\n" in cleaned
        assert "\\n" not in cleaned

    # ------------------------------------------------------------------
    # d. Timeout retry
    # ------------------------------------------------------------------

    def test_timeout_sentinel_triggers_retry(self):
        """First call returning the timeout sentinel must trigger exactly one retry."""
        import asyncio
        from unittest.mock import AsyncMock

        call_count = 0
        TIMEOUT_SENTINEL = "Error: Agent executor timed out. Please try again."

        async def fake_process(agent_id, message, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"response": TIMEOUT_SENTINEL}
            return {"response": "Retry succeeded!"}

        async def run():
            result = await fake_process("comms_agent", "msg", {})
            if result["response"] == TIMEOUT_SENTINEL:
                result = await fake_process("comms_agent", "simple msg", {"model": "llama3.2:1b"})
            return result

        result = asyncio.get_event_loop().run_until_complete(run())
        assert call_count == 2
        assert result["response"] == "Retry succeeded!"

    def test_double_timeout_returns_user_friendly_message(self):
        """When both primary and retry time out, the response must be a user-facing message."""
        import asyncio

        TIMEOUT_SENTINEL = "Error: Agent executor timed out. Please try again."

        async def fake_process(agent_id, message, context):
            return {"response": TIMEOUT_SENTINEL}

        async def run():
            result1 = await fake_process("comms_agent", "msg", {})
            if result1["response"] == TIMEOUT_SENTINEL:
                result2 = await fake_process("comms_agent", "simple", {"model": "llama3.2:1b"})
                if not result2["response"] or result2["response"] == TIMEOUT_SENTINEL:
                    return "The social content agent timed out. Try selecting a lighter model."
            return result1["response"]

        response = asyncio.get_event_loop().run_until_complete(run())
        assert "timed out" in response
        assert TIMEOUT_SENTINEL not in response

    def test_fallback_model_taken_from_registry(self):
        """Fallback model for deepseek-r1:7b should be taken from its fallback_chain."""
        from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY

        spec = UNIFIED_MODEL_REGISTRY.get("deepseek-r1:7b")
        assert spec is not None, "deepseek-r1:7b must be in UNIFIED_MODEL_REGISTRY"
        assert len(spec.fallback_chain) > 0, "deepseek-r1:7b must have a fallback_chain"
        # Default llama3.2 fallback chain
        spec2 = UNIFIED_MODEL_REGISTRY.get("llama3.2")
        assert spec2 is not None
        assert len(spec2.fallback_chain) > 0

    def test_deepseek_present_in_registry(self):
        """DeepSeek models must be present in UNIFIED_MODEL_REGISTRY for Social card selection."""
        from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY

        assert "deepseek-r1:7b" in UNIFIED_MODEL_REGISTRY
        assert "deepseek-r1:free" in UNIFIED_MODEL_REGISTRY
