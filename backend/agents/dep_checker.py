"""
Dependency Checker Agent — Automated dependency health monitoring.
================================================================
Runs on a cron schedule to:
  1. Check all Python deps for known CVEs (pip-audit)
  2. Identify outdated packages (pip list --outdated)
  3. Verify pyproject.toml ↔ requirements.txt consistency
  4. Log findings to shared_events and alert_dispatch

Designed to be dispatched by AgentopScheduler via cron.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from backend.config import PROJECT_ROOT
from backend.utils import logger


def _run_cmd(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    """Run a subprocess safely with timeout."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return 1, f"Command not found: {cmd[0]}"


def check_cves() -> dict[str, Any]:
    """Run pip-audit and return structured CVE findings."""
    code, output = _run_cmd(
        [sys.executable, "-m", "pip_audit", "--format=json", "--skip-editable"],
        timeout=180,
    )

    vulnerabilities: list[dict[str, Any]] = []
    if code == 0:
        try:
            data = json.loads(output)
            for dep in data.get("dependencies", []):
                if dep.get("vulns"):
                    vulnerabilities.append(
                        {
                            "package": dep["name"],
                            "version": dep["version"],
                            "vulns": dep["vulns"],
                        }
                    )
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "check": "cve_scan",
        "status": "clean" if not vulnerabilities else "vulnerable",
        "count": len(vulnerabilities),
        "vulnerabilities": vulnerabilities,
    }


def check_outdated() -> dict[str, Any]:
    """List outdated packages."""
    code, output = _run_cmd(
        [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
    )

    outdated: list[dict[str, str]] = []
    if code == 0:
        try:
            packages = json.loads(output)
            for pkg in packages:
                outdated.append(
                    {
                        "package": pkg["name"],
                        "current": pkg["version"],
                        "latest": pkg["latest_version"],
                        "type": pkg.get("latest_filetype", "unknown"),
                    }
                )
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "check": "outdated_packages",
        "status": "up_to_date" if not outdated else "updates_available",
        "count": len(outdated),
        "packages": outdated[:50],  # Cap at 50 to avoid noise
    }


def check_consistency() -> dict[str, Any]:
    """Verify pyproject.toml dependencies are a subset of requirements.txt."""
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    requirements_path = PROJECT_ROOT / "requirements.txt"

    issues: list[str] = []

    if not pyproject_path.exists():
        issues.append("pyproject.toml not found")
    if not requirements_path.exists():
        issues.append("requirements.txt not found")

    if issues:
        return {"check": "consistency", "status": "error", "issues": issues}

    # Parse requirements.txt package names
    req_names: set[str] = set()
    for line in requirements_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            # Extract package name (before any version specifier)
            name = line.split(">=")[0].split("==")[0].split("<=")[0].split("[")[0].strip().lower()
            if name:
                req_names.add(name)

    # Parse pyproject.toml dependencies (simple regex, no toml import needed)
    import re

    pyproject_text = pyproject_path.read_text()
    deps_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", pyproject_text, re.DOTALL)
    pyproject_names: set[str] = set()
    if deps_match:
        for dep_line in deps_match.group(1).splitlines():
            dep_line = dep_line.strip().strip('",')
            if dep_line:
                name = dep_line.split(">=")[0].split("==")[0].split("<=")[0].split("[")[0].strip().lower()
                if name:
                    pyproject_names.add(name)

    # Find deps in pyproject.toml but not in requirements.txt
    missing_from_req = pyproject_names - req_names
    if missing_from_req:
        issues.append(f"In pyproject.toml but not requirements.txt: {sorted(missing_from_req)}")

    return {
        "check": "consistency",
        "status": "consistent" if not issues else "inconsistent",
        "issues": issues,
        "pyproject_count": len(pyproject_names),
        "requirements_count": len(req_names),
    }


def run_full_check() -> dict[str, Any]:
    """Run all dependency checks and return a consolidated report."""
    timestamp = datetime.now(UTC).isoformat()
    logger.info("dep-checker: starting full dependency audit")

    cve_result = check_cves()
    outdated_result = check_outdated()
    consistency_result = check_consistency()

    # Overall health
    all_clean = cve_result["status"] == "clean" and consistency_result["status"] == "consistent"

    report = {
        "agent": "dep_checker",
        "timestamp": timestamp,
        "overall_health": "healthy" if all_clean else "attention_needed",
        "checks": {
            "cves": cve_result,
            "outdated": outdated_result,
            "consistency": consistency_result,
        },
    }

    # Log to shared events
    events_path = PROJECT_ROOT / "data" / "shared_events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with open(events_path, "a") as f:
        f.write(
            json.dumps(
                {
                    "event": "dep_check_completed",
                    "timestamp": timestamp,
                    "health": report["overall_health"],
                    "cve_count": cve_result["count"],
                    "outdated_count": outdated_result["count"],
                }
            )
            + "\n"
        )

    logger.info(
        f"dep-checker: audit complete — {report['overall_health']} "
        f"(CVEs: {cve_result['count']}, outdated: {outdated_result['count']})"
    )

    # Write full report
    report_path = PROJECT_ROOT / "data" / "dep_check_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    logger.info(f"dep-checker: report written to {report_path}")

    return report
