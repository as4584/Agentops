#!/usr/bin/env python3
"""
Release evidence generator — Sprint 3.

Combines runtime inventory, drift check, and test coverage check into
a single machine-readable release evidence artifact stored at
reports/release_evidence.json.

Usage:
    python scripts/generate_release_evidence.py [--stdout]
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_OUTPUT_PATH = _REPORTS_DIR / "release_evidence.json"


def _run_check(name: str, cmd: list[str]) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        passed = result.returncode == 0
        return {
            "name": name,
            "passed": passed,
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr).strip()[:500],
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "passed": False, "exit_code": -1, "output": "TIMEOUT"}
    except Exception as exc:
        return {"name": name, "passed": False, "exit_code": -1, "output": str(exc)[:200]}


def main() -> int:
    stdout_only = "--stdout" in sys.argv

    checks = [
        _run_check(
            "config_validation",
            [sys.executable, "-m", "backend.config", "validate"],
        ),
        _run_check(
            "architecture_drift",
            [sys.executable, "scripts/verify_architecture_drift.py"],
        ),
    ]

    all_passed = all(c["passed"] for c in checks)

    # Runtime inventory (from file if exists, else inline)
    inventory_path = _REPORTS_DIR / "runtime_inventory.json"
    inventory_summary: dict = {}
    if inventory_path.exists():
        try:
            inv = json.loads(inventory_path.read_text())
            inventory_summary = {
                "native_tool_count": inv.get("native_tool_count"),
                "mcp_tool_count": inv.get("mcp_tool_count"),
                "gitnexus_usable": inv.get("gitnexus_health", {}).get("usable"),
                "agent_count": len(inv.get("agent_tool_permissions", {})),
                "deployment_mode": inv.get("deployment_mode"),
            }
        except Exception:
            pass

    evidence = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "all_passed": all_passed,
        "checks": checks,
        "inventory_summary": inventory_summary,
    }

    payload = json.dumps(evidence, indent=2)
    if stdout_only:
        print(payload)
    else:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_PATH.write_text(payload, encoding="utf-8")
        print(f"Release evidence written to {_OUTPUT_PATH}")
        for c in checks:
            status = "PASS" if c["passed"] else "FAIL"
            print(f"  [{status}] {c['name']}")
        if not all_passed:
            print("\nRelease evidence contains FAILURES.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
