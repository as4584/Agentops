#!/usr/bin/env python3
"""
content_cli.py — CLI for the Autonomous Content Pipeline.
=========================================================
All LLM calls use local Ollama. Zero cloud dependency.

Usage:
    python content_cli.py run --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Run full pipeline once (gated)
    python content_cli.py agent NAME --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Run specific agent (gated)
    python content_cli.py approve JOB_ID --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Approve a QA-passed job (gated)
    python content_cli.py reject JOB_ID --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Reject a job (gated)
    python content_cli.py retry JOB_ID ST --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Retry from status (gated)
  python content_cli.py status           Pipeline status
  python content_cli.py jobs             List all jobs
    python content_cli.py analytics --tests-ok --playwright-ok --lighthouse-mobile-ok
                                                                                Run weekly analytics (gated)
  python content_cli.py health           Check LLM + system health
"""

from __future__ import annotations

import asyncio
import sys

# Ensure project root is on path
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import SANDBOX_ENFORCEMENT_ENABLED
from backend.content.job_store import job_store
from backend.content.pipeline import ContentPipeline
from backend.content.video_job import JobStatus
from backend.llm import OllamaClient


def _get_pipeline() -> ContentPipeline:
    llm = OllamaClient()
    return ContentPipeline(llm)


def _extract_quality_checks(argv: list[str]) -> tuple[list[str], dict[str, bool]]:
    checks = {
        "tests_ok": "--tests-ok" in argv,
        "playwright_ok": "--playwright-ok" in argv,
        "lighthouse_mobile_ok": "--lighthouse-mobile-ok" in argv,
    }
    filtered = [item for item in argv if item not in {"--tests-ok", "--playwright-ok", "--lighthouse-mobile-ok"}]
    return filtered, checks


def _require_quality_checks(checks: dict[str, bool]) -> None:
    if not SANDBOX_ENFORCEMENT_ENABLED:
        return
    required = ("tests_ok", "playwright_ok", "lighthouse_mobile_ok")
    missing = [name for name in required if checks.get(name) is not True]
    if missing:
        raise SystemExit(
            "❌ Content mutation blocked by quality gate. "
            f"Missing checks: {', '.join(missing)}. "
            "Pass --tests-ok --playwright-ok --lighthouse-mobile-ok after validation."
        )


async def cmd_run():
    pipe = _get_pipeline()
    results = await pipe.run_full()
    print("\n✅ Pipeline complete!")
    for name, count in results.items():
        print(f"  {name}: {count} jobs")


async def cmd_agent(name: str):
    pipe = _get_pipeline()
    results = await pipe.run_agent(name)
    print(f"✅ {name}: {len(results)} jobs processed")


async def cmd_approve(job_id: str):
    pipe = _get_pipeline()
    job = pipe.approve_job(job_id)
    print(f"✅ Job {job_id} approved → {job.status.value}")


async def cmd_reject(job_id: str, reason: str = ""):
    pipe = _get_pipeline()
    pipe.reject_job(job_id, reason)
    print(f"❌ Job {job_id} rejected")


async def cmd_retry(job_id: str, status: str):
    pipe = _get_pipeline()
    pipe.retry_job(job_id, JobStatus(status))
    print(f"🔄 Job {job_id} restarted → {status}")


async def cmd_status():
    pipe = _get_pipeline()
    summary = pipe.get_status_summary()
    if not summary:
        print("No jobs in pipeline")
        return
    print("\nPipeline Status:")
    print("-" * 30)
    for st, count in summary.items():
        print(f"  {st:15s}  {count}")
    print(f"\n  Total: {sum(summary.values())} jobs")


async def cmd_jobs():
    all_jobs = job_store.list_all()
    if not all_jobs:
        print("No jobs found")
        return
    print(f"\nAll Jobs ({len(all_jobs)}):")
    print(f"{'ID':>12s}  {'Status':>12s}  {'Source':>8s}  Topic")
    print("-" * 70)
    for j in all_jobs:
        print(f"{j.job_id:>12s}  {j.status.value:>12s}  {j.source:>8s}  {j.topic[:40]}")


async def cmd_analytics():
    pipe = _get_pipeline()
    await pipe.run_weekly_analytics()
    print("✅ Weekly analytics complete")


async def cmd_health():
    llm = OllamaClient()
    available = await llm.is_available()
    models = await llm.list_models() if available else []
    print(f"\nOllama server: {'✅ online' if available else '❌ offline'}")
    print(f"URL: {llm.base_url}")
    print(f"Default model: {llm.model}")
    if models:
        print(f"Available models: {', '.join(models)}")
    else:
        print("No models found. Pull one with: ollama pull llama3.2")
    await llm.close()


def main():
    argv, quality_checks = _extract_quality_checks(sys.argv)

    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = argv[1]

    if cmd == "run":
        _require_quality_checks(quality_checks)
        asyncio.run(cmd_run())
    elif cmd == "agent":
        _require_quality_checks(quality_checks)
        asyncio.run(cmd_agent(argv[2]))
    elif cmd == "approve":
        _require_quality_checks(quality_checks)
        asyncio.run(cmd_approve(argv[2]))
    elif cmd == "reject":
        _require_quality_checks(quality_checks)
        reason = argv[3] if len(argv) > 3 else ""
        asyncio.run(cmd_reject(argv[2], reason))
    elif cmd == "retry":
        _require_quality_checks(quality_checks)
        asyncio.run(cmd_retry(argv[2], argv[3]))
    elif cmd == "status":
        asyncio.run(cmd_status())
    elif cmd == "jobs":
        asyncio.run(cmd_jobs())
    elif cmd == "analytics":
        _require_quality_checks(quality_checks)
        asyncio.run(cmd_analytics())
    elif cmd == "health":
        asyncio.run(cmd_health())
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
