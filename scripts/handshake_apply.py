#!/usr/bin/env python3
"""
scripts/handshake_apply.py — Run Lex's Handshake application campaign.

Usage:
    # Dry run (browser opens, no forms submitted — good for first test)
    python scripts/handshake_apply.py --dry-run --limit 5

    # Real run — apply to up to 50 jobs
    python scripts/handshake_apply.py --limit 50

    # Apply to everything (no limit)
    python scripts/handshake_apply.py --limit 999

    # Show results summary only
    python scripts/handshake_apply.py --status

First run:
    A browser window will open and ask you to log into Handshake.
    After logging in, press ENTER in this terminal.
    Your session is saved — subsequent runs won't ask for login again.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _print_status():
    db = Path("data/job_applications.db")
    if not db.exists():
        print("No applications tracked yet.")
        return
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM applications GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    last10 = conn.execute(
        "SELECT company, role, status, applied_date FROM applications ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    conn.close()

    print(f"\n{'='*55}")
    print(f"  HANDSHAKE APPLICATION TRACKER — {total} total")
    print(f"{'='*55}")
    for status, count in rows:
        bar = "█" * min(count, 40)
        print(f"  {status:<25} {count:>4}  {bar}")
    print(f"\n  Last 10 applications:")
    print(f"  {'Company':<25} {'Role':<30} {'Status':<15} {'Date'}")
    print(f"  {'-'*25} {'-'*30} {'-'*15} {'-'*10}")
    for company, role, status, date in last10:
        print(f"  {company[:24]:<25} {role[:29]:<30} {status[:14]:<15} {date or 'pending'}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Handshake job application campaign for Lex Santiago")
    parser.add_argument("--limit", type=int, default=20, help="Max number of jobs to apply to (default: 20)")
    parser.add_argument("--dry-run", action="store_true", help="Open browser and screenshot but do NOT submit")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (no window) — requires prior login")
    parser.add_argument("--status", action="store_true", help="Show application tracker status and exit")
    parser.add_argument("--interactive", action="store_true", help="Pause per job to paste a Copilot/Sonnet cover letter")
    args = parser.parse_args()

    if args.status:
        _print_status()
        return

    _interactive_label = "Interactive — paste Copilot/Sonnet output per job"
    print(f"""
╔══════════════════════════════════════════════════════╗
║       AGENTOP — HANDSHAKE APPLICATION CAMPAIGN       ║
║       Candidate: Alexander (Lex) Santiago            ║
║       School: NJIT | Grad: May 2028                  ║
╚══════════════════════════════════════════════════════╝

  Mode:    {"DRY RUN (no submissions)" if args.dry_run else "LIVE (submitting applications)"}
  Limit:   {args.limit} jobs
  Browser: {"Headless" if args.headless else "Headed (visible window)"}
  Letters: {_interactive_label if args.interactive else "Auto (Ollama template, or skipped if no field)"}
  Profile: data/handshake_profile/ (persistent login)

""")

    from backend.skills.job_application.handshake import run_handshake_campaign

    results = asyncio.run(
        run_handshake_campaign(
            limit=args.limit,
            dry_run=args.dry_run,
            headed=not args.headless,
            interactive=args.interactive,
        )
    )

    # Summary
    applied = [r for r in results if r["status"] == "applied"]
    errors = [r for r in results if r["status"].startswith("error")]
    skipped = [r for r in results if r["status"] in ("no_apply_button", "skipped")]
    dry = [r for r in results if r["status"] == "dry_run"]

    print(f"""
{'='*55}
CAMPAIGN COMPLETE
{'='*55}
  Total jobs processed : {len(results)}
  Applied              : {len(applied)}
  Dry run captures     : {len(dry)}
  No apply button      : {len(skipped)}
  Errors               : {len(errors)}
  Screenshots in       : output/handshake_screenshots/
  Tracker DB           : data/job_applications.db

Run  python scripts/handshake_apply.py --status  to see full tracker.
{'='*55}
""")

    if errors:
        print("  Errors:")
        for r in errors[:5]:
            print(f"    {r['company']} — {r['status']}")


if __name__ == "__main__":
    main()
