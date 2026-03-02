#!/usr/bin/env python3
"""
content_cli.py — CLI for the Autonomous Content Pipeline.
=========================================================
All LLM calls use local Ollama. Zero cloud dependency.

Usage:
  python content_cli.py run              Run full pipeline once
  python content_cli.py agent NAME       Run specific agent
  python content_cli.py approve JOB_ID   Approve a QA-passed job
  python content_cli.py reject JOB_ID    Reject a job
  python content_cli.py retry JOB_ID ST  Retry from status
  python content_cli.py status           Pipeline status
  python content_cli.py jobs             List all jobs
  python content_cli.py analytics        Run weekly analytics
  python content_cli.py health           Check LLM + system health
"""

from __future__ import annotations

import asyncio
import sys
import json

# Ensure project root is on path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.llm import OllamaClient
from backend.content.pipeline import ContentPipeline
from backend.content.job_store import job_store
from backend.content.video_job import JobStatus


def _get_pipeline() -> ContentPipeline:
    llm = OllamaClient()
    return ContentPipeline(llm)


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
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "run":
        asyncio.run(cmd_run())
    elif cmd == "agent":
        asyncio.run(cmd_agent(sys.argv[2]))
    elif cmd == "approve":
        asyncio.run(cmd_approve(sys.argv[2]))
    elif cmd == "reject":
        reason = sys.argv[3] if len(sys.argv) > 3 else ""
        asyncio.run(cmd_reject(sys.argv[2], reason))
    elif cmd == "retry":
        asyncio.run(cmd_retry(sys.argv[2], sys.argv[3]))
    elif cmd == "status":
        asyncio.run(cmd_status())
    elif cmd == "jobs":
        asyncio.run(cmd_jobs())
    elif cmd == "analytics":
        asyncio.run(cmd_analytics())
    elif cmd == "health":
        asyncio.run(cmd_health())
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
