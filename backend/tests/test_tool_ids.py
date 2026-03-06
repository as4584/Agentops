"""
Contract tests for Tool ID Normalization (backend/utils/tool_ids.py).
======================================================================
Covers:
- Property tests: every sanitized ID matches ^[a-zA-Z0-9_-]{1,64}$
- Round-trip tests: canonical → sanitized → canonical identity
- Collision tests: 10k parallel registrations, zero ID collisions
- Determinism tests: same input always produces same output
- Edge cases: empty string, overly long IDs, Unicode, special chars

Run with::

    pytest backend/tests/test_tool_ids.py -v
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from backend.utils.tool_ids import (
    ToolIdRegistry,
    is_valid_tool_id,
    make_tool_call_id,
    sanitize_tool_id,
    validate_tool_definitions,
)
from backend.utils.tool_validator import ToolValidator, _levenshtein, validator_for_agent

# ---------------------------------------------------------------------------
# Pattern constant (mirrored from tool_ids.py for clarity in assertions)
# ---------------------------------------------------------------------------
VALID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def is_valid(tool_id: str) -> bool:
    return bool(VALID_PATTERN.match(tool_id))


# ===========================================================================
# 1. sanitize_tool_id — property tests
# ===========================================================================

class TestSanitizeToolId:
    """Every output must satisfy the OpenAI/Copilot pattern."""

    @pytest.mark.parametrize("raw", [
        "planner.step:1",
        "agent_call/2",
        "tool-call-1.3",
        "model:ollama-qwen",
        "safe_shell",
        "file_reader",
        "a" * 100,           # overly long
        "!@#$%^&*()",        # all invalid chars
        "hello world",       # space
        "üñïcödé",           # Unicode
        "step__double",      # double underscore (valid — collapsed)
        "UPPER_CASE",        # uppercase (valid, preserved)
        "mix.of/all:types!", # multiple different separators
    ])
    def test_output_matches_pattern(self, raw: str) -> None:
        result = sanitize_tool_id(raw)
        assert is_valid(result), (
            f"sanitize_tool_id({raw!r}) = {result!r} does not match valid pattern"
        )

    def test_empty_string_returns_valid(self) -> None:
        result = sanitize_tool_id("")
        assert is_valid(result), f"empty input gave invalid output: {result!r}"

    def test_deterministic(self) -> None:
        raw = "planner.step:1"
        assert sanitize_tool_id(raw) == sanitize_tool_id(raw)

    def test_known_transformations(self) -> None:
        assert sanitize_tool_id("planner.step:1") == "planner_step_1"
        assert sanitize_tool_id("agent_call/2") == "agent_call_2"
        assert sanitize_tool_id("model:ollama-qwen") == "model_ollama-qwen"
        assert sanitize_tool_id("tool-call-1.3") == "tool-call-1_3"

    def test_max_length(self) -> None:
        long_id = "a" * 200
        result = sanitize_tool_id(long_id)
        assert len(result) <= 64, f"result too long: {len(result)}"
        assert is_valid(result)

    def test_hyphen_preserved(self) -> None:
        """Hyphens are valid in the OpenAI pattern and must be preserved."""
        result = sanitize_tool_id("safe-shell-v2")
        assert result == "safe-shell-v2"

    def test_multiple_consecutive_separators_collapsed(self) -> None:
        result = sanitize_tool_id("a...b:::c///d")
        assert "__" not in result, f"consecutive underscores in {result!r}"

    def test_unicode_replaced(self) -> None:
        result = sanitize_tool_id("cré-ation")
        assert is_valid(result)
        assert "r" in result.lower()  # "cr" preserved

    def test_already_valid_unchanged(self) -> None:
        valid = "safe_shell"
        assert sanitize_tool_id(valid) == valid


# ===========================================================================
# 2. is_valid_tool_id
# ===========================================================================

class TestIsValidToolId:
    def test_valid_ids(self) -> None:
        assert is_valid_tool_id("safe_shell")
        assert is_valid_tool_id("a")
        assert is_valid_tool_id("a" * 64)
        assert is_valid_tool_id("tool-name_v2")

    def test_invalid_ids(self) -> None:
        assert not is_valid_tool_id("")
        assert not is_valid_tool_id("a" * 65)
        assert not is_valid_tool_id("tool.name")
        assert not is_valid_tool_id("tool:name")
        assert not is_valid_tool_id("tool/name")
        assert not is_valid_tool_id("tool name")


# ===========================================================================
# 3. ToolIdRegistry — round-trip + collision tests
# ===========================================================================

class TestToolIdRegistry:
    """Round-trip and collision-free guarantees."""

    def test_register_returns_valid_id(self) -> None:
        reg = ToolIdRegistry()
        result = reg.register("planner.step:1")
        assert is_valid(result)

    def test_round_trip(self) -> None:
        reg = ToolIdRegistry()
        canonical = "agent_call/2"
        sanitized = reg.register(canonical)
        assert reg.get_canonical(sanitized) == canonical

    def test_idempotent_registration(self) -> None:
        reg = ToolIdRegistry()
        first = reg.register("model:ollama-qwen")
        second = reg.register("model:ollama-qwen")
        assert first == second

    def test_collision_handling(self) -> None:
        """Two different canonicals that map to the same sanitized form get distinct IDs."""
        reg = ToolIdRegistry()
        # Both "planner.step:1" and "planner_step:1" sanitize to "planner_step_1"
        id_a = reg.register("planner.step:1")
        id_b = reg.register("planner_step:1")
        assert id_a != id_b, "Collision: two distinct canonicals got the same sanitized ID"
        # Both must still be valid
        assert is_valid(id_a)
        assert is_valid(id_b)
        # Round-trip for both
        assert reg.get_canonical(id_a) == "planner.step:1"
        assert reg.get_canonical(id_b) == "planner_step:1"

    def test_unknown_sanitized_returns_none(self) -> None:
        reg = ToolIdRegistry()
        assert reg.get_canonical("nonexistent") is None

    def test_unknown_canonical_returns_none(self) -> None:
        reg = ToolIdRegistry()
        assert reg.get_sanitized("nonexistent") is None

    def test_all_canonical(self) -> None:
        reg = ToolIdRegistry()
        reg.register("a:b")
        reg.register("c/d")
        assert set(reg.all_canonical()) == {"a:b", "c/d"}

    def test_all_sanitized_are_valid(self) -> None:
        reg = ToolIdRegistry()
        for raw in ["planner.step:1", "agent_call/2", "model:ollama-qwen", "safe_shell"]:
            reg.register(raw)
        for sanitized in reg.all_sanitized():
            assert is_valid(sanitized), f"Invalid sanitized ID in registry: {sanitized!r}"

    def test_clear(self) -> None:
        reg = ToolIdRegistry()
        reg.register("a:b")
        reg.clear()
        assert reg.all_canonical() == []

    # ── sanitize_tool_definitions ────────────────────────────────────────

    def test_sanitize_tool_definitions(self) -> None:
        reg = ToolIdRegistry()
        tools = [
            {"type": "function", "function": {"name": "safe.shell", "description": "..."}},
            {"type": "function", "function": {"name": "file/reader", "description": "..."}},
        ]
        sanitized, reg2 = reg.sanitize_tool_definitions(tools)
        assert reg2 is reg
        for tool in sanitized:
            assert is_valid(tool["function"]["name"])

    def test_desanitize_tool_calls(self) -> None:
        reg = ToolIdRegistry()
        reg.register("safe.shell")
        santized_name = reg.get_sanitized("safe.shell")
        tool_calls = [{"function": {"name": santized_name, "arguments": "{}"}}]
        result = reg.desanitize_tool_calls(tool_calls)
        assert result[0]["function"]["name"] == "safe.shell"

    # ── Thread-safety / collision test (10k registrations) ──────────────

    def test_10k_parallel_registrations_no_collisions(self) -> None:
        """
        10 000 unique canonical IDs registered concurrently must each get a unique
        sanitized ID, and every sanitized ID must satisfy the valid pattern.
        """
        reg = ToolIdRegistry()
        n = 10_000
        # Generate IDs that are intentionally similar to stress-test collision handling.
        canonicals = [f"agent.task:{i}" for i in range(n)]

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(reg.register, c) for c in canonicals]
            sanitized_ids = [f.result() for f in as_completed(futures)]

        # All sanitized IDs must be valid.
        invalid = [sid for sid in sanitized_ids if not is_valid(sid)]
        assert not invalid, f"{len(invalid)} sanitized IDs are invalid: {invalid[:5]}"

        # No two different canonicals should share a sanitized ID.
        all_sanitized = reg.all_sanitized()
        assert len(all_sanitized) == n, (
            f"Expected {n} unique sanitized IDs, got {len(all_sanitized)}"
        )
        assert len(set(all_sanitized)) == n, "Duplicate sanitized IDs detected"


# ===========================================================================
# 4. make_tool_call_id
# ===========================================================================

class TestMakeToolCallId:
    def test_basic(self) -> None:
        result = make_tool_call_id("planner", "step", 1)
        assert is_valid(result)
        assert result == "planner_step_1"

    def test_with_context(self) -> None:
        result = make_tool_call_id("agent", "call", 2, "ctx")
        assert is_valid(result)
        assert result == "agent_call_ctx_2"

    def test_model_ollama(self) -> None:
        result = make_tool_call_id("model", "ollama-qwen", 5)
        assert is_valid(result)
        assert result == "model_ollama-qwen_5"

    def test_deterministic(self) -> None:
        a = make_tool_call_id("agent", "tool", 7, "ctx")
        b = make_tool_call_id("agent", "tool", 7, "ctx")
        assert a == b

    def test_sequence_creates_unique_ids(self) -> None:
        ids = {make_tool_call_id("agent", "tool", i) for i in range(100)}
        assert len(ids) == 100


# ===========================================================================
# 5. validate_tool_definitions
# ===========================================================================

class TestValidateToolDefinitions:
    def test_valid_tools_no_violations(self) -> None:
        tools = [
            {"type": "function", "function": {"name": "safe_shell"}},
            {"type": "function", "function": {"name": "file-reader"}},
        ]
        assert validate_tool_definitions(tools) == []

    def test_invalid_name_reported(self) -> None:
        tools = [{"type": "function", "function": {"name": "bad.name"}}]
        violations = validate_tool_definitions(tools)
        assert len(violations) == 1
        assert "bad.name" in violations[0]

    def test_missing_name_reported(self) -> None:
        tools = [{"type": "function", "function": {}}]
        violations = validate_tool_definitions(tools)
        assert len(violations) == 1
        assert "missing" in violations[0]

    def test_empty_list(self) -> None:
        assert validate_tool_definitions([]) == []


# ===========================================================================
# 6. ToolValidator — hallucination prevention
# ===========================================================================

class TestToolValidator:
    def test_valid_tool_passes(self) -> None:
        v = ToolValidator(["safe_shell", "file_reader"])
        result = v.validate("safe_shell")
        assert result.valid
        assert result.canonical_name == "safe_shell"

    def test_unknown_tool_fails(self) -> None:
        v = ToolValidator(["safe_shell", "file_reader"])
        result = v.validate("hack_shell")
        assert not result.valid

    def test_fuzzy_suggestion_within_threshold(self) -> None:
        v = ToolValidator(["safe_shell", "file_reader"])
        result = v.validate("file_raeder")   # 2 edits away
        assert not result.valid
        assert "file_reader" in result.suggestions

    def test_no_suggestion_beyond_threshold(self) -> None:
        v = ToolValidator(["safe_shell"])
        result = v.validate("completely_different_tool_xyz")
        assert not result.valid
        assert result.suggestions == []

    def test_error_message_lists_available_tools(self) -> None:
        v = ToolValidator(["safe_shell", "file_reader"])
        result = v.validate("unknown_tool")
        assert "safe_shell" in result.error_message
        assert "file_reader" in result.error_message

    def test_error_message_did_you_mean(self) -> None:
        v = ToolValidator(["safe_shell"])
        result = v.validate("safe_shel")   # 1 edit
        assert "Did you mean" in result.error_message
        assert "safe_shell" in result.error_message

    def test_update_allowed(self) -> None:
        v = ToolValidator(["safe_shell"])
        v.update_allowed(["file_reader"])
        assert v.validate("file_reader").valid
        assert not v.validate("safe_shell").valid

    def test_add_tool(self) -> None:
        v = ToolValidator(["safe_shell"])
        v.add_tool("doc_updater")
        assert v.validate("doc_updater").valid

    def test_is_allowed(self) -> None:
        v = ToolValidator(["safe_shell"])
        assert v.is_allowed("safe_shell")
        assert not v.is_allowed("unknown")

    def test_validate_batch(self) -> None:
        v = ToolValidator(["safe_shell", "file_reader"])
        results = v.validate_batch(["safe_shell", "unknown", "file_reader"])
        assert results[0].valid
        assert not results[1].valid
        assert results[2].valid

    def test_validator_for_agent(self) -> None:
        v = validator_for_agent(["safe_shell", "file_reader", "doc_updater"])
        assert v.validate("doc_updater").valid
        assert not v.validate("hack_shell").valid


# ===========================================================================
# 7. Levenshtein distance unit tests
# ===========================================================================

class TestLevenshtein:
    def test_identical(self) -> None:
        assert _levenshtein("abc", "abc") == 0

    def test_insertion(self) -> None:
        assert _levenshtein("abc", "abcd") == 1

    def test_deletion(self) -> None:
        assert _levenshtein("abcd", "abc") == 1

    def test_substitution(self) -> None:
        assert _levenshtein("abc", "axc") == 1

    def test_empty_strings(self) -> None:
        assert _levenshtein("", "") == 0
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("", "abc") == 3

    def test_known_distance(self) -> None:
        # "kitten" → "sitting": 3 edits
        assert _levenshtein("kitten", "sitting") == 3


# ===========================================================================
# 8. Integration: sanitization pipeline (canonical → API → response)
# ===========================================================================

class TestSanitizationPipeline:
    """
    Simulate the full round-trip:
      1. Register canonical tool names.
      2. Sanitize tool definitions (as sent to OpenAI API).
      3. Simulate API response with sanitized tool_calls.
      4. Desanitize response → canonical names restored.
    """

    def test_full_round_trip_pipeline(self) -> None:
        reg = ToolIdRegistry()
        validator = ToolValidator(["planner.step:1", "agent_call/2"])

        # Step 1: tool definitions with invalid names (as they exist internally).
        raw_tools = [
            {"type": "function", "function": {"name": "planner.step:1", "description": "Plan next step"}},
            {"type": "function", "function": {"name": "agent_call/2",  "description": "Delegate to agent"}},
        ]

        # Step 2: sanitize before API call.
        sanitized_tools, reg = reg.sanitize_tool_definitions(raw_tools)

        # All sanitized names must be valid.
        for tool in sanitized_tools:
            assert is_valid(tool["function"]["name"])

        # Step 3: simulate API response calling back with sanitized names.
        api_tool_calls = [
            {"function": {"name": tool["function"]["name"], "arguments": "{}"}}
            for tool in sanitized_tools
        ]

        # Step 4: desanitize → back to canonical.
        canonical_tool_calls = reg.desanitize_tool_calls(api_tool_calls)
        canonical_names = {tc["function"]["name"] for tc in canonical_tool_calls}

        assert canonical_names == {"planner.step:1", "agent_call/2"}

    def test_hallucinated_tool_blocked(self) -> None:
        """LLM hallucinating a tool name it was never given must be caught."""
        validator = ToolValidator(["safe_shell", "file_reader"])
        hallucinated = "list_all_files_on_disk"
        result = validator.validate(hallucinated)
        assert not result.valid
        assert "safe_shell" in result.error_message

    def test_known_invalid_raw_ids_all_sanitize(self) -> None:
        """All IDs that previously caused 400 errors must now sanitize correctly."""
        problematic_ids = [
            "planner.step:1",
            "agent_call/2",
            "tool-call-1.3",
            "model:ollama-qwen",
            "model:gpt-4o",
            "copilot:chat",
            "openai:gpt-4o",
            "step (with spaces)",
            "step\ttab",
            "step\nnewline",
        ]
        for raw in problematic_ids:
            result = sanitize_tool_id(raw)
            assert is_valid(result), (
                f"Previously-problematic ID {raw!r} → {result!r} still invalid"
            )
