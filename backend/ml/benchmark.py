"""
Benchmark Suite — Regression testing and capability benchmarks.
===============================================================
Covers:
- Golden task regression suites
- Website generation benchmarks (vs golden references)
- Multi-task capability benchmarks (drafting, planning, summarizing,
  extracting, classification, tool selection, code assistance)

Integrates with GoldenTaskRegistry and MLflowTracker for tracking.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger


@dataclass
class BenchmarkCase:
    """A single benchmark test case."""
    case_id: str
    suite_id: str
    task_type: str
    input_prompt: str
    expected_output: str = ""
    golden_reference: str = ""  # For comparison benchmarks (e.g., golden website HTML)
    timeout_ms: int = 30000
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    """Result from running a benchmark case."""
    case_id: str
    suite_id: str
    model: str
    actual_output: str = ""
    passed: bool = False
    score: float = 0.0
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""
    scores_by_dimension: dict[str, float] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SuiteReport:
    """Aggregated report for a benchmark suite run."""
    suite_id: str
    run_id: str
    model: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0
    total_tokens: int = 0
    pass_rate: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    regressions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BenchmarkSuite:
    """Manages benchmark test suites and regression detection."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._storage_dir = storage_dir or (ML_EXPERIMENTS_DIR / "benchmarks")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._suites_dir = self._storage_dir / "suites"
        self._suites_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir = self._storage_dir / "results"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._baselines_dir = self._storage_dir / "baselines"
        self._baselines_dir.mkdir(parents=True, exist_ok=True)

    # ── Suite Management ─────────────────────────────────

    def create_suite(
        self,
        suite_id: str,
        name: str,
        cases: list[dict[str, Any]],
        description: str = "",
    ) -> str:
        """Create a benchmark suite with test cases."""
        suite_data = {
            "suite_id": suite_id,
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_count": len(cases),
            "cases": cases,
        }
        path = self._suites_dir / f"{suite_id}.json"
        path.write_text(json.dumps(suite_data, indent=2))
        logger.info(f"[Benchmark] Created suite: {suite_id} ({len(cases)} cases)")
        return suite_id

    def get_suite(self, suite_id: str) -> dict[str, Any]:
        path = self._suites_dir / f"{suite_id}.json"
        if not path.exists():
            raise KeyError(f"Suite not found: {suite_id}")
        return json.loads(path.read_text())

    def list_suites(self) -> list[dict[str, Any]]:
        suites = []
        for f in sorted(self._suites_dir.glob("*.json")):
            data = json.loads(f.read_text())
            suites.append({
                "suite_id": data["suite_id"],
                "name": data["name"],
                "case_count": data.get("case_count", 0),
                "description": data.get("description", ""),
            })
        return suites

    # ── Running Benchmarks ───────────────────────────────

    def run_suite(
        self,
        suite_id: str,
        model: str,
        runner_fn: Any,  # Callable[[BenchmarkCase], BenchmarkResult]
    ) -> SuiteReport:
        """Execute all cases in a suite using the provided runner function."""
        suite_data = self.get_suite(suite_id)
        cases = [BenchmarkCase(**c) for c in suite_data["cases"]]

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        run_id = f"{suite_id}_{model}_{ts}"

        report = SuiteReport(
            suite_id=suite_id,
            run_id=run_id,
            model=model,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        for case in cases:
            try:
                result = runner_fn(case)
                result.suite_id = suite_id
                result.model = model
                report.results.append(result.to_dict())
                report.total_cases += 1
                if result.passed:
                    report.passed += 1
                else:
                    report.failed += 1
            except Exception as e:
                report.errors += 1
                report.total_cases += 1
                report.results.append(
                    BenchmarkResult(
                        case_id=case.case_id,
                        suite_id=suite_id,
                        model=model,
                        error=str(e),
                    ).to_dict()
                )

        # Compute aggregates
        valid_results = [r for r in report.results if not r.get("error")]
        if valid_results:
            report.avg_score = sum(r["score"] for r in valid_results) / len(valid_results)
            report.avg_latency_ms = sum(r["latency_ms"] for r in valid_results) / len(valid_results)
            report.total_tokens = sum(r.get("tokens_in", 0) + r.get("tokens_out", 0) for r in valid_results)
        report.pass_rate = report.passed / report.total_cases if report.total_cases > 0 else 0.0
        report.completed_at = datetime.now(timezone.utc).isoformat()

        # Check for regressions against baseline
        report.regressions = self._detect_regressions(suite_id, model, report)

        # Persist report
        report_path = self._results_dir / f"{run_id}.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))

        logger.info(
            f"[Benchmark] {suite_id} ({model}): {report.passed}/{report.total_cases} passed, "
            f"score={report.avg_score:.2f}, regressions={len(report.regressions)}"
        )
        return report

    # ── Baselines and Regression Detection ───────────────

    def set_baseline(self, suite_id: str, model: str, report: SuiteReport) -> None:
        """Set a benchmark run as the baseline for regression detection."""
        key = f"{suite_id}__{model}"
        path = self._baselines_dir / f"{key}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2))
        logger.info(f"[Benchmark] Set baseline: {key} (pass_rate={report.pass_rate:.2f})")

    def get_baseline(self, suite_id: str, model: str) -> Optional[SuiteReport]:
        key = f"{suite_id}__{model}"
        path = self._baselines_dir / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return SuiteReport(**data)

    def _detect_regressions(
        self,
        suite_id: str,
        model: str,
        current: SuiteReport,
    ) -> list[str]:
        """Compare current run against baseline to find regressions."""
        baseline = self.get_baseline(suite_id, model)
        if not baseline:
            return []

        regressions = []

        # Pass rate regression
        if current.pass_rate < baseline.pass_rate - 0.05:
            regressions.append(
                f"Pass rate dropped: {baseline.pass_rate:.2f} → {current.pass_rate:.2f}"
            )

        # Average score regression
        if current.avg_score < baseline.avg_score - 0.05:
            regressions.append(
                f"Avg score dropped: {baseline.avg_score:.2f} → {current.avg_score:.2f}"
            )

        # Latency regression (>20% increase)
        if baseline.avg_latency_ms > 0 and current.avg_latency_ms > baseline.avg_latency_ms * 1.2:
            regressions.append(
                f"Latency increased: {baseline.avg_latency_ms:.0f}ms → {current.avg_latency_ms:.0f}ms"
            )

        # Per-case regression (was passing, now failing)
        baseline_passed = {r["case_id"] for r in baseline.results if r.get("passed")}
        for r in current.results:
            if r.get("case_id") in baseline_passed and not r.get("passed"):
                regressions.append(f"Case regressed: {r['case_id']}")

        return regressions

    def get_history(
        self,
        suite_id: str,
        model: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get run history for a suite."""
        results = []
        pattern = f"{suite_id}_*"
        for f in sorted(self._results_dir.glob(f"{pattern}.json"), reverse=True):
            if len(results) >= limit:
                break
            data = json.loads(f.read_text())
            if model and data.get("model") != model:
                continue
            results.append({
                "run_id": data["run_id"],
                "model": data["model"],
                "pass_rate": data.get("pass_rate", 0),
                "avg_score": data.get("avg_score", 0),
                "avg_latency_ms": data.get("avg_latency_ms", 0),
                "total_cases": data.get("total_cases", 0),
                "regressions": len(data.get("regressions", [])),
                "completed_at": data.get("completed_at", ""),
            })
        return results

    # ── Built-in Benchmark Factories ─────────────────────

    @staticmethod
    def create_capability_suite() -> dict[str, Any]:
        """Create a default multi-capability benchmark suite."""
        cases = [
            {
                "case_id": "draft_email",
                "suite_id": "capabilities",
                "task_type": "drafting",
                "input_prompt": "Draft a professional email to a client requesting a meeting "
                                "to discuss project milestones for next quarter.",
                "tags": ["drafting", "communication"],
            },
            {
                "case_id": "plan_sprint",
                "suite_id": "capabilities",
                "task_type": "planning",
                "input_prompt": "Create a 2-week sprint plan for implementing user authentication "
                                "with OAuth2. Include tasks, estimates, and dependencies.",
                "tags": ["planning", "project_management"],
            },
            {
                "case_id": "summarize_doc",
                "suite_id": "capabilities",
                "task_type": "summarization",
                "input_prompt": "Summarize the key architectural decisions in this document: "
                                "System uses event-driven microservices with CQRS pattern. "
                                "Data stored in PostgreSQL for writes, Redis for read cache. "
                                "Message broker is RabbitMQ. Auth via JWT with refresh tokens. "
                                "Deployed on Kubernetes with Helm charts.",
                "expected_output": "event-driven microservices CQRS PostgreSQL Redis RabbitMQ JWT Kubernetes",
                "tags": ["summarization"],
            },
            {
                "case_id": "extract_entities",
                "suite_id": "capabilities",
                "task_type": "extraction",
                "input_prompt": "Extract all technical entities (tools, frameworks, languages) "
                                "from: 'We built the frontend in React with TypeScript, "
                                "backend in FastAPI with Python 3.12, deployed on AWS ECS.'",
                "expected_output": "React TypeScript FastAPI Python AWS ECS",
                "tags": ["extraction", "ner"],
            },
            {
                "case_id": "classify_intent",
                "suite_id": "capabilities",
                "task_type": "classification",
                "input_prompt": "Classify the intent: 'My deployment is failing with exit code 137'",
                "expected_output": "troubleshooting",
                "tags": ["classification"],
            },
            {
                "case_id": "select_tool",
                "suite_id": "capabilities",
                "task_type": "tool_selection",
                "input_prompt": "Given tools [safe_shell, file_reader, git_ops, db_query, webhook_send], "
                                "which tool should be used to: 'Check the latest git commits'?",
                "expected_output": "git_ops",
                "metadata": {"expected_tool": "git_ops"},
                "tags": ["tool_selection"],
            },
            {
                "case_id": "code_fastapi_endpoint",
                "suite_id": "capabilities",
                "task_type": "code_assistance",
                "input_prompt": "Write a FastAPI endpoint that accepts a POST with JSON body "
                                "containing 'name' and 'email', validates email format, "
                                "and returns a 201 with the created user.",
                "tags": ["code_assistance", "python", "fastapi"],
            },
        ]
        return {
            "suite_id": "capabilities",
            "name": "Multi-Capability Benchmark",
            "description": "Tests drafting, planning, summarizing, extracting, "
                           "classification, tool selection, and code assistance",
            "cases": cases,
        }

    @staticmethod
    def create_webgen_suite(golden_sites_dir: Optional[str] = None) -> dict[str, Any]:
        """Create a website generation benchmark suite."""
        cases = [
            {
                "case_id": "landing_page",
                "suite_id": "webgen",
                "task_type": "code_assistance",
                "input_prompt": "Generate a responsive landing page HTML for a SaaS product "
                                "called 'Agentop'. Include hero section, features grid, "
                                "pricing table, and footer. Use Tailwind CSS.",
                "tags": ["webgen", "html", "tailwind"],
                "metadata": {"min_length": 500, "required_elements": ["hero", "features", "pricing", "footer"]},
            },
            {
                "case_id": "dashboard_component",
                "suite_id": "webgen",
                "task_type": "code_assistance",
                "input_prompt": "Create a React dashboard component with a sidebar navigation, "
                                "top bar with search, and a main content area with a data table. "
                                "Use TypeScript and Tailwind CSS.",
                "tags": ["webgen", "react", "typescript"],
                "metadata": {"required_elements": ["sidebar", "topbar", "table"]},
            },
            {
                "case_id": "form_validation",
                "suite_id": "webgen",
                "task_type": "code_assistance",
                "input_prompt": "Build a multi-step form with client-side validation in Next.js. "
                                "Steps: personal info, address, payment. Include progress indicator "
                                "and back/next navigation.",
                "tags": ["webgen", "nextjs", "forms"],
                "metadata": {"required_elements": ["steps", "validation", "progress"]},
            },
        ]
        return {
            "suite_id": "webgen",
            "name": "Website Generation Benchmark",
            "description": "Tests ability to generate quality web code matching golden references",
            "cases": cases,
        }
