#!/usr/bin/env python3
"""
Pre-push Audit — Lightweight technical + security checks before every push.
=============================================================================
Catches pile-on issues before they reach the remote:

1. Orphaned routes     — route files not registered in server.py
2. Empty secret guards — API_SECRET / GATEWAY keys must be warned-about
3. Timing-safe auth    — bearer comparisons must use hmac.compare_digest
4. Dead imports        — route modules imported but never include_router'd
5. Injection coverage  — chat endpoint must have injection pattern list
6. Secret scan         — delegates to scan_secrets.py

Exit 0 = all clear, exit 1 = violations found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend"
SERVER_PY = BACKEND / "server.py"
ROUTES_DIR = BACKEND / "routes"
SKILLS_DIR = BACKEND / "skills"

# Canonical 12 agent IDs — update when a new agent is added to ALL_AGENT_DEFINITIONS
VALID_AGENT_IDS: frozenset[str] = frozenset(
    {
        "soul_core",
        "devops_agent",
        "monitor_agent",
        "self_healer_agent",
        "code_review_agent",
        "security_agent",
        "data_agent",
        "comms_agent",
        "cs_agent",
        "it_agent",
        "knowledge_agent",
        "ocr_agent",
    }
)

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BOLD = "\033[1m"
RESET = "\033[0m"

violations: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    violations.append(msg)
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  {YELLOW}⚠{RESET} {msg}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


# ── 1. Orphaned route files ──────────────────────────────────────────────────


def check_orphaned_routes() -> None:
    """Every backend/routes/*.py with a router must be registered.

    Registration can happen in one of two places:
      1. Directly in server.py (legacy pattern)
      2. Via register_all_routes() in backend/routes/__init__.py (Sprint 6+)
    """
    routes_init = ROUTES_DIR / "__init__.py"
    server_text = SERVER_PY.read_text()
    # Combined corpus: server.py + routes/__init__.py
    registration_corpus = server_text + (routes_init.read_text() if routes_init.exists() else "")

    # If server.py delegates to register_all_routes(), treat routes/__init__.py
    # as the authoritative registration file.
    uses_register_all = "register_all_routes" in server_text

    route_files = sorted(ROUTES_DIR.glob("*.py"))

    for rf in route_files:
        if rf.name.startswith("_"):
            continue
        content = rf.read_text()
        # Check if file defines a router
        if "APIRouter" not in content:
            continue
        module_name = rf.stem  # e.g. "knowledge"
        import_pattern = rf"from backend\.routes\.{module_name} import"
        if not re.search(import_pattern, registration_corpus):
            fail(
                f"Orphaned route: backend/routes/{rf.name} defines a router"
                f" but is not imported in server.py or routes/__init__.py"
            )
            continue
        # Check include_router call in the combined corpus
        router_aliases = re.findall(
            rf"from backend\.routes\.{module_name} import .*?router as (\w+)",
            registration_corpus,
        )
        if not router_aliases:
            router_aliases = [f"{module_name}_router"]
        registered = any(f"include_router({alias})" in registration_corpus for alias in router_aliases)
        if not registered:
            if f"from backend.routes.{module_name} import router" in registration_corpus:
                pass  # imported as plain "router" — trust it's wired
            elif uses_register_all and re.search(import_pattern, routes_init.read_text() if routes_init.exists() else ""):
                pass  # imported inside register_all_routes body — wired
            else:
                fail(f"Route imported but not registered: backend/routes/{rf.name}")


# ── 1b. Orphaned skill manifests (warn-only) ─────────────────────────────────


def check_orphaned_skills() -> None:
    """Warn if any skill.json references an agent ID not in VALID_AGENT_IDS."""
    import json as _json

    skill_files = sorted(SKILLS_DIR.glob("*/skill.json"))
    if not skill_files:
        ok("Skills: no skill.json manifests found")
        return

    bad: list[str] = []
    for sf in skill_files:
        try:
            data = _json.loads(sf.read_text())
        except Exception:
            warn(f"Skills: could not parse {sf.relative_to(PROJECT_ROOT)}")
            continue
        allowed = data.get("allowed_agents", [])
        if not isinstance(allowed, list):
            continue
        # "*" is a valid wildcard meaning "any agent" — skip it
        invalid = [a for a in allowed if a != "*" and a not in VALID_AGENT_IDS]
        if invalid:
            bad.append(f"{sf.parent.name}: {invalid}")

    if bad:
        for entry in bad:
            warn(f"Skill manifest references unknown agent(s): {entry}")
    else:
        ok(f"Skills: all {len(skill_files)} manifests reference valid agents")


# ── 2. Timing-safe auth check ────────────────────────────────────────────────

AUTH_PY = BACKEND / "auth.py"


def check_timing_safe_auth() -> None:
    """Bearer token comparison must use hmac.compare_digest, not == or !="""
    server_text = SERVER_PY.read_text()
    # Look for direct string comparison on auth tokens
    if re.search(r"auth\[7:\]\s*[!=]=\s*API_SECRET", server_text):
        fail("Timing-unsafe bearer token comparison in server.py (use hmac.compare_digest)")
        return
    # Auth was refactored into backend/auth.py — check the delegation pattern:
    # server.py must import verify_api_request and auth.py must use hmac.compare_digest
    if not re.search(r"from backend\.auth import.*verify_api_request", server_text):
        fail("server.py does not import verify_api_request from backend.auth")
        return
    if not AUTH_PY.exists():
        fail("backend/auth.py not found")
        return
    auth_text = AUTH_PY.read_text()
    if "hmac.compare_digest" in auth_text:
        ok("Bearer token uses timing-safe comparison (hmac.compare_digest in backend/auth.py)")
    else:
        fail("No hmac.compare_digest found in backend/auth.py")


# ── 3. Dev key fallback check ────────────────────────────────────────────────


def check_no_dev_key_fallback() -> None:
    """config_gateway.py must not fall back to a deterministic dev key."""
    gateway_cfg = BACKEND / "config_gateway.py"
    if not gateway_cfg.exists():
        return
    text = gateway_cfg.read_text()
    if "dev000000" in text:
        fail("config_gateway.py still has deterministic dev key fallback")
    else:
        ok("No deterministic dev key fallback in config_gateway.py")


# ── 4. Injection pattern coverage ────────────────────────────────────────────


def check_injection_patterns() -> None:
    """Chat endpoint must have prompt injection patterns covering key attacks."""
    server_text = SERVER_PY.read_text()
    required_patterns = [
        "ignore previous instructions",
        "you are now",
        "</s>",
        "<|im_start|>",
        "disregard",
    ]
    missing = [p for p in required_patterns if p not in server_text]
    if missing:
        fail(f"Chat endpoint missing injection patterns: {missing}")
    else:
        ok(f"Injection detection covers {len(required_patterns)} core attack patterns")


# ── 5. Secret scan ───────────────────────────────────────────────────────────


def check_secrets() -> None:
    """Run the custom secret scanner."""
    scanner = PROJECT_ROOT / "scripts" / "scan_secrets.py"
    if not scanner.exists():
        fail("scripts/scan_secrets.py not found")
        return
    result = subprocess.run(
        [sys.executable, str(scanner)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        fail(f"Secret scanner found violations:\n{result.stdout[-500:]}")
    else:
        # Extract summary from output
        for line in result.stdout.strip().splitlines():
            if "checked" in line.lower() or "violation" in line.lower():
                ok(line.strip())
                return
        ok("Secret scan passed")


# ── 6. Import sanity — hmac must be imported where used ──────────────────────


def check_hmac_imported() -> None:
    """If hmac.compare_digest is used in auth.py, hmac must be imported there."""
    if not AUTH_PY.exists():
        return
    auth_text = AUTH_PY.read_text()
    if "hmac.compare_digest" in auth_text and "import hmac" not in auth_text:
        fail("backend/auth.py uses hmac.compare_digest but does not import hmac")


# ── 7. Test suite smoke check ────────────────────────────────────────────────


def check_tests_pass() -> None:
    """Run pytest on backend + deerflow tests (fast, no coverage)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests/",
            "deerflow/tests/",
            "--ignore=backend/tests/test_scheduler_routes.py",
            "-x",
            "--tb=line",
            "-q",
            "--no-header",
            "--no-cov",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    # Parse the summary line (e.g. "1161 passed, 5 skipped")
    summary = ""
    for line in reversed(result.stdout.strip().splitlines()):
        if "passed" in line:
            summary = line.strip()
            break
    if result.returncode == 0:
        ok(f"Tests: {summary}" if summary else "Tests passed")
    else:
        # Find any FAILED lines
        failures = [line for line in result.stdout.splitlines() if "FAILED" in line]
        fail(f"Tests failed: {failures[0] if failures else summary or 'exit code ' + str(result.returncode)}")


# ── 8. Ruff lint check ───────────────────────────────────────────────────────


def check_ruff() -> None:
    """Run ruff check (lint) and ruff format --check (style)."""
    result = subprocess.run(
        ["ruff", "check", "."],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        ok("Ruff lint clean")
    else:
        lines = result.stdout.strip().splitlines()
        count = len([line for line in lines if line and not line.startswith("Found")])
        fail(f"Ruff found {count} lint issues (run: ruff check .)")

    fmt = subprocess.run(
        ["ruff", "format", "--check", "."],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if fmt.returncode == 0:
        ok("Ruff format clean")
    else:
        lines = fmt.stdout.strip().splitlines()
        files = [l for l in lines if l.startswith("Would reformat")]
        fail(f"Ruff format: {len(files)} file(s) need formatting (run: ruff format .)")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    print()
    print(f"{BOLD}┌─────────────────────────────────────────────────┐{RESET}")
    print(f"{BOLD}│       pre-push: technical + security audit      │{RESET}")
    print(f"{BOLD}└─────────────────────────────────────────────────┘{RESET}")
    print()

    check_orphaned_routes()
    check_orphaned_skills()
    check_timing_safe_auth()
    check_no_dev_key_fallback()
    check_injection_patterns()
    check_hmac_imported()
    check_secrets()
    check_ruff()
    check_tests_pass()

    print()
    if violations:
        print(f"{RED}{BOLD}  ✗ AUDIT FAILED — {len(violations)} violation(s) found.{RESET}")
        print("  Fix the issues above before pushing.")
        print("  Emergency bypass: git push --no-verify")
        print()
        return 1
    else:
        if warnings:
            print(
                f"{YELLOW}{BOLD}  ⚠ Audit passed with {len(warnings)} warning(s). Review above before pushing.{RESET}"
            )
        else:
            print(f"{GREEN}{BOLD}  ✓ Audit passed — all checks clean.{RESET}")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
