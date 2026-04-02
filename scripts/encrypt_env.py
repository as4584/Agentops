#!/usr/bin/env python3
"""
encrypt_env.py — Encrypt / decrypt .env at rest using AES-256-GCM.

Generates a master key in ~/.agentop/master.key (chmod 600) on first run.
Encrypted .env is stored as .env.enc alongside the plaintext .env.

Usage:
    python scripts/encrypt_env.py encrypt   # .env → .env.enc (removes .env)
    python scripts/encrypt_env.py decrypt   # .env.enc → .env
    python scripts/encrypt_env.py rotate    # re-encrypt with new key
    python scripts/encrypt_env.py status    # show encryption status
"""

from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path

# AES-256-GCM from stdlib-adjacent cryptography (already in requirements.txt)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENC_FILE = PROJECT_ROOT / ".env.enc"
KEY_DIR = Path.home() / ".agentop"
KEY_FILE = KEY_DIR / "master.key"

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def _ensure_key() -> bytes:
    """Load or generate the 256-bit master key. Stored chmod 600."""
    if KEY_FILE.exists():
        raw = KEY_FILE.read_bytes().strip()
        return base64.urlsafe_b64decode(raw)

    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key = AESGCM.generate_key(bit_length=256)
    KEY_FILE.write_bytes(base64.urlsafe_b64encode(key))
    os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
    print(f"[+] Generated master key → {KEY_FILE} (chmod 600)")
    return key


def _encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    """Return nonce(12) || ciphertext+tag."""
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ct


def _decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """Decrypt nonce(12) || ciphertext+tag."""
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_encrypt() -> None:
    if not ENV_FILE.exists():
        print("[!] No .env file found — nothing to encrypt.")
        sys.exit(1)

    key = _ensure_key()
    plaintext = ENV_FILE.read_bytes()
    blob = _encrypt_bytes(plaintext, key)

    # Write .env.enc as base64 for git-friendliness
    ENC_FILE.write_bytes(base64.urlsafe_b64encode(blob))
    os.chmod(ENC_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600

    # Remove plaintext .env
    ENV_FILE.unlink()
    print(f"[+] Encrypted .env → .env.enc ({len(plaintext)} bytes → {ENC_FILE.stat().st_size} bytes)")
    print("[+] Removed plaintext .env")
    print(f"[i] Master key: {KEY_FILE}")
    print("[i] To decrypt: python scripts/encrypt_env.py decrypt")


def cmd_decrypt() -> None:
    if not ENC_FILE.exists():
        print("[!] No .env.enc file found — nothing to decrypt.")
        sys.exit(1)
    if ENV_FILE.exists():
        print("[!] .env already exists. Remove it first or rename it.")
        sys.exit(1)

    key = _ensure_key()
    blob = base64.urlsafe_b64decode(ENC_FILE.read_bytes())
    plaintext = _decrypt_bytes(blob, key)

    ENV_FILE.write_bytes(plaintext)
    os.chmod(ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
    print(f"[+] Decrypted .env.enc → .env ({len(plaintext)} bytes)")
    print("[i] Re-encrypt when done: python scripts/encrypt_env.py encrypt")


def cmd_rotate() -> None:
    """Decrypt with old key, generate new key, re-encrypt."""
    if not ENC_FILE.exists():
        print("[!] No .env.enc to rotate. Encrypt first.")
        sys.exit(1)

    # Decrypt with current key
    old_key = _ensure_key()
    blob = base64.urlsafe_b64decode(ENC_FILE.read_bytes())
    plaintext = _decrypt_bytes(blob, old_key)

    # Generate new key
    new_key = AESGCM.generate_key(bit_length=256)
    KEY_FILE.write_bytes(base64.urlsafe_b64encode(new_key))
    os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)

    # Re-encrypt
    new_blob = _encrypt_bytes(plaintext, new_key)
    ENC_FILE.write_bytes(base64.urlsafe_b64encode(new_blob))

    print("[+] Rotated master key and re-encrypted .env.enc")
    print(f"[i] Old key is gone. New key: {KEY_FILE}")


def cmd_status() -> None:
    print(f"  .env        : {'EXISTS (plaintext!)' if ENV_FILE.exists() else 'not present'}")
    print(f"  .env.enc    : {'encrypted' if ENC_FILE.exists() else 'not present'}")
    print(f"  master.key  : {'exists' if KEY_FILE.exists() else 'NOT GENERATED'}")
    if ENV_FILE.exists() and ENC_FILE.exists():
        print("  [!] WARNING: Both .env and .env.enc exist. Encrypt or remove .env.")
    if ENV_FILE.exists():
        # Count secrets (lines with = and non-empty value that aren't comments)
        lines = ENV_FILE.read_text().splitlines()
        secret_count = sum(
            1 for line in lines if "=" in line and not line.strip().startswith("#") and line.split("=", 1)[1].strip()
        )
        print(f"  secrets     : {secret_count} variables with values")


def cmd_auto_decrypt_for_startup() -> None:
    """Called by backend startup — decrypt .env.enc → .env if needed."""
    if ENV_FILE.exists():
        return  # Already decrypted
    if not ENC_FILE.exists():
        return  # No encrypted file either
    if not KEY_FILE.exists():
        print("[!] .env.enc exists but no master key found. Run: python scripts/encrypt_env.py decrypt")
        return
    cmd_decrypt()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/encrypt_env.py [encrypt|decrypt|rotate|status]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "encrypt":
        cmd_encrypt()
    elif cmd == "decrypt":
        cmd_decrypt()
    elif cmd == "rotate":
        cmd_rotate()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
