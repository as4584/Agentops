"""
Tests for backend/gateway/ratelimit.py — MemoryRateLimiter token-bucket logic.

No external dependencies required.
"""

from __future__ import annotations

import time

import pytest

from backend.gateway.ratelimit import BucketState, MemoryRateLimiter, get_rate_limiter


@pytest.fixture()
def limiter() -> MemoryRateLimiter:
    return MemoryRateLimiter()


# ---------------------------------------------------------------------------
# BucketState
# ---------------------------------------------------------------------------


class TestBucketState:
    def test_default_construction(self):
        b = BucketState()
        assert b.rpm_window == []
        assert b.tpm_tokens == 0.0
        assert b.tpd_tokens == 0.0
        assert b.tpd_day == ""
        assert b.usd_hour == 0.0


# ---------------------------------------------------------------------------
# RPM
# ---------------------------------------------------------------------------


class TestCheckRPM:
    def test_first_request_allowed(self, limiter):
        allowed, remaining = limiter.check_rpm("k1", limit=10)
        assert allowed is True
        assert remaining == 9

    def test_unlimited_rpm(self, limiter):
        allowed, remaining = limiter.check_rpm("k1", limit=0)
        assert allowed is True
        assert remaining == 999_999

    def test_limit_at_boundary(self, limiter):
        for _ in range(5):
            allowed, _ = limiter.check_rpm("k2", limit=5)
        # 5 requests consumed
        allowed, remaining = limiter.check_rpm("k2", limit=5)
        assert allowed is False
        assert remaining == 0

    def test_remaining_decrements(self, limiter):
        _, r1 = limiter.check_rpm("k3", limit=10)
        _, r2 = limiter.check_rpm("k3", limit=10)
        assert r2 < r1

    def test_different_keys_isolated(self, limiter):
        for _ in range(3):
            limiter.check_rpm("k_a", limit=3)
        allowed_a, _ = limiter.check_rpm("k_a", limit=3)
        allowed_b, _ = limiter.check_rpm("k_b", limit=3)
        assert allowed_a is False
        assert allowed_b is True

    def test_reset_clears_state(self, limiter):
        for _ in range(3):
            limiter.check_rpm("k_reset", limit=3)
        limiter.reset("k_reset")
        allowed, _ = limiter.check_rpm("k_reset", limit=3)
        assert allowed is True

    def test_reset_nonexistent_key_is_noop(self, limiter):
        limiter.reset("nonexistent_key")  # should not raise


# ---------------------------------------------------------------------------
# TPM
# ---------------------------------------------------------------------------


class TestCheckTPM:
    def test_within_limit(self, limiter):
        allowed, remaining = limiter.check_tpm("k1", tokens=100, limit=1000)
        assert allowed is True
        assert remaining == 900

    def test_unlimited_tpm(self, limiter):
        allowed, remaining = limiter.check_tpm("k1", tokens=999999, limit=0)
        assert allowed is True
        assert remaining == 999_999

    def test_over_limit(self, limiter):
        limiter.check_tpm("k2", tokens=900, limit=1000)
        allowed, remaining = limiter.check_tpm("k2", tokens=200, limit=1000)
        assert allowed is False
        assert remaining == 100

    def test_exact_limit_boundary(self, limiter):
        allowed, remaining = limiter.check_tpm("k3", tokens=1000, limit=1000)
        assert allowed is True
        assert remaining == 0

    def test_tpm_window_resets(self, limiter, monkeypatch):
        # Fill up the bucket
        limiter.check_tpm("k4", tokens=1000, limit=1000)
        allowed_before, _ = limiter.check_tpm("k4", tokens=1, limit=1000)
        assert allowed_before is False

        # Simulate 61 seconds passing
        future = time.time() + 61
        monkeypatch.setattr(time, "time", lambda: future)
        allowed_after, _ = limiter.check_tpm("k4", tokens=1, limit=1000)
        assert allowed_after is True


# ---------------------------------------------------------------------------
# TPD
# ---------------------------------------------------------------------------


class TestCheckTPD:
    def test_within_daily_limit(self, limiter):
        allowed, remaining = limiter.check_tpd("k1", tokens=500, limit=10000)
        assert allowed is True
        assert remaining == 9500

    def test_unlimited_tpd(self, limiter):
        allowed, remaining = limiter.check_tpd("k1", tokens=1_000_000, limit=0)
        assert allowed is True

    def test_over_daily_limit(self, limiter):
        limiter.check_tpd("k2", tokens=9900, limit=10000)
        allowed, remaining = limiter.check_tpd("k2", tokens=200, limit=10000)
        assert allowed is False
        assert remaining == 100

    def test_day_rollover_resets_bucket(self, limiter):
        # Fill bucket for today
        limiter.check_tpd("k3", tokens=9000, limit=10000)
        allowed_same_day, _ = limiter.check_tpd("k3", tokens=9000, limit=10000)
        assert allowed_same_day is False

        # Manually simulate a day rollover by setting bucket's day to yesterday
        bucket = limiter._buckets["k3"]
        bucket.tpd_day = "1970-01-01"  # past date; next check will reset
        allowed_new_day, _ = limiter.check_tpd("k3", tokens=9000, limit=10000)
        assert allowed_new_day is True

    def test_get_tpd_used_initial_zero(self, limiter):
        assert limiter.get_tpd_used("brand_new_key") == 0.0

    def test_get_tpd_used_after_consumption(self, limiter):
        limiter.check_tpd("k5", tokens=300, limit=10000)
        assert limiter.get_tpd_used("k5") == 300.0


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------


class TestRecordCost:
    def test_within_budget(self, limiter):
        within, remaining = limiter.record_cost("k1", usd=0.10, hourly_limit=1.00)
        assert within is True
        assert abs(remaining - 0.90) < 0.001

    def test_unlimited_budget(self, limiter):
        within, remaining = limiter.record_cost("k1", usd=9999, hourly_limit=0)
        assert within is True

    def test_over_budget(self, limiter):
        limiter.record_cost("k2", usd=0.90, hourly_limit=1.00)
        within, remaining = limiter.record_cost("k2", usd=0.20, hourly_limit=1.00)
        assert within is False

    def test_hourly_window_resets(self, limiter, monkeypatch):
        limiter.record_cost("k3", usd=0.90, hourly_limit=1.00)
        future = time.time() + 3601
        monkeypatch.setattr(time, "time", lambda: future)
        within, _ = limiter.record_cost("k3", usd=0.90, hourly_limit=1.00)
        assert within is True


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


class TestGetRateLimiter:
    def test_returns_memory_limiter_by_default(self, monkeypatch):
        import backend.gateway.ratelimit as rl_mod

        # Reset singleton to force re-creation
        monkeypatch.setattr(rl_mod, "_limiter", None)
        monkeypatch.setattr(rl_mod, "GATEWAY_RATE_LIMIT_BACKEND", "memory")
        lim = get_rate_limiter()
        assert isinstance(lim, MemoryRateLimiter)

    def test_returns_same_singleton(self, monkeypatch):
        import backend.gateway.ratelimit as rl_mod

        monkeypatch.setattr(rl_mod, "_limiter", None)
        lim1 = get_rate_limiter()
        lim2 = get_rate_limiter()
        assert lim1 is lim2
