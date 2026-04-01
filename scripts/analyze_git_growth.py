#!/usr/bin/env python3
"""
Git Growth Analyzer for Agentop
================================
Analyzes commit history to show:
- Lines of code added/removed over time
- Test coverage growth
- Commit frequency
- Skill/agent capability growth
- Performance improvements (based on commit messages)

Run: python scripts/analyze_git_growth.py [--since DATE]
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


class GitGrowthAnalyzer:
    """Analyze git history for growth metrics."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self.commits = []
        self._load_commits()

    def _run_git(self, cmd: str) -> str:
        """Run git command in repo."""
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _load_commits(self) -> None:
        """Load all commits with metadata."""
        # Format: hash|author|date|subject
        output = self._run_git('git log --pretty=format:"%H|%an|%ai|%s" --all')
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                hash_, author, date_str, subject = parts
                try:
                    date_obj = datetime.fromisoformat(date_str.replace(" ", "T"))
                    self.commits.append(
                        {
                            "hash": hash_,
                            "author": author,
                            "date": date_obj,
                            "subject": subject,
                        }
                    )
                except ValueError:
                    pass

    def commits_by_week(self) -> dict[str, int]:
        """Group commits by week."""
        weeks = {}
        for commit in self.commits:
            date = commit["date"]
            week_start = date - timedelta(days=date.weekday())
            week_key = week_start.strftime("%Y-W%V")
            weeks[week_key] = weeks.get(week_key, 0) + 1
        return weeks

    def feature_commits(self) -> list[dict[str, Any]]:
        """Extract feature/fix/feat commits with impact."""
        feature_commits = []
        for commit in self.commits:
            subject = commit["subject"]
            if any(x in subject for x in ["feat", "fix", "feat(", "fix("]):
                feature_commits.append(commit)
        return sorted(feature_commits, key=lambda x: x["date"], reverse=True)

    def estimate_skill_growth(self) -> dict[str, Any]:
        """Estimate skill count growth from commit messages."""
        skill_markers = {}
        for commit in sorted(self.commits, key=lambda x: x["date"]):
            subject = commit["subject"]
            date = commit["date"].strftime("%Y-%m-%d")

            # Track key milestones
            if "skill" in subject.lower():
                skill_markers[date] = skill_markers.get(date, 0) + 1
            if "agent" in subject.lower():
                if "agents" not in skill_markers:
                    skill_markers["agents"] = {}
                skill_markers["agents"][date] = skill_markers["agents"].get(date, 0) + 1

        return skill_markers

    def estimate_test_coverage_growth(self) -> dict[str, Any]:
        """Estimate test coverage growth from commit messages."""
        coverage_events = {}
        for commit in sorted(self.commits, key=lambda x: x["date"]):
            subject = commit["subject"]
            date = commit["date"].strftime("%Y-%m-%d")

            # Look for coverage mentions
            if "coverage" in subject.lower() or "test" in subject.lower():
                if "→" in subject:
                    # Extract coverage ratio if present
                    coverage_events[date] = subject

        return coverage_events

    def performance_improvements(self) -> list[dict[str, Any]]:
        """Extract performance improvement commits."""
        perf_commits = []
        keywords = ["faster", "optimize", "optim", "perf", "bench", "latency", "throughput"]
        for commit in self.commits:
            subject = commit["subject"].lower()
            if any(kw in subject for kw in keywords):
                perf_commits.append(commit)
        return sorted(perf_commits, key=lambda x: x["date"], reverse=True)

    def generate_report(self) -> None:
        """Generate and print growth report."""
        print("\n" + "=" * 70)
        print("AGENTOP GIT GROWTH ANALYSIS")
        print("=" * 70)

        print(f"\n📊 Total Commits: {len(self.commits)}")
        if self.commits:
            earliest = min(self.commits, key=lambda x: x["date"])
            latest = max(self.commits, key=lambda x: x["date"])
            duration = (latest["date"] - earliest["date"]).days
            print(
                f"📅 Time Span: {earliest['date'].strftime('%Y-%m-%d')} → {latest['date'].strftime('%Y-%m-%d')} ({duration} days)"
            )

        print("\n📈 Commits by Week:")
        weeks = self.commits_by_week()
        for week in sorted(weeks.keys(), reverse=True)[:10]:
            print(f"  {week}: {weeks[week]:2d} commits")

        print("\n✨ Feature Commits (Top 15):")
        for commit in self.feature_commits()[:15]:
            date = commit["date"].strftime("%Y-%m-%d")
            subject = commit["subject"][:60]
            print(f"  {date} — {subject}")

        print("\n⚡ Performance Improvements:")
        perf = self.performance_improvements()
        if perf:
            for commit in perf[:10]:
                date = commit["date"].strftime("%Y-%m-%d")
                subject = commit["subject"][:60]
                print(f"  {date} — {subject}")
        else:
            print("  (No explicit performance commits found)")

        print("\n🧪 Test Coverage Milestones:")
        coverage = self.estimate_test_coverage_growth()
        for date in sorted(coverage.keys(), reverse=True)[:10]:
            event = coverage[date][:70]
            print(f"  {date} — {event}")

        print("\n" + "=" * 70)

    def export_json(self, output_file: str = "growth_report.json") -> None:
        """Export growth data as JSON for dashboards."""
        data = {
            "total_commits": len(self.commits),
            "date_range": {
                "start": min(c["date"] for c in self.commits).isoformat() if self.commits else None,
                "end": max(c["date"] for c in self.commits).isoformat() if self.commits else None,
            },
            "commits_by_week": self.commits_by_week(),
            "feature_commits": [
                {
                    "date": c["date"].isoformat(),
                    "hash": c["hash"][:8],
                    "subject": c["subject"],
                }
                for c in self.feature_commits()[:20]
            ],
            "performance_improvements": [
                {
                    "date": c["date"].isoformat(),
                    "hash": c["hash"][:8],
                    "subject": c["subject"],
                }
                for c in self.performance_improvements()[:10]
            ],
        }

        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\n✅ Report exported to {output_file}")


def main():
    """Run analyzer."""
    analyzer = GitGrowthAnalyzer(repo_path=".")
    analyzer.generate_report()
    analyzer.export_json("reports/growth_report.json")


if __name__ == "__main__":
    main()
