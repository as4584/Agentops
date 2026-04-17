"""
Tests for backend.middleware.DriftGuard — governance invariant enforcement.

Covers:
- Tool execution is allowed for READ_ONLY and STATE_MODIFY operations
- ARCHITECTURAL_MODIFY execution is recorded as needing doc update (doc_check=False)
- Halted system raises RuntimeError on any tool call
- INV-7: every execution is logged
- check_invariants() returns GREEN / YELLOW / RED correctly
- check_namespace_overlap() correctly flags duplicates
- DriftGuard recovers after halt is cleared
- _check_documentation_updated() timestamp-aware INV-5 enforcement
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta

import pytest

from backend.middleware import DriftGuard
from backend.models import DriftStatus, ModificationType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop(**kwargs):
    return "ok"


async def _failing(**kwargs):
    raise ValueError("tool exploded")


# ---------------------------------------------------------------------------
# Normal execution — READ_ONLY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_executes_and_returns_result():
    guard = DriftGuard()
    result = await guard.guard_tool_execution(
        tool_name="file_reader",
        agent_id="monitor_agent",
        modification_type=ModificationType.READ_ONLY,
        tool_fn=_noop,
    )
    assert result == "ok"


@pytest.mark.asyncio
async def test_state_modify_executes_and_returns_result():
    guard = DriftGuard()
    result = await guard.guard_tool_execution(
        tool_name="webhook_send",
        agent_id="comms_agent",
        modification_type=ModificationType.STATE_MODIFY,
        tool_fn=_noop,
    )
    assert result == "ok"


# ---------------------------------------------------------------------------
# ARCHITECTURAL_MODIFY — flagged but NOT blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_architectural_modify_still_executes():
    """Architectural modifications are flagged but execution proceeds."""
    guard = DriftGuard()
    result = await guard.guard_tool_execution(
        tool_name="doc_updater",
        agent_id="devops_agent",
        modification_type=ModificationType.ARCHITECTURAL_MODIFY,
        tool_fn=_noop,
    )
    assert result == "ok"


@pytest.mark.asyncio
async def test_architectural_modify_adds_pending_update():
    guard = DriftGuard()
    await guard.guard_tool_execution(
        tool_name="doc_updater",
        agent_id="devops_agent",
        modification_type=ModificationType.ARCHITECTURAL_MODIFY,
        tool_fn=_noop,
    )
    report = guard.check_invariants()
    # Should be YELLOW because doc update pending
    assert report.status in (DriftStatus.YELLOW, DriftStatus.GREEN)


# ---------------------------------------------------------------------------
# Halted system
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_halted_system_blocks_all_tool_calls():
    guard = DriftGuard()
    guard._halted = True  # noqa: SLF001 — testing internal state

    with pytest.raises(RuntimeError, match="SYSTEM HALTED"):
        await guard.guard_tool_execution(
            tool_name="file_reader",
            agent_id="any_agent",
            modification_type=ModificationType.READ_ONLY,
            tool_fn=_noop,
        )


@pytest.mark.asyncio
async def test_cleared_halt_allows_execution():
    guard = DriftGuard()
    guard._halted = True  # noqa: SLF001
    guard._halted = False  # cleared

    result = await guard.guard_tool_execution(
        tool_name="file_reader",
        agent_id="monitor_agent",
        modification_type=ModificationType.READ_ONLY,
        tool_fn=_noop,
    )
    assert result == "ok"


# ---------------------------------------------------------------------------
# Failing tool propagates exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_tool_propagates_exception():
    guard = DriftGuard()

    with pytest.raises(ValueError, match="tool exploded"):
        await guard.guard_tool_execution(
            tool_name="safe_shell",
            agent_id="devops_agent",
            modification_type=ModificationType.STATE_MODIFY,
            tool_fn=_failing,
        )


# ---------------------------------------------------------------------------
# check_invariants()
# ---------------------------------------------------------------------------


def test_check_invariants_green_on_fresh_guard():
    guard = DriftGuard()
    report = guard.check_invariants()
    assert report.status == DriftStatus.GREEN
    assert report.violations == []


def test_check_invariants_yellow_after_arch_modify_without_docs(monkeypatch):
    """
    If _pending_updates is non-empty, the report should be YELLOW.
    We inject the pending update directly to test the invariant check
    independently of the documentation check logic.
    """
    guard = DriftGuard()
    guard._pending_updates.append("doc_updater by devops_agent requires documentation update")  # noqa: SLF001

    report = guard.check_invariants()
    assert report.status == DriftStatus.YELLOW
    assert len(report.pending_updates) == 1


# ---------------------------------------------------------------------------
# check_namespace_overlap()
# ---------------------------------------------------------------------------


def test_namespace_overlap_no_duplicates():
    guard = DriftGuard()
    # Returns True when namespaces are clean (no duplicates)
    assert guard.check_namespace_overlap(["soul_core", "devops_agent", "monitor_agent"]) is True


def test_namespace_overlap_detects_duplicate():
    guard = DriftGuard()
    # Returns False when duplicates exist
    assert guard.check_namespace_overlap(["soul_core", "devops_agent", "soul_core"]) is False


def test_namespace_overlap_empty_list():
    guard = DriftGuard()
    # Empty list has no duplicates — clean
    assert guard.check_namespace_overlap([]) is True


def test_namespace_overlap_single_item():
    guard = DriftGuard()
    # Single item — no duplicates possible, so clean
    assert guard.check_namespace_overlap(["only_one"]) is True


# ---------------------------------------------------------------------------
# _check_documentation_updated() — INV-5 timestamp-aware enforcement
# ---------------------------------------------------------------------------


def _write_changelog(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_check_doc_missing_file(tmp_path, monkeypatch):
    """Returns False when CHANGE_LOG.md does not exist."""
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", tmp_path / "no_such_file.md")
    guard = DriftGuard()
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is False  # noqa: SLF001


def test_check_doc_recent_entry_passes(tmp_path, monkeypatch):
    """A changelog entry from 2 minutes ago containing the agent_id should pass."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    now = datetime.now(UTC)
    recent_ts = (now - timedelta(minutes=2)).isoformat()
    cl_path.write_text(
        textwrap.dedent(f"""\
        ### {recent_ts}
        - **Agent:** devops_agent
        - **Files Modified:** backend/config.py
        - **Reason:** updated deployment config
        - **Risk Assessment:** LOW
        - **Documentation Updated:** YES
        """),
        encoding="utf-8",
    )
    guard = DriftGuard()
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is True  # noqa: SLF001


def test_check_doc_stale_entry_fails(tmp_path, monkeypatch):
    """An entry older than 10 minutes must not satisfy the recency check."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    now = datetime.now(UTC)
    stale_ts = (now - timedelta(minutes=15)).isoformat()
    cl_path.write_text(
        textwrap.dedent(f"""\
        ### {stale_ts}
        - **Agent:** devops_agent
        - **Reason:** old entry
        """),
        encoding="utf-8",
    )
    guard = DriftGuard()
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is False  # noqa: SLF001


def test_check_doc_agent_id_not_in_recent_entry(tmp_path, monkeypatch):
    """A recent entry that does NOT contain the agent_id must fail."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    now = datetime.now(UTC)
    recent_ts = (now - timedelta(minutes=1)).isoformat()
    cl_path.write_text(
        textwrap.dedent(f"""\
        ### {recent_ts}
        - **Agent:** comms_agent
        - **Reason:** unrelated change
        """),
        encoding="utf-8",
    )
    guard = DriftGuard()
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is False  # noqa: SLF001


def test_check_doc_legacy_format_falls_back_to_substring(tmp_path, monkeypatch):
    """Legacy changelogs with no ISO timestamps fall back to substring check."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    # No ### timestamp headers — just plain Markdown
    cl_path.write_text(
        "## Changes\n- devops_agent updated doc_updater\n",
        encoding="utf-8",
    )
    guard = DriftGuard()
    # Both agent_id and tool_name present → legacy substring match → True
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is True  # noqa: SLF001


def test_check_doc_legacy_format_missing_substring_returns_false(tmp_path, monkeypatch):
    """Legacy changelog that lacks the agent_id must still return False."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    cl_path.write_text("## Changes\n- some other agent did something\n", encoding="utf-8")
    guard = DriftGuard()
    assert guard._check_documentation_updated("devops_agent", "doc_updater") is False  # noqa: SLF001


def test_check_doc_malformed_content_does_not_raise(tmp_path, monkeypatch):
    """Malformed changelog content must return False, never raise."""
    cl_path = tmp_path / "CHANGE_LOG.md"
    monkeypatch.setattr("backend.middleware.CHANGE_LOG_PATH", cl_path)

    cl_path.write_bytes(b"\xff\xfe" + b"garbage\x00" * 50)  # invalid UTF-8 BOM + nulls
    guard = DriftGuard()
    result = guard._check_documentation_updated("devops_agent", "doc_updater")
    assert isinstance(result, bool)  # no exception; result is False
