"""Deterministic tests for backend.orchestrator.lex_router.

All Ollama/network calls are mocked. Tests validate:
  - keyword fallback routing
  - LLM response parsing
  - full resolve_agent pipeline (C→LLM→keyword)
  - red-line blocking
  - edge cases (empty messages, bad JSON, unknown agents)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestrator.lex_router import (
    GENERAL_AUTO_ROUTE_AGENTS,
    VALID_AGENTS,
    _keyword_route,
    _parse_lex_response,
    _specialist_route,
    resolve_agent,
)

# ── keyword routing ─────────────────────────────────────────────────


class TestKeywordRoute:
    def test_deploy_routes_to_devops(self):
        assert _keyword_route("deploy the new service") == "devops_agent"

    def test_ci_cd_routes_to_devops(self):
        assert _keyword_route("fix the CI pipeline") == "devops_agent"

    def test_health_routes_to_monitor(self):
        assert _keyword_route("check health status of all services") == "monitor_agent"

    def test_restart_routes_to_self_healer(self):
        assert _keyword_route("restart the crashed worker") == "self_healer_agent"

    def test_code_review_routes_correctly(self):
        assert _keyword_route("review this diff for code quality") == "code_review_agent"

    def test_security_scan_routes_correctly(self):
        assert _keyword_route("scan for secrets and vulnerabilities") == "security_agent"

    def test_database_query_routes_to_data(self):
        assert _keyword_route("query the customer database schema") == "data_agent"

    def test_webhook_routes_to_comms(self):
        assert _keyword_route("send webhook notification to slack") == "comms_agent"

    def test_customer_support_routes_to_cs(self):
        assert _keyword_route("handle this customer complaint ticket") == "cs_agent"

    def test_infra_routes_to_it(self):
        assert _keyword_route("check cpu and memory usage") == "it_agent"

    def test_docs_route_to_knowledge(self):
        assert _keyword_route("search the documentation for API reference") == "knowledge_agent"

    def test_soul_keywords(self):
        assert _keyword_route("reflect on our mission and purpose") == "soul_core"

    def test_empty_message_defaults_to_soul(self):
        assert _keyword_route("") == "soul_core"

    def test_gibberish_defaults_to_soul(self):
        assert _keyword_route("asdfghjkl qwerty") == "soul_core"

    def test_multiple_keyword_matches_picks_highest(self):
        # "deploy pipeline build" has 3 devops keywords
        result = _keyword_route("deploy the pipeline and build it")
        assert result == "devops_agent"

    def test_mixed_keywords_picks_dominant(self):
        # "scan for secrets" = 2 security, "check health" = 1 monitor
        result = _keyword_route("scan for secrets and check health")
        assert result in VALID_AGENTS

    def test_all_returned_agents_are_valid(self):
        messages = [
            "deploy",
            "health",
            "restart",
            "review",
            "scan",
            "query",
            "webhook",
            "customer",
            "cpu",
            "docs",
            "reflect",
            "",
        ]
        for msg in messages:
            agent = _keyword_route(msg)
            assert agent in VALID_AGENTS, f"Invalid agent '{agent}' for '{msg}'"


# ── LLM response parsing ────────────────────────────────────────────


class TestParseResponse:
    def test_valid_json(self):
        text = '{"agent_id": "devops_agent", "confidence": 0.95, "reasoning": "deploy task"}'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "devops_agent"
        assert result["confidence"] == 0.95

    def test_json_embedded_in_text(self):
        text = 'Here is my analysis:\n{"agent_id": "security_agent", "confidence": 0.9}\nDone.'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "security_agent"

    def test_empty_string_returns_none(self):
        assert _parse_lex_response("") is None

    def test_garbage_text_returns_none(self):
        assert _parse_lex_response("I don't know what to do") is None

    def test_invalid_json_returns_none(self):
        assert _parse_lex_response("{agent_id: bad}") is None

    def test_json_with_whitespace(self):
        text = '  \n  {"agent_id": "cs_agent", "confidence": 0.8}  \n  '
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "cs_agent"

    def test_partial_json_returns_none(self):
        assert _parse_lex_response('{"agent_id": "devops_') is None


# ── resolve_agent pipeline ───────────────────────────────────────────


@pytest.mark.asyncio
class TestResolveAgent:
    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "keyword")
    async def test_keyword_mode_skips_llm(self):
        result = await resolve_agent("deploy the service")
        assert result["agent_id"] == "devops_agent"
        assert result["method"] == "keyword"

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_hybrid_falls_back_to_keyword_when_ollama_down(self):
        with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
            mock_lex.return_value = ("", 0.0)  # LLM failed
            result = await resolve_agent("scan for vulnerabilities")
            assert result["agent_id"] == "security_agent"
            assert result["method"] == "keyword"
            mock_lex.assert_called_once()

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_hybrid_uses_llm_when_available(self):
        with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
            mock_lex.return_value = ("devops_agent", 0.95)
            result = await resolve_agent("deploy to production")
            assert result["agent_id"] == "devops_agent"
            assert result["method"] == "lex"
            assert result["confidence"] == 0.95

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "lex")
    async def test_lex_mode_falls_back_to_soul_not_keyword(self):
        with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
            mock_lex.return_value = ("", 0.0)
            result = await resolve_agent("something weird")
            assert result["agent_id"] == "soul_core"
            assert result["method"] == "lex_fallback"

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_c_fast_router_preempts_llm(self):
        mock_fast = MagicMock()
        mock_fast.available = True
        mock_fast.check_red_line.return_value = False
        mock_fast.route.return_value = {"agent_id": "devops_agent", "confidence": 0.92, "matched": True}
        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):
            result = await resolve_agent("deploy now")
            assert result["method"] == "c_fast"
            assert result["agent_id"] == "devops_agent"

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_c_red_line_blocks_dangerous_input(self):
        mock_fast = MagicMock()
        mock_fast.available = True
        mock_fast.check_red_line.return_value = True
        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):
            result = await resolve_agent("rm -rf / --no-preserve-root")
            assert result["blocked"] is True
            assert result["agent_id"] == "soul_core"
            assert result["method"] == "c_red_line"

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_c_low_confidence_falls_through_to_llm(self):
        mock_fast = MagicMock()
        mock_fast.available = True
        mock_fast.check_red_line.return_value = False
        mock_fast.route.return_value = {"agent_id": "monitor_agent", "confidence": 0.5, "matched": True}
        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):
            with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
                mock_lex.return_value = ("it_agent", 0.88)
                result = await resolve_agent("something about infrastructure")
                assert result["method"] == "lex"  # C confidence too low, fell through

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "keyword")
    async def test_resolve_returns_valid_agent_always(self):
        messages = [
            "hello",
            "deploy",
            "scan",
            "restart",
            "review code",
            "check cpu",
            "query db",
            "",
            "asdf",
            "reflect on goals",
        ]
        for msg in messages:
            result = await resolve_agent(msg)
            assert result["agent_id"] in VALID_AGENTS, f"Invalid for '{msg}': {result}"
            assert "method" in result
            assert "confidence" in result


# ── Keyword routing: boundary & edge cases ───────────────────────────


class TestKeywordRouteBoundary:
    """Tests for ambiguous, overlapping, and adversarial keyword inputs."""

    def test_case_insensitive(self):
        assert _keyword_route("DEPLOY THE SERVICE") == "devops_agent"
        assert _keyword_route("ReStArT tHe PrOcEsS") == "self_healer_agent"

    def test_mixed_keywords_highest_score_wins(self):
        # 3 devops keywords vs 1 security
        result = _keyword_route("deploy the CI pipeline build with a secret")
        assert result == "devops_agent"

    def test_two_agent_tie_returns_one(self):
        # 1 keyword each for monitor and it — result depends on iteration
        result = _keyword_route("health check on cpu")
        assert result in VALID_AGENTS

    def test_very_long_message(self):
        long_msg = "deploy " * 5000
        result = _keyword_route(long_msg)
        assert result == "devops_agent"

    def test_unicode_message(self):
        result = _keyword_route("部署新服务到生产环境 deploy")
        assert result == "devops_agent"

    def test_newlines_and_tabs(self):
        result = _keyword_route("please\n\trestart\n\tthe\ncrashed\nprocess")
        assert result == "self_healer_agent"

    def test_punctuation_in_keywords(self):
        assert _keyword_route("deploy!!! now!!!") == "devops_agent"

    def test_partial_keyword_no_match(self):
        # "dep" is not "deploy", "sec" is not "security"
        result = _keyword_route("dep sec")
        assert result == "soul_core"

    def test_general_agents_reachable(self):
        """The existing 12-agent keyword baseline must stay intact."""
        reachable = set()
        test_msgs = [
            "deploy the build via docker",  # devops
            "monitor health alert status",  # monitor
            "restart crashed broken process",  # self_healer
            "review diff refactor code quality",  # code_review
            "security audit scan vulnerability",  # security
            "database query sql schema",  # data
            "webhook notify incident slack",  # comms
            "customer support ticket complaint",  # cs
            "cpu memory disk network process",  # it
            "search docs knowledge documentation",  # knowledge
            "reflect goal trust purpose soul",  # soul_core
            "ocr extract text from pdf document",  # ocr_agent
        ]
        for msg in test_msgs:
            reachable.add(_keyword_route(msg))
        assert reachable == GENERAL_AUTO_ROUTE_AGENTS

    def test_empty_string_returns_soul_core(self):
        assert _keyword_route("") == "soul_core"

    def test_only_stopwords(self):
        assert _keyword_route("the a is of and to in") == "soul_core"

    def test_substring_match_inside_word(self):
        # "building" contains "build" — should still match devops
        result = _keyword_route("the building is nice")
        assert result == "devops_agent"

    def test_multiword_keyword_match(self):
        # "code quality" is a multi-word keyword
        assert _keyword_route("check code quality please") == "code_review_agent"

    def test_help_desk_multiword(self):
        assert _keyword_route("call the help desk") == "cs_agent"


# ── LLM response parsing: more edge cases ────────────────────────────


class TestParseResponseEdgeCases:
    def test_nested_json_picks_first(self):
        text = '{"agent_id": "it_agent", "confidence": 0.7} extra {"agent_id": "wrong"}'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "it_agent"

    def test_json_with_extra_fields(self):
        text = '{"agent_id": "data_agent", "confidence": 0.9, "reasoning": "db", "extra": true}'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "data_agent"

    def test_json_with_numbers_as_strings(self):
        text = '{"agent_id": "soul_core", "confidence": "0.85"}'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["confidence"] == "0.85"

    def test_only_braces(self):
        assert _parse_lex_response("{}") == {}

    def test_markdown_code_block_json(self):
        text = '```json\n{"agent_id": "devops_agent"}\n```'
        result = _parse_lex_response(text)
        assert result is not None
        assert result["agent_id"] == "devops_agent"

    def test_multiple_newlines_before_json(self):
        text = '\n\n\n{"agent_id": "cs_agent", "confidence": 0.8}\n\n'
        result = _parse_lex_response(text)
        assert result is not None

    def test_json_with_unicode(self):
        text = '{"agent_id": "comms_agent", "reasoning": "通知"}'
        result = _parse_lex_response(text)
        assert result is not None


# ── resolve_agent: advanced pipeline ─────────────────────────────────


@pytest.mark.asyncio
class TestResolveAgentAdvanced:
    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_llm_returns_invalid_agent_accepted_as_is(self):
        """Router currently trusts the LLM response even for unknown agent IDs."""
        with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
            mock_lex.return_value = ("nonexistent_agent", 0.9)
            result = await resolve_agent("deploy the service")
            # LLM result is accepted — no validation of agent_id
            assert result["agent_id"] == "nonexistent_agent"
            assert result["method"] == "lex"

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_llm_timeout_propagates_exception(self):
        with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
            mock_lex.side_effect = Exception("Connection timeout")
            with pytest.raises(Exception, match="Connection timeout"):
                await resolve_agent("restart process")

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_c_router_not_matched_proceeds_to_llm(self):
        mock_fast = MagicMock()
        mock_fast.available = True
        mock_fast.check_red_line.return_value = False
        mock_fast.route.return_value = {"agent_id": "", "confidence": 0.0, "matched": False}
        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):
            with patch("backend.orchestrator.lex_router._lex_route", new_callable=AsyncMock) as mock_lex:
                mock_lex.return_value = ("soul_core", 0.92)
                result = await resolve_agent("what is the meaning of this project")
                assert result["method"] == "lex"
                assert result["agent_id"] == "soul_core"

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "keyword")
    async def test_general_agents_reachable_in_keyword_mode(self):
        """The 12 general agents remain reachable in keyword-only mode."""
        reachable = set()
        test_msgs = [
            "deploy build docker",
            "monitor health alert",
            "restart crashed",
            "review diff lint",
            "security audit scan",
            "database query sql",
            "webhook notify",
            "customer support ticket",
            "cpu disk network",
            "search docs knowledge",
            "reflect goal soul",
            "ocr extract text from pdf",
        ]
        for msg in test_msgs:
            result = await resolve_agent(msg)
            reachable.add(result["agent_id"])
        assert reachable == GENERAL_AUTO_ROUTE_AGENTS

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_specialist_agent_routes_are_explicit_and_stable(self):
        specialist_messages = {
            "prompt_engineer": "rewrite this prompt for claude sonnet",
            "token_optimizer": "reduce token count and context window budget",
            "curriculum_advisor": "what is the bseai course sequence and prerequisite path",
            "vocabulary_coach": "define this term from the spell book with precise vocabulary",
            "career_intel": "analyze this job description and identify the skills gap",
            "accreditation_advisor": "build an ABET accreditation matrix for these outcomes",
            "pedagogy_agent": "design learning objectives using bloom's taxonomy",
            "higgsfield_agent": "create a higgsfield soul id and start video generation",
            "higgsfield_research_agent": "research higgsfield failures and recommend prompt changes",
        }

        for expected_agent, message in specialist_messages.items():
            result = await resolve_agent(message)
            assert result["agent_id"] == expected_agent
            assert result["method"] == "specialist_keyword"

    async def test_valid_agents_matches_full_registry(self):
        assert GENERAL_AUTO_ROUTE_AGENTS < VALID_AGENTS
        assert len(VALID_AGENTS) == 21

    @patch("backend.orchestrator.lex_router._fast_router", None)
    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "keyword")
    async def test_result_always_has_required_keys(self):
        msgs = ["deploy", "restart", "reflect", "", "asdf"]
        for msg in msgs:
            result = await resolve_agent(msg)
            assert "agent_id" in result
            assert "method" in result
            assert "confidence" in result
            assert isinstance(result["confidence"], (int, float))

    @patch("backend.orchestrator.lex_router.LLM_ROUTER_MODE", "hybrid")
    async def test_c_red_line_includes_reason(self):
        mock_fast = MagicMock()
        mock_fast.available = True
        mock_fast.check_red_line.return_value = True
        with patch("backend.orchestrator.lex_router._fast_router", mock_fast):
            result = await resolve_agent("DROP TABLE users;")
            assert result["blocked"] is True
            assert "reason" in result


# ── _specialist_route: natural-language trigger coverage ─────────────


class TestSpecialistRoute:
    """Covers both the canonical exact phrases and the new natural-language triggers."""

    # ── prompt_engineer ──────────────────────────────────────────────

    def test_exact_prompt_engineer_phrase(self):
        assert _specialist_route("prompt engineer") == "prompt_engineer"

    def test_rewrite_this_prompt(self):
        assert _specialist_route("rewrite this prompt for gpt-4") == "prompt_engineer"

    def test_optimize_this_prompt(self):
        assert _specialist_route("optimize this prompt to be shorter") == "prompt_engineer"

    def test_make_this_prompt_better(self):
        assert _specialist_route("can you make this prompt better?") == "prompt_engineer"

    def test_improve_my_prompt(self):
        assert _specialist_route("improve my prompt for claude") == "prompt_engineer"

    def test_help_me_write_a_prompt(self):
        assert _specialist_route("help me write a prompt for summarisation") == "prompt_engineer"

    def test_write_a_better_prompt(self):
        assert _specialist_route("write a better prompt for this task") == "prompt_engineer"

    def test_craft_a_prompt(self):
        assert _specialist_route("craft a prompt for extracting entities") == "prompt_engineer"

    def test_better_prompt_for(self):
        assert _specialist_route("I need a better prompt for classification") == "prompt_engineer"

    # ── token_optimizer ──────────────────────────────────────────────

    def test_exact_token_optimizer_phrase(self):
        assert _specialist_route("token optimizer") == "token_optimizer"

    def test_compress_this_prompt(self):
        assert _specialist_route("compress this prompt") == "token_optimizer"

    def test_reduce_token_count(self):
        assert _specialist_route("how do I reduce token count in my prompt?") == "token_optimizer"

    def test_too_many_tokens(self):
        assert _specialist_route("too many tokens in this request") == "token_optimizer"

    def test_reduce_tokens(self):
        assert _specialist_route("I need to reduce tokens") == "token_optimizer"

    def test_shorten_the_prompt(self):
        assert _specialist_route("please shorten the prompt to fit the window") == "token_optimizer"

    def test_trim_my_prompt(self):
        assert _specialist_route("trim my prompt please") == "token_optimizer"

    def test_prompt_too_long(self):
        assert _specialist_route("the prompt too long for the model") == "token_optimizer"

    def test_context_limit(self):
        assert _specialist_route("hitting the context limit again") == "token_optimizer"

    # ── non-matching messages return empty string ────────────────────

    def test_unrelated_message_returns_empty(self):
        assert _specialist_route("deploy the service to production") == ""

    def test_empty_message_returns_empty(self):
        assert _specialist_route("") == ""

    def test_case_insensitive_match(self):
        assert _specialist_route("MAKE THIS PROMPT BETTER") == "prompt_engineer"
