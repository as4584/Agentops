#!/usr/bin/env python3
"""Custom secret scanner — catches network credentials, IPs, and hardware identifiers.

Runs in CI and as a pre-commit hook. Exits non-zero if any pattern matches.
Patterns are tuned for Agentop's known exposure surface (router creds, WiFi
passwords, MAC addresses, public IPs near sensitive keywords).

Usage:
    python scripts/scan_secrets.py              # scan tracked files
    python scripts/scan_secrets.py --staged     # scan only staged files (pre-commit)
"""

import re
import subprocess
import sys
from pathlib import Path

# ── Files to skip ────────────────────────────────────────────────────────────
SKIP_PATTERNS = {
    ".git/",
    "node_modules/",
    ".next/",
    "__pycache__/",
    ".venv/",
    ".env.example",
    ".secrets.baseline",
    "scan_secrets.py",  # don't flag ourselves
    ".egg-info/",
    "output/",
    "sandbox/tmp/",
    ".coverage",
    "tsconfig.tsbuildinfo",
    "docs/handoffs/",  # historical chat logs, triaged safe
}

# ── Per-file rule overrides (pattern_name → set of file paths) ───────────────
# These suppress specific patterns in files where they're expected.
PER_FILE_ALLOWLIST: dict[str, set[str]] = {
    "bcrypt_hash_in_source": {"k8s/adguard-home/deployment.yaml"},
    "plaintext_password_assignment": {"k8s/adguard-home/deployment.yaml"},
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".mp3",
    ".wav",
    ".ogg",
    ".zip",
    ".tar",
    ".gz",
    ".pyc",
    ".so",
    ".dll",
    ".exe",
    ".db",
    ".sqlite",
    ".sqlite3",
}

# ── Patterns that should NEVER appear in committed code ──────────────────────
# Each tuple: (name, compiled_regex, description)
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "plaintext_password_assignment",
        re.compile(
            r"""(?i)(?:password|passwd|pwd|secret|credential)\s*[:=]\s*[`"'][^REDACTED\[\]{}\s*#][^"'`\n]{6,}[`"']""",
        ),
        "Plaintext password assignment (password: 'value' or password = \"value\")",
    ),
    (
        "public_ipv4",
        re.compile(
            r"\b(?:WAN|public|external|wan_ip|WAN.IP)\b[^.\n]{0,30}"
            r"\b(?:(?:2[0-5][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}"
            r"(?:2[0-5][0-9]|1[0-9]{2}|[1-9]?[0-9])\b",
        ),
        "Public/WAN IPv4 address near a keyword",
    ),
    (
        "mac_address",
        re.compile(
            r"\b[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-]"
            r"[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}\b",
        ),
        "MAC address (hardware identifier)",
    ),
    (
        "wifi_psk",
        re.compile(
            r"""(?i)(?:wifi|wi-fi|wpa|psk|ssid)[^.\n]{0,40}[`"'][^\s\[\]REDACTED]{8,}[`"']""",
        ),
        "WiFi password / PSK near wireless keyword",
    ),
    (
        "router_admin_cred",
        re.compile(
            r"""(?i)(?:router|gateway|omada|er605|a2300|tplink|tp-link|admin)\s*(?:password|pwd|pass|credential|login)\s*[:=]\s*[`"'][^REDACTED\[\]\s]{4,}[`"']""",
        ),
        "Router/gateway admin credentials",
    ),
    (
        "snmp_community_string",
        re.compile(
            r"""(?i)snmp[_\s]*community\s*[:=]\s*[`"'][^REDACTED\[\]\s]{2,}[`"']""",
        ),
        "SNMP community string",
    ),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "Private key block",
    ),
    (
        "aws_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key ID",
    ),
    (
        "generic_api_key",
        re.compile(
            r"""(?i)(?:api[_\s]*key|api[_\s]*secret|auth[_\s]*token)\s*[:=]\s*[`"'][0-9a-zA-Z_\-]{20,}[`"']""",
        ),
        "Generic API key / token assignment",
    ),
    (
        "bcrypt_hash_in_source",
        re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),
        "bcrypt hash in source code (store in env/secret, not code)",
    ),
]

# ── Allowlist — known safe matches ───────────────────────────────────────────
ALLOWLIST = [
    "REDACTED",
    "[REDACTED",
    "REDACTED_",
    "placeholder",
    "example.com",
    "your-password-here",
    "changeme",
    "localhost",
    "AKIAIOSFODNN7EXAMPLE",  # AWS official dummy key (used in tests)
    "unit-test-secret",  # test fixture
    "password123",  # doc anti-pattern example
    "NEVER Do This",  # doc section header
    "openssl rand",  # shell expansion, not a real secret
    "sk-or-",  # placeholder API key prefix in docs
    "a1b2c3d4",  # sequential hex placeholder in docs
    "agp_sk_",  # placeholder Agentop key in docs
]


def should_skip(path: str) -> bool:
    if any(s in path for s in SKIP_PATTERNS):
        return True
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def is_allowlisted(line: str) -> bool:
    return any(a.lower() in line.lower() for a in ALLOWLIST)


def get_files(staged_only: bool) -> list[str]:
    if staged_only:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
        )
        return [f for f in result.stdout.strip().split("\n") if f]
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def scan() -> int:
    staged_only = "--staged" in sys.argv
    files = get_files(staged_only)
    violations: list[str] = []

    for filepath in files:
        if should_skip(filepath):
            continue
        path = Path(filepath)
        if not path.exists():
            continue
        try:
            content = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        for line_num, line in enumerate(content.splitlines(), 1):
            if is_allowlisted(line):
                continue
            for name, pattern, description in FORBIDDEN_PATTERNS:
                if filepath in PER_FILE_ALLOWLIST.get(name, set()):
                    continue
                if pattern.search(line):
                    violations.append(f"  {filepath}:{line_num} [{name}] {description}")

    if violations:
        print(f"\n{'=' * 70}")
        print(f"SECRET SCAN FAILED — {len(violations)} violation(s) found:")
        print(f"{'=' * 70}")
        for v in violations:
            print(v)
        print(f"{'=' * 70}")
        print("Fix: replace values with [REDACTED] or move to .env / K8s secrets")
        print(f"{'=' * 70}\n")
        return 1

    mode = "staged files" if staged_only else "all tracked files"
    print(f"Secret scan passed — {len(files)} {mode} checked, 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(scan())
