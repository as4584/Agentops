"""
Gateway Tests — Unit tests for auth, encryption, rate limits, ACL, and audit.
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

import pytest

from backend.gateway.auth import APIKeyManager, generate_api_key, _hash_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_mgr(tmp_path):
    """APIKeyManager backed by a temp SQLite database."""
    return APIKeyManager(db_path=tmp_path / "test_keys.db")


# ---------------------------------------------------------------------------
# Key Generation
# ---------------------------------------------------------------------------

class TestKeyGeneration:
    def test_format(self):
        raw, prefix = generate_api_key()
        assert raw.startswith("agp_sk_")
        assert len(raw.split("_")) == 4
        assert prefix in raw

    def test_uniqueness(self):
        keys = {generate_api_key()[0] for _ in range(100)}
        assert len(keys) == 100  # no collisions

    def test_hash_deterministic(self):
        raw, _ = generate_api_key()
        h1 = _hash_key(raw)
        h2 = _hash_key(raw)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# APIKeyManager
# ---------------------------------------------------------------------------

class TestAPIKeyManager:
    def test_create_and_validate(self, tmp_mgr):
        raw, key = tmp_mgr.create_key("test-key", owner="alice")
        assert raw.startswith("agp_sk_")
        validated = tmp_mgr.validate_key(raw)
        assert validated is not None
        assert validated.key_id == key.key_id
        assert validated.owner == "alice"

    def test_invalid_key_returns_none(self, tmp_mgr):
        result = tmp_mgr.validate_key("agp_sk_notreal_abc123")
        assert result is None

    def test_disabled_key_rejected(self, tmp_mgr):
        raw, key = tmp_mgr.create_key("disabled-test")
        tmp_mgr.revoke_key(key.key_id)
        assert tmp_mgr.validate_key(raw) is None

    def test_expired_key_rejected(self, tmp_mgr):
        raw, key = tmp_mgr.create_key("expiry-test")
        # Set expiry in the past
        tmp_mgr.update_key(key.key_id, expires_at=time.time() - 1)
        assert tmp_mgr.validate_key(raw) is None

    def test_prefix_returns_none_for_bad_prefix(self, tmp_mgr):
        assert tmp_mgr.validate_key("wrong_prefix_abc") is None

    def test_scopes_default(self, tmp_mgr):
        _, key = tmp_mgr.create_key("scope-test")
        assert "chat" in key.scopes
        assert "models" in key.scopes

    def test_custom_scopes(self, tmp_mgr):
        _, key = tmp_mgr.create_key("admin-key", scopes={"chat", "admin"})
        assert "admin" in key.scopes

    def test_key_rotation(self, tmp_mgr):
        raw1, key = tmp_mgr.create_key("rotate-test")
        # Rotate
        result = tmp_mgr.rotate_key(key.key_id)
        assert result is not None
        raw2, _ = result
        # Both keys should work
        assert tmp_mgr.validate_key(raw1) is not None
        assert tmp_mgr.validate_key(raw2) is not None
        # Promote
        tmp_mgr.promote_rotation(key.key_id)
        # Old key should be rejected; new key works
        assert tmp_mgr.validate_key(raw1) is None
        assert tmp_mgr.validate_key(raw2) is not None

    def test_get_by_id(self, tmp_mgr):
        _, key = tmp_mgr.create_key("lookup-test")
        found = tmp_mgr.get_by_id(key.key_id)
        assert found is not None
        assert found.name == "lookup-test"

    def test_list_keys(self, tmp_mgr):
        for i in range(3):
            tmp_mgr.create_key(f"key-{i}")
        assert len(tmp_mgr.list_keys()) == 3

    def test_hard_delete(self, tmp_mgr):
        raw, key = tmp_mgr.create_key("delete-test")
        tmp_mgr.delete_key(key.key_id)
        assert tmp_mgr.get_by_id(key.key_id) is None
        assert tmp_mgr.validate_key(raw) is None
