"""
Gateway Secrets — AES-256-GCM encryption for provider API keys at rest.
======================================================================
Provider keys are encrypted before persisted and decrypted only at
runtime.  The master key is sourced from AGENTOP_GATEWAY_MASTER_KEY
(env or injected by a secrets manager / KMS).

Keys never appear in:
- Log output
- Stack traces (values are wrapped in SecretStr)
- HTTP responses
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.config_gateway import GATEWAY_MASTER_KEY, GATEWAY_SECRETS_PATH

# ---------------------------------------------------------------------------
# SecretStr — Prevents accidental logging of sensitive values
# ---------------------------------------------------------------------------


class SecretStr:
    """Wrapper that masks value in repr / str to prevent leakage."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:  # noqa: D102
        return self._value

    def __repr__(self) -> str:  # noqa: D105
        return "SecretStr('**********')"

    def __str__(self) -> str:  # noqa: D105
        return "**********"

    def __bool__(self) -> bool:  # noqa: D105
        return bool(self._value)


# ---------------------------------------------------------------------------
# Key Derivation
# ---------------------------------------------------------------------------


def _derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from the master key + salt via PBKDF2-SHA256."""
    raw = master_key.encode() if isinstance(master_key, str) else master_key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=260_000,
    )
    return kdf.derive(raw)


# ---------------------------------------------------------------------------
# Encryption / Decryption helpers
# ---------------------------------------------------------------------------


def _encrypt(plaintext: str, master_key: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns a base64url-encoded blob: salt(16) || nonce(12) || ciphertext+tag.
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(master_key, salt)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    blob = salt + nonce + ct
    return base64.urlsafe_b64encode(blob).decode()


def _decrypt(blob_b64: str, master_key: str) -> str:
    """Decrypt a blob produced by _encrypt()."""
    blob = base64.urlsafe_b64decode(blob_b64.encode())
    salt, nonce, ct = blob[:16], blob[16:28], blob[28:]
    key = _derive_key(master_key, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ---------------------------------------------------------------------------
# SecretsVault
# ---------------------------------------------------------------------------


class SecretsVault:
    """Persistent, encrypted key–value store for provider API keys.

    Secrets are stored in *path* as a JSON file where each value is an
    AES-256-GCM ciphertext blob.  The file itself should be 600 / owner-only.
    """

    def __init__(
        self,
        path: Path = GATEWAY_SECRETS_PATH,
        master_key: str = GATEWAY_MASTER_KEY,
    ) -> None:
        self._path = path
        self._master_key = master_key
        self._data: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self._data = raw.get("secrets", {})
            except Exception:
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"secrets": self._data}, indent=2))
        # chmod 600 — owner read/write only
        os.chmod(self._path, 0o600)

    # ------------------------------------------------------------------ API

    def set(self, key: str, value: str) -> None:
        """Encrypt and store *value* under *key*."""
        self._data[key] = _encrypt(value, self._master_key)
        self._save()

    def get(self, key: str) -> SecretStr | None:
        """Retrieve and decrypt the value for *key*, or None if absent."""
        ciphertext = self._data.get(key)
        if not ciphertext:
            return None
        try:
            plaintext = _decrypt(ciphertext, self._master_key)
            return SecretStr(plaintext)
        except Exception:
            return None

    def delete(self, key: str) -> bool:
        """Remove *key*. Returns True if it existed."""
        existed = key in self._data
        self._data.pop(key, None)
        if existed:
            self._save()
        return existed

    def rotate_master_key(self, new_master_key: str) -> None:
        """Re-encrypt all secrets under a new master key."""
        new_data: dict[str, str] = {}
        for k, ciphertext in self._data.items():
            plaintext = _decrypt(ciphertext, self._master_key)
            new_data[k] = _encrypt(plaintext, new_master_key)
        self._data = new_data
        self._master_key = new_master_key
        self._save()

    def list_keys(self) -> list[str]:
        """Return the list of stored secret keys (not their values)."""
        return list(self._data.keys())

    def has(self, key: str) -> bool:  # noqa: D102
        return key in self._data


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_vault: SecretsVault | None = None


def get_vault() -> SecretsVault:
    """Return the module-level SecretsVault singleton."""
    global _vault
    if _vault is None:
        _vault = SecretsVault()
    return _vault


def get_provider_key(provider: str) -> SecretStr | None:
    """Convenience: fetch a provider API key from the vault.

    Falls back to the plain environment variable (unencrypted) for
    development deployments that haven't migrated to the vault yet.
    """
    secret = get_vault().get(f"provider:{provider}")
    if secret:
        return secret
    # Fallback: plain env var
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "copilot": "COPILOT_TOKEN",
    }
    env_var = env_map.get(provider.lower())
    if env_var:
        val = os.getenv(env_var, "")
        if val:
            return SecretStr(val)
    return None


# ---------------------------------------------------------------------------
# Infrastructure credential helpers
# ---------------------------------------------------------------------------

# Valid infrastructure device categories.  Keys are stored as
# "infra:<device>" in the vault (e.g. "infra:router", "infra:wap").
INFRA_DEVICES = frozenset(
    {
        "router",  # ER605 admin
        "wap",  # A2300 WAP admin
        "godaddy",  # GoDaddy API key + secret
        "ddns",  # Dynamic DNS credentials
        "doppler",  # Doppler service token
        "discord",  # Discord bot token
    }
)


def set_infra_credential(device: str, username: str, password: str) -> None:
    """Store an infrastructure credential pair in the vault."""
    device = device.lower()
    if device not in INFRA_DEVICES:
        raise ValueError(f"Unknown infra device: {device}. Valid: {sorted(INFRA_DEVICES)}")
    payload = json.dumps({"username": username, "password": password})
    get_vault().set(f"infra:{device}", payload)


def get_infra_credential(device: str) -> dict[str, str] | None:
    """Retrieve an infrastructure credential pair from the vault.

    Returns {"username": ..., "password": ...} or None.
    """
    device = device.lower()
    secret = get_vault().get(f"infra:{device}")
    if not secret:
        return None
    try:
        return json.loads(secret.get_secret_value())
    except (json.JSONDecodeError, KeyError):
        return None


def list_infra_devices() -> list[str]:
    """Return infra device names that have stored credentials."""
    vault = get_vault()
    return [k.removeprefix("infra:") for k in vault.list_keys() if k.startswith("infra:")]
