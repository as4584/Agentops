"""
Rate limit and ACL tests.
"""

from __future__ import annotations

import pytest

from backend.gateway.ratelimit import MemoryRateLimiter
from backend.gateway.acl import ModelACL, TIER_MODELS, ModelTier


class TestMemoryRateLimiter:
    def test_rpm_allows_within_limit(self):
        lim = MemoryRateLimiter()
        for _ in range(5):
            ok, rem = lim.check_rpm("key1", limit=10)
            assert ok

    def test_rpm_blocks_over_limit(self):
        lim = MemoryRateLimiter()
        for _ in range(10):
            lim.check_rpm("key1", limit=10)
        ok, rem = lim.check_rpm("key1", limit=10)
        assert not ok
        assert rem == 0

    def test_rpm_zero_means_unlimited(self):
        lim = MemoryRateLimiter()
        for _ in range(1000):
            ok, _ = lim.check_rpm("key1", limit=0)
            assert ok

    def test_tpm_allows_within_limit(self):
        lim = MemoryRateLimiter()
        ok, rem = lim.check_tpm("key1", tokens=100, limit=1000)
        assert ok
        assert rem == 900

    def test_tpm_blocks_over_limit(self):
        lim = MemoryRateLimiter()
        lim.check_tpm("key1", tokens=900, limit=1000)
        ok, rem = lim.check_tpm("key1", tokens=200, limit=1000)
        assert not ok

    def test_tpd_resets_daily(self):
        lim = MemoryRateLimiter()
        lim.check_tpd("key1", tokens=500, limit=1000)
        # Simulate day rollover by manipulating bucket
        from datetime import date, timedelta
        past = (date.today() - timedelta(days=1)).isoformat()
        lim._buckets["key1"].tpd_day = past
        ok, _ = lim.check_tpd("key1", tokens=800, limit=1000)
        assert ok  # reset on new day

    def test_isolation_between_keys(self):
        lim = MemoryRateLimiter()
        for _ in range(10):
            lim.check_rpm("key1", limit=10)
        ok, _ = lim.check_rpm("key2", limit=10)
        assert ok  # key2 unaffected

    def test_reset(self):
        lim = MemoryRateLimiter()
        for _ in range(10):
            lim.check_rpm("key1", limit=10)
        lim.reset("key1")
        ok, _ = lim.check_rpm("key1", limit=10)
        assert ok


class TestModelACL:
    @pytest.fixture
    def acl(self, tmp_path):
        return ModelACL(db_path=tmp_path / "acl_test.db")

    def test_default_deny(self, acl):
        assert not acl.is_allowed("new-key", "gpt-4o")
        assert not acl.is_allowed("new-key", "llama3.2")

    def test_exact_grant(self, acl):
        acl.grant("k1", ["gpt-4o"])
        assert acl.is_allowed("k1", "gpt-4o")
        assert not acl.is_allowed("k1", "gpt-4o-mini")

    def test_wildcard_grant(self, acl):
        acl.grant("k1", ["ollama/*"])
        assert acl.is_allowed("k1", "ollama/llama3.2")
        assert not acl.is_allowed("k1", "gpt-4o")

    def test_wildcard_all(self, acl):
        acl.grant("k1", ["*"])
        assert acl.is_allowed("k1", "anything/anycmodel")

    def test_tier_budget_grants_ollama(self, acl):
        acl.grant_tier("k1", ModelTier.BUDGET)
        assert acl.is_allowed("k1", "llama3.2")
        assert acl.is_allowed("k1", "mistral:7b")

    def test_tier_premium_grants_cloud(self, acl):
        acl.grant_tier("k1", ModelTier.PREMIUM)
        assert acl.is_allowed("k1", "gpt-4o")
        assert acl.is_allowed("k1", "claude-sonnet")

    def test_revoke(self, acl):
        acl.grant("k1", ["gpt-4o", "gpt-4o-mini"])
        acl.revoke("k1", ["gpt-4o"])
        assert not acl.is_allowed("k1", "gpt-4o")
        assert acl.is_allowed("k1", "gpt-4o-mini")

    def test_revoke_all(self, acl):
        acl.grant("k1", ["gpt-4o", "llama3.2"])
        acl.revoke_all("k1")
        assert not acl.is_allowed("k1", "gpt-4o")
        assert not acl.is_allowed("k1", "llama3.2")

    def test_filter_allowed(self, acl):
        acl.grant("k1", ["gpt-4o", "llama3.2"])
        all_models = ["gpt-4o", "gpt-4o-mini", "llama3.2", "claude-sonnet"]
        allowed = acl.filter_allowed_models("k1", all_models)
        assert set(allowed) == {"gpt-4o", "llama3.2"}
