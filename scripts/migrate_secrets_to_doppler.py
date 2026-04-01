#!/usr/bin/env python3
from __future__ import annotations

import argparse
import secrets
import string
import subprocess
import sys
from pathlib import Path

PLACEHOLDER_HINTS = (
    "your_",
    "changeme",
    "example",
    "<secret>",
    "replace_me",
)

ROTATE_DEFAULT_KEYS = [
    "AGENTOP_API_SECRET",
    "TIKTOK_CLIENT_SECRET",
    "META_APP_SECRET",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
    "GITHUB_TOKEN",
]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = val.strip().strip('"').strip("'")
    return values


def _is_real_secret(value: str) -> bool:
    if not value:
        return False
    low = value.lower()
    return not any(h in low for h in PLACEHOLDER_HINTS)


def _random_secret(length: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _require_doppler() -> None:
    code, _, _ = _run(["doppler", "--version"])
    if code != 0:
        raise RuntimeError("doppler CLI not found. Install Doppler CLI first.")


def _set_secret(key: str, value: str, project: str | None, config: str | None) -> None:
    cmd = ["doppler", "secrets", "set", f"{key}={value}"]
    if project:
        cmd.extend(["--project", project])
    if config:
        cmd.extend(["--config", config])
    code, _, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"Failed to set {key}: {err}")


def _get_secret(key: str, project: str | None, config: str | None) -> str:
    cmd = ["doppler", "secrets", "get", key, "--plain"]
    if project:
        cmd.extend(["--project", project])
    if config:
        cmd.extend(["--config", config])
    code, out, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"Failed to fetch {key}: {err}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate .env secrets into Doppler and validate rotation.")
    parser.add_argument("--env-file", default=".env", help="Path to source .env file")
    parser.add_argument("--project", default="agentop", help="Doppler project")
    parser.add_argument("--config", default="dev", help="Doppler config")
    parser.add_argument("--apply", action="store_true", help="Apply migration to Doppler")
    parser.add_argument(
        "--rotate-sensitive",
        action="store_true",
        help="Rotate sensitive keys to fresh random values during migration",
    )
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"Missing env file: {env_path}", file=sys.stderr)
        return 1

    values = _parse_env_file(env_path)
    candidates = {k: v for k, v in values.items() if _is_real_secret(v)}
    if not candidates:
        print("No non-placeholder secrets found to migrate.")
        return 0

    rotate_keys = {k for k in ROTATE_DEFAULT_KEYS if k in candidates}

    print(f"Found {len(candidates)} non-placeholder secrets in {env_path}.")
    print("Keys:")
    for key in sorted(candidates):
        print(f"- {key}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to write to Doppler.")
        if args.rotate_sensitive:
            print("Rotation preview enabled; sensitive keys would be rotated on apply.")
        return 0

    try:
        _require_doppler()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("\nApplying migration to Doppler...")
    migrated: dict[str, str] = {}
    originals: dict[str, str] = {}
    for key, value in sorted(candidates.items()):
        originals[key] = value
        if args.rotate_sensitive and key in rotate_keys:
            value = _random_secret()
        _set_secret(key, value, args.project, args.config)
        migrated[key] = value

    print(f"Wrote {len(migrated)} secrets to Doppler ({args.project}/{args.config}).")

    print("\nValidating migrated secrets...")
    for key, expected in sorted(migrated.items()):
        actual = _get_secret(key, args.project, args.config)
        if actual != expected:
            print(f"Validation failed: {key} value mismatch after write", file=sys.stderr)
            return 1

    if args.rotate_sensitive:
        for key in sorted(rotate_keys):
            if migrated[key] == originals[key]:
                print(f"Rotation validation failed: {key} was not rotated", file=sys.stderr)
                return 1

    print("Validation successful.")
    if args.rotate_sensitive and rotate_keys:
        print("Sensitive keys rotated:")
        for key in sorted(rotate_keys):
            print(f"- {key}")

    print("\nNext steps:")
    print("1. Remove real values from local .env (keep placeholders only).")
    print("2. Use 'doppler run -- python -m backend.port_guard serve backend.server:app --host 127.0.0.1 --port 8000'.")
    print("3. Rotate keys at providers where required (GitHub/OpenRouter/etc.) if old values were ever committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
