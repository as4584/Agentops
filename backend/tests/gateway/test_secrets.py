"""
Encryption tests — SecretsVault AES-256-GCM.
"""

from __future__ import annotations

import pytest

from backend.gateway.secrets import SecretsVault, SecretStr, _encrypt, _decrypt


@pytest.fixture
def vault(tmp_path):
    return SecretsVault(path=tmp_path / "test.enc", master_key="testkeyfortests1234567890123456")


class TestSecretStr:
    def test_masks_in_repr(self):
        s = SecretStr("super-secret")
        assert "super-secret" not in repr(s)
        assert "**" in repr(s)

    def test_masks_in_str(self):
        s = SecretStr("super-secret")
        assert "super-secret" not in str(s)

    def test_get_value(self):
        s = SecretStr("actual-value")
        assert s.get_secret_value() == "actual-value"

    def test_bool_false_for_empty(self):
        assert not SecretStr("")
        assert SecretStr("x")


class TestEncryptDecrypt:
    def test_round_trip(self):
        mk = "masterkey_test_32bytes_pad_1234"
        ct = _encrypt("hello world", mk)
        assert _encrypt("hello world", mk) != ct  # different nonce each time
        assert _decrypt(ct, mk) == "hello world"

    def test_wrong_key_fails(self):
        mk = "masterkey_test_32bytes_pad_1234"
        ct = _encrypt("secret", mk)
        with pytest.raises(Exception):
            _decrypt(ct, "wrongkey_test_32bytes_pad_12345")

    def test_tamper_detection(self):
        mk = "masterkey_test_32bytes_pad_1234"
        ct = _encrypt("secret", mk)
        # Flip last byte
        ct_tampered = ct[:-1] + ("A" if ct[-1] != "A" else "B")
        with pytest.raises(Exception):
            _decrypt(ct_tampered, mk)


class TestSecretsVault:
    def test_set_get(self, vault):
        vault.set("provider:openai", "sk-test-openai-key")
        result = vault.get("provider:openai")
        assert result is not None
        assert result.get_secret_value() == "sk-test-openai-key"

    def test_missing_key_returns_none(self, vault):
        assert vault.get("nonexistent") is None

    def test_delete(self, vault):
        vault.set("provider:test", "some-key")
        assert vault.delete("provider:test") is True
        assert vault.get("provider:test") is None
        assert vault.delete("provider:test") is False  # already gone

    def test_list_keys(self, vault):
        vault.set("provider:openai", "key1")
        vault.set("provider:anthropic", "key2")
        keys = vault.list_keys()
        assert "provider:openai" in keys
        assert "provider:anthropic" in keys

    def test_persistence(self, tmp_path):
        mk = "persistkey_32bytes_pad_________1"
        path = tmp_path / "persist.enc"
        v1 = SecretsVault(path=path, master_key=mk)
        v1.set("k", "value123")
        # New instance reads same file
        v2 = SecretsVault(path=path, master_key=mk)
        assert v2.get("k").get_secret_value() == "value123"

    def test_rotation(self, tmp_path):
        old_mk = "oldmasterkey_32bytes______________"
        new_mk = "newmasterkey_32bytes______________"
        path = tmp_path / "rotate.enc"
        vault = SecretsVault(path=path, master_key=old_mk)
        vault.set("p", "secret")
        vault.rotate_master_key(new_mk)
        # Can decrypt with new key
        assert vault.get("p").get_secret_value() == "secret"
        # Old key no longer works
        old_vault = SecretsVault(path=path, master_key=old_mk)
        assert old_vault.get("p") is None
