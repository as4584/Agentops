"""
Tests for scripts/repair_patterns.json — validates that every entry is
well-formed and that pattern regexes compile and match their expected
targets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_PATTERNS_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "repair_patterns.json"
_VALID_SEVERITIES = {"medium", "high", "critical"}
_VALID_BOOLEANS = {True, False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load() -> dict:
    return json.loads(_PATTERNS_PATH.read_text())


def _patterns() -> list[dict]:
    return _load()["patterns"]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestRepairPatternsSchema:
    """Every entry must satisfy the schema contract."""

    def test_file_exists(self) -> None:
        assert _PATTERNS_PATH.exists(), f"repair_patterns.json not found at {_PATTERNS_PATH}"

    def test_version_present(self) -> None:
        data = _load()
        assert "version" in data, "Top-level 'version' key missing"
        assert isinstance(data["version"], str), "'version' must be a string"

    def test_patterns_is_list(self) -> None:
        data = _load()
        assert isinstance(data.get("patterns"), list), "'patterns' must be a list"
        assert len(data["patterns"]) > 0, "'patterns' must not be empty"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_required_fields(self, pat: dict) -> None:
        for field in ("id", "description", "detect", "safe", "severity", "added_sprint", "rationale"):
            assert field in pat, f"Pattern '{pat.get('id', '?')}' missing required field '{field}'"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_id_is_slug(self, pat: dict) -> None:
        assert re.match(r"^[a-z][a-z0-9_]*$", pat["id"]), f"Pattern id '{pat['id']}' must be lowercase snake_case"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_severity_valid(self, pat: dict) -> None:
        assert pat["severity"] in _VALID_SEVERITIES, f"Pattern '{pat['id']}' has unknown severity '{pat['severity']}'"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_safe_is_bool(self, pat: dict) -> None:
        assert pat["safe"] in _VALID_BOOLEANS, f"Pattern '{pat['id']}' has non-boolean 'safe': {pat['safe']!r}"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_fix_cmd_type(self, pat: dict) -> None:
        fix = pat.get("fix_cmd")
        assert fix is None or isinstance(fix, list), f"Pattern '{pat['id']}' fix_cmd must be null or a list"
        if isinstance(fix, list):
            assert all(isinstance(s, str) for s in fix), f"Pattern '{pat['id']}' fix_cmd entries must be strings"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_safe_with_no_fix_cmd(self, pat: dict) -> None:
        """safe=true patterns should have a fix_cmd (otherwise they can't be auto-repaired)."""
        if pat["safe"]:
            assert pat.get("fix_cmd"), f"Pattern '{pat['id']}' is safe=true but has no fix_cmd"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_added_sprint_is_int(self, pat: dict) -> None:
        assert isinstance(pat["added_sprint"], int), f"Pattern '{pat['id']}' added_sprint must be an integer"

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_rationale_non_empty(self, pat: dict) -> None:
        assert pat["rationale"].strip(), f"Pattern '{pat['id']}' rationale must not be empty"

    def test_no_duplicate_ids(self) -> None:
        ids = [p["id"] for p in _patterns()]
        assert len(ids) == len(set(ids)), f"Duplicate pattern ids: {[i for i in ids if ids.count(i) > 1]}"


# ---------------------------------------------------------------------------
# Regex compilation tests
# ---------------------------------------------------------------------------


class TestRepairPatternRegexes:
    """Every detect regex must compile and match the documented example."""

    @pytest.mark.parametrize("pat", _patterns(), ids=[p["id"] for p in _patterns()])
    def test_detect_compiles(self, pat: dict) -> None:
        try:
            re.compile(pat["detect"], re.MULTILINE)
        except re.error as exc:
            pytest.fail(f"Pattern '{pat['id']}' detect regex does not compile: {exc}")

    # ── Per-pattern canary strings that MUST match ──────────────────────

    @pytest.mark.parametrize(
        "pattern_id,canary",
        [
            ("legacy_kvs_import", "from backend.knowledge import KnowledgeVectorStore"),
            ("legacy_kvs_import", "import KnowledgeVectorStore"),
            ("legacy_v1_runtime_call", "result = process_message_v1(msg)"),
            ("regex_tool_call", "[TOOL:safe_shell]"),
            ("datetime_utcfromtimestamp", "datetime.utcfromtimestamp(ts)"),
            ("asyncmock_bare", "mock_fn = AsyncMock()"),
            ("router_hardcoded_agent_list", "VALID_AGENTS = ['soul_core', 'devops_agent']"),
            ("gitnexus_ungated_call", "result = gitnexus.run('query', data)"),
            ("gitnexus_ungated_call", "out = gitnexus_client.call(method)"),
            ("raw_dict_process_message", "await orchestrator.process_message({'msg': 'hi'})"),
            ("json_knowledge_rebuild", "rebuild_knowledge_index()"),
            ("json_knowledge_rebuild", "build_json_index(path)"),
        ],
    )
    def test_canary_matches(self, pattern_id: str, canary: str) -> None:
        pattern = next((p for p in _patterns() if p["id"] == pattern_id), None)
        assert pattern is not None, f"Pattern '{pattern_id}' not found in repair_patterns.json"
        rx = re.compile(pattern["detect"], re.MULTILINE)
        assert rx.search(canary), f"Pattern '{pattern_id}' detect regex did not match canary: {canary!r}"

    # ── Per-pattern strings that must NOT match (avoid false positives) ─

    @pytest.mark.parametrize(
        "pattern_id,non_match",
        [
            ("legacy_kvs_import", "from backend.knowledge.context_assembler import ContextAssembler"),
            ("legacy_v1_runtime_call", "result = await orchestrator.process_message(req)"),
            ("router_hardcoded_agent_list", "VALID_AGENTS = set(ALL_AGENT_DEFINITIONS.keys())"),
            ("raw_dict_process_message", "await orchestrator.process_message(ChatRequest(msg='hi'))"),
        ],
    )
    def test_non_match(self, pattern_id: str, non_match: str) -> None:
        pattern = next((p for p in _patterns() if p["id"] == pattern_id), None)
        assert pattern is not None, f"Pattern '{pattern_id}' not found"
        rx = re.compile(pattern["detect"], re.MULTILINE)
        assert not rx.search(non_match), f"Pattern '{pattern_id}' falsely matched non-target: {non_match!r}"


# ---------------------------------------------------------------------------
# Fix script existence tests
# ---------------------------------------------------------------------------


class TestFixScriptExists:
    """Every safe pattern's fix_cmd must reference an existing script."""

    _SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

    @pytest.mark.parametrize(
        "pat",
        [p for p in _patterns() if p["safe"] and p.get("fix_cmd")],
        ids=[p["id"] for p in _patterns() if p["safe"] and p.get("fix_cmd")],
    )
    def test_fix_script_exists(self, pat: dict) -> None:
        cmd = pat["fix_cmd"]
        assert cmd, f"Pattern '{pat['id']}' has safe=true but no fix_cmd"
        # The first element after 'python' is the script path
        if cmd[0] == "python":
            script_path = self._SCRIPTS_DIR.parent / cmd[1]
            assert script_path.exists(), f"Pattern '{pat['id']}' fix_cmd references non-existent script: {cmd[1]}"
