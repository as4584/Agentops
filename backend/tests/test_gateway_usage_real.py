"""Real tests for UsageTracker — backend/gateway/usage.py.

These tests hit an actual SQLite DB (tmp_path) with no mocks.
They verify the accumulation logic, quota enforcement, and ranking
queries that would catch real regressions in cost tracking.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backend.gateway.usage import UsageTracker

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracker(tmp_path: Path) -> UsageTracker:
    """Fresh UsageTracker backed by an isolated temp SQLite file."""
    return UsageTracker(db_path=tmp_path / "test_usage.db")


# ---------------------------------------------------------------------------
# record() accumulation
# ---------------------------------------------------------------------------


def test_record_accumulates_requests(tracker: UsageTracker) -> None:
    """Calling record() three times should give requests=3, not 1."""
    for _ in range(3):
        tracker.record("key1", "gpt-4o", "openai", tokens_in=100, tokens_out=50, cost_usd=0.01)

    summary = tracker.get_daily_usage("key1", days=1)
    assert len(summary) == 1
    assert summary[0].requests == 3


def test_record_accumulates_tokens(tracker: UsageTracker) -> None:
    """Token counts should sum across calls, not be overwritten."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=100, tokens_out=50, cost_usd=0.01)
    tracker.record("key1", "gpt-4o", "openai", tokens_in=200, tokens_out=80, cost_usd=0.02)

    tin, tout = tracker.get_today_tokens("key1")
    assert tin == 300
    assert tout == 130


def test_record_writes_to_both_tables(tracker: UsageTracker) -> None:
    """A single record() call must upsert into BOTH hourly and daily rollup tables."""
    tracker.record("key_abc", "llama3.2", "ollama", tokens_in=10, tokens_out=5, cost_usd=0.0)

    # Daily table check via get_daily_usage
    daily = tracker.get_daily_usage("key_abc", days=1)
    assert len(daily) == 1, "Daily table should have one row"

    # Hourly table check via direct query (internal conn)
    row = tracker._conn.execute("SELECT COUNT(*) FROM gateway_usage_hourly WHERE key_id = 'key_abc'").fetchone()
    assert row[0] == 1, "Hourly table should also have a row"


def test_record_separate_models_create_separate_rows(tracker: UsageTracker) -> None:
    """Different model names should produce separate rows, not merge."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=50, tokens_out=20, cost_usd=0.01)
    tracker.record("key1", "gpt-3.5-turbo", "openai", tokens_in=50, tokens_out=20, cost_usd=0.001)

    daily = tracker.get_daily_usage("key1", days=1)
    assert len(daily) == 2


# ---------------------------------------------------------------------------
# get_today_cost / get_monthly_cost
# ---------------------------------------------------------------------------


def test_get_today_cost_returns_zero_when_no_records(tracker: UsageTracker) -> None:
    assert tracker.get_today_cost("no_such_key") == 0.0


def test_get_today_cost_sums_across_models(tracker: UsageTracker) -> None:
    tracker.record("key1", "model-a", "p", tokens_in=0, tokens_out=0, cost_usd=0.10)
    tracker.record("key1", "model-b", "p", tokens_in=0, tokens_out=0, cost_usd=0.05)

    cost = tracker.get_today_cost("key1")
    assert abs(cost - 0.15) < 1e-9


def test_get_monthly_cost_includes_today(tracker: UsageTracker) -> None:
    tracker.record("key1", "model-a", "p", tokens_in=0, tokens_out=0, cost_usd=1.23)

    monthly = tracker.get_monthly_cost("key1")
    assert monthly >= 1.23


# ---------------------------------------------------------------------------
# check_quota — blocking and warning behaviour
# ---------------------------------------------------------------------------


def test_check_quota_passes_when_under_limit(tracker: UsageTracker) -> None:
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=5.0)

    allowed, reason = tracker.check_quota("key1", daily_usd_limit=10.0, monthly_usd_limit=50.0)
    assert allowed is True
    assert reason == ""


def test_check_quota_blocks_at_daily_100pct(tracker: UsageTracker) -> None:
    """Cost equals 100 % of limit — must block."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=10.0)

    allowed, reason = tracker.check_quota("key1", daily_usd_limit=10.0, monthly_usd_limit=100.0)
    assert allowed is False
    assert "daily quota exceeded" in reason.lower()


def test_check_quota_blocks_above_daily_limit(tracker: UsageTracker) -> None:
    """Cost exceeds daily limit — must block."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=10.01)

    allowed, reason = tracker.check_quota("key1", daily_usd_limit=10.0, monthly_usd_limit=100.0)
    assert allowed is False


def test_check_quota_warns_at_daily_80pct(tracker: UsageTracker, caplog: pytest.LogCaptureFixture) -> None:
    """At 80 % we let the request through but emit a WARNING."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=8.0)

    with caplog.at_level(logging.WARNING, logger="gateway.usage"):
        allowed, reason = tracker.check_quota("key1", daily_usd_limit=10.0, monthly_usd_limit=100.0)

    assert allowed is True
    assert reason == ""
    assert any("80" in r.message or "%" in r.message for r in caplog.records)


def test_check_quota_blocks_at_monthly_100pct(tracker: UsageTracker) -> None:
    """Monthly cost at limit — block regardless of daily headroom."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=50.0)

    allowed, reason = tracker.check_quota("key1", daily_usd_limit=100.0, monthly_usd_limit=50.0)
    assert allowed is False
    assert "monthly quota exceeded" in reason.lower()


def test_check_quota_with_zero_limits_always_passes(tracker: UsageTracker) -> None:
    """Limits of 0.0 mean 'unlimited' — should never block."""
    tracker.record("key1", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=9999.0)

    allowed, _ = tracker.check_quota("key1", daily_usd_limit=0.0, monthly_usd_limit=0.0)
    assert allowed is True


# ---------------------------------------------------------------------------
# top_models — ranking query
# ---------------------------------------------------------------------------


def test_top_models_returns_empty_for_unknown_key(tracker: UsageTracker) -> None:
    result = tracker.top_models("ghost_key", days=7)
    assert result == []


def test_top_models_ranks_by_cost_descending(tracker: UsageTracker) -> None:
    tracker.record("k", "cheap-model", "p", tokens_in=100, tokens_out=50, cost_usd=0.001)
    tracker.record("k", "expensive-model", "p", tokens_in=100, tokens_out=50, cost_usd=1.50)
    tracker.record("k", "mid-model", "p", tokens_in=100, tokens_out=50, cost_usd=0.25)

    top = tracker.top_models("k", days=7)
    assert top[0]["model"] == "expensive-model"
    assert top[1]["model"] == "mid-model"
    assert top[2]["model"] == "cheap-model"


def test_top_models_aggregates_multiple_records_for_same_model(tracker: UsageTracker) -> None:
    """Multiple record() calls for the same model should appear as one row."""
    for _ in range(4):
        tracker.record("k", "gpt-4o", "openai", tokens_in=100, tokens_out=50, cost_usd=0.10)

    top = tracker.top_models("k", days=7)
    assert len(top) == 1
    assert top[0]["requests"] == 4
    assert abs(top[0]["cost_usd"] - 0.40) < 0.001


def test_top_models_respects_days_window(tracker: UsageTracker) -> None:
    """Records are bounded by the days parameter — but since we can't backdate easily,
    at minimum verify that current-day records ARE included."""
    tracker.record("k", "gpt-4o", "openai", tokens_in=0, tokens_out=0, cost_usd=0.50)

    top = tracker.top_models("k", days=1)
    assert len(top) == 1
    assert top[0]["model"] == "gpt-4o"
