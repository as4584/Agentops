#!/usr/bin/env python3
"""
scripts/sync_doppler.py — Sync secrets between .env and Doppler.

Usage:
    python scripts/sync_doppler.py status          # Show what's in Doppler vs .env
    python scripts/sync_doppler.py push             # Push .env values to Doppler
    python scripts/sync_doppler.py pull             # Pull Doppler values to .env
    python scripts/sync_doppler.py rotate KEY_NAME  # Rotate a specific secret
    python scripts/sync_doppler.py audit            # Check for exposed/stale secrets
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_ENC_FILE = ROOT / ".env.enc"

# Keys that should ALWAYS be in Doppler, never local
SENSITIVE_KEYS = {
    "AGENTOP_API_SECRET",
    "OPENROUTER_API_KEY",
    "FAL_KEY",
    "ELEVENLABS_API_KEY",
    "GITHUB_PAT",
    "TIKTOK_CLIENT_KEY",
    "TIKTOK_CLIENT_SECRET",
    "DISCORD_BOT_TOKEN",
}

# Keys safe to keep local (not secret)
LOCAL_ONLY_KEYS = {
    "AGENTOP_CORS_ORIGINS",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "FRONTEND_PORT",
}


def _check_doppler_cli() -> bool:
    """Check if Doppler CLI is installed and authenticated."""
    try:
        result = subprocess.run(["doppler", "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _doppler_get(project: str = "agentop", config: str = "dev") -> dict[str, str]:
    """Fetch all secrets from Doppler."""
    result = subprocess.run(
        ["doppler", "secrets", "download", "--no-file", "--project", project, "--config", config, "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"ERROR: Doppler fetch failed: {result.stderr.strip()}")
        return {}
    return json.loads(result.stdout)


def _doppler_set(key: str, value: str, project: str = "agentop", config: str = "dev") -> bool:
    """Set a single secret in Doppler."""
    result = subprocess.run(
        ["doppler", "secrets", "set", key, value, "--project", project, "--config", config],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.returncode == 0


def _parse_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict."""
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                env[key] = value
    return env


def _is_placeholder(value: str) -> bool:
    """Check if a value is a placeholder (not a real secret)."""
    placeholders = {"", "your-key-here", "changeme", "xxx", "CHANGEME", "your_key_here"}
    return value in placeholders or value.startswith("your-") or value.startswith("sk-xxx")


def cmd_status(args: argparse.Namespace) -> None:
    """Show sync status between .env and Doppler."""
    local = _parse_env(ENV_FILE)

    if not _check_doppler_cli():
        print("WARNING: Doppler CLI not installed. Install: curl -Ls https://cli.doppler.com/install.sh | sh")
        print(f"\nLocal .env has {len(local)} keys:")
        for key in sorted(local):
            is_sensitive = key in SENSITIVE_KEYS
            is_placeholder = _is_placeholder(local[key])
            status = "PLACEHOLDER" if is_placeholder else ("SENSITIVE" if is_sensitive else "ok")
            print(f"  {key}: [{status}]")
        return

    doppler = _doppler_get(args.project, args.config)

    print(f"{'Key':<35} {'Local':<15} {'Doppler':<15} {'Action'}")
    print("-" * 80)
    all_keys = sorted(set(list(local.keys()) + list(doppler.keys())))
    for key in all_keys:
        in_local = key in local and not _is_placeholder(local.get(key, ""))
        in_doppler = key in doppler and not _is_placeholder(doppler.get(key, ""))
        is_sensitive = key in SENSITIVE_KEYS
        is_local_only = key in LOCAL_ONLY_KEYS

        if is_local_only:
            action = "local-only (skip)"
        elif in_local and in_doppler:
            if local.get(key) == doppler.get(key):
                action = "synced"
            else:
                action = "CONFLICT — values differ"
        elif in_local and not in_doppler:
            action = "push to Doppler" if is_sensitive else "optional push"
        elif in_doppler and not in_local:
            action = "pull to local"
        else:
            action = "both empty"

        print(f"  {key:<33} {'YES' if in_local else 'no':<13} {'YES' if in_doppler else 'no':<13} {action}")


def cmd_push(args: argparse.Namespace) -> None:
    """Push local .env secrets to Doppler."""
    if not _check_doppler_cli():
        print("ERROR: Doppler CLI not installed.")
        sys.exit(1)

    local = _parse_env(ENV_FILE)
    pushed = 0
    for key, value in sorted(local.items()):
        if key in LOCAL_ONLY_KEYS:
            continue
        if _is_placeholder(value):
            continue
        if _doppler_set(key, value, args.project, args.config):
            print(f"  PUSHED: {key}")
            pushed += 1
        else:
            print(f"  FAILED: {key}")
    print(f"\nPushed {pushed} secrets to Doppler ({args.project}/{args.config})")


def cmd_pull(args: argparse.Namespace) -> None:
    """Pull secrets from Doppler to local .env."""
    if not _check_doppler_cli():
        print("ERROR: Doppler CLI not installed.")
        sys.exit(1)

    doppler = _doppler_get(args.project, args.config)
    local = _parse_env(ENV_FILE)

    updated = 0
    for key, value in doppler.items():
        if _is_placeholder(value):
            continue
        if key not in local or local[key] != value:
            local[key] = value
            updated += 1

    # Write back
    lines = []
    for key in sorted(local):
        lines.append(f'{key}="{local[key]}"')
    ENV_FILE.write_text("\n".join(lines) + "\n")
    print(f"Pulled {updated} secrets from Doppler → .env")
    print("Run: python scripts/encrypt_env.py encrypt  # to re-encrypt")


def cmd_rotate(args: argparse.Namespace) -> None:
    """Rotate a specific secret key."""
    key = args.key_name
    if not _check_doppler_cli():
        print("ERROR: Doppler CLI not installed. Rotating locally only.")

    new_value = secrets.token_urlsafe(48)
    local = _parse_env(ENV_FILE)
    old_value = local.get(key, "")

    local[key] = new_value
    lines = []
    for k in sorted(local):
        lines.append(f'{k}="{local[k]}"')
    ENV_FILE.write_text("\n".join(lines) + "\n")

    print(f"Rotated {key}:")
    print(f"  Old: {old_value[:8]}...{old_value[-4:]}" if len(old_value) > 12 else "  Old: (empty)")
    print(f"  New: {new_value[:8]}...{new_value[-4:]}")

    if _check_doppler_cli():
        if _doppler_set(key, new_value, args.project, args.config):
            print(f"  Synced to Doppler ({args.project}/{args.config})")
        else:
            print("  WARNING: Doppler sync failed — update manually")

    print("\nRemember to re-encrypt: python scripts/encrypt_env.py encrypt")


def cmd_audit(args: argparse.Namespace) -> None:
    """Audit secrets for exposure risk."""
    local = _parse_env(ENV_FILE)
    issues: list[str] = []

    for key in SENSITIVE_KEYS:
        if key in local and not _is_placeholder(local[key]):
            # Check if it looks like a test/dev key
            val = local[key]
            if len(val) < 16:
                issues.append(f"  WEAK: {key} is only {len(val)} chars (min 16 recommended)")
            if val.startswith("sk-") and "test" not in val.lower():
                issues.append(f"  LIVE KEY: {key} appears to be a production key — ensure Doppler is source of truth")

    # Check git history for leaked secrets
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--diff-filter=A", "--name-only", "--format="],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(ROOT),
        )
        tracked_files = result.stdout.strip().split("\n")
        if ".env" in tracked_files:
            issues.append("  CRITICAL: .env was added to git history at some point — rotate ALL secrets")
    except Exception:
        pass

    # Check .env.enc exists
    if not ENV_ENC_FILE.exists():
        issues.append("  WARNING: .env is not encrypted — run: python scripts/encrypt_env.py encrypt")

    if issues:
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(issue)
    else:
        print("No issues found. Secrets appear properly managed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync secrets with Doppler")
    parser.add_argument("--project", default="agentop", help="Doppler project name")
    parser.add_argument("--config", default="dev", help="Doppler config (dev/stg/prd)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show sync status")
    sub.add_parser("push", help="Push .env → Doppler")
    sub.add_parser("pull", help="Pull Doppler → .env")

    rotate_p = sub.add_parser("rotate", help="Rotate a secret")
    rotate_p.add_argument("key_name", help="Key to rotate")

    sub.add_parser("audit", help="Audit for exposure risk")

    args = parser.parse_args()
    if not args.command:
        args.command = "status"

    {"status": cmd_status, "push": cmd_push, "pull": cmd_pull, "rotate": cmd_rotate, "audit": cmd_audit}[args.command](
        args
    )


if __name__ == "__main__":
    main()
