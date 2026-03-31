"""
LLM Eval Framework — Evaluate LLM outputs systematically.
==========================================================
Evaluates:
- Did it choose the right tool?
- Did it retrieve the right files/docs?
- Did it answer correctly?
- Did it follow constraints?
- Did it avoid hallucinating?
- How long did it take?
- How many tokens did it burn?

Integrates with MLflowTracker for persistent logging.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger


class EvalDimension(str, Enum):
    """Dimensions we evaluate LLM outputs on."""

    TOOL_SELECTION = "tool_selection"
    RETRIEVAL_ACCURACY = "retrieval_accuracy"
    ANSWER_CORRECTNESS = "answer_correctness"
    CONSTRAINT_FOLLOWING = "constraint_following"
    HALLUCINATION = "hallucination"
    LATENCY = "latency"
    TOKEN_EFFICIENCY = "token_efficiency"
    CODE_QUALITY = "code_quality"
    FORMAT_COMPLIANCE = "format_compliance"


@dataclass
class EvalResult:
    """Result of a single evaluation."""

    dimension: str
    score: float  # 0.0 – 1.0
    pass_fail: bool
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalCase:
    """A single evaluation case (input → expected → actual)."""

    case_id: str
    task_type: str
    input_prompt: str
    expected_output: str
    actual_output: str
    model: str
    temperature: float = 0.7
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def overall_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def passed(self) -> bool:
        return all(r.pass_fail for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["overall_score"] = self.overall_score
        d["passed"] = self.passed
        return d


class LLMEvalFramework:
    """Orchestrates evaluation of LLM outputs across multiple dimensions."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or (ML_EXPERIMENTS_DIR / "eval_results")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._evaluators: dict[str, Any] = {}

    def evaluate(
        self,
        case: EvalCase,
        dimensions: list[EvalDimension] | None = None,
    ) -> EvalCase:
        """Run all applicable evaluations on a case."""
        dims = dimensions or list(EvalDimension)
        for dim in dims:
            evaluator = self._get_evaluator(dim)
            result = evaluator(case)
            case.results.append(result)
        self._persist_case(case)
        logger.info(
            f"[LLMEval] {case.case_id}: score={case.overall_score:.2f} passed={case.passed} dims={len(case.results)}"
        )
        return case

    def evaluate_tool_selection(self, case: EvalCase) -> EvalResult:
        """Did the LLM choose the right tool?"""
        expected_tool = case.context.get("expected_tool", "")
        actual_tool = case.context.get("actual_tool", "")
        if not expected_tool:
            return EvalResult(
                dimension=EvalDimension.TOOL_SELECTION,
                score=1.0,
                pass_fail=True,
                details="No expected tool specified — skipped",
            )
        match = expected_tool.lower().strip() == actual_tool.lower().strip()
        return EvalResult(
            dimension=EvalDimension.TOOL_SELECTION,
            score=1.0 if match else 0.0,
            pass_fail=match,
            details=f"Expected: {expected_tool}, Got: {actual_tool}",
        )

    def evaluate_retrieval(self, case: EvalCase) -> EvalResult:
        """Did it retrieve the right files/docs?"""
        expected_docs = set(case.context.get("expected_docs", []))
        actual_docs = set(case.context.get("actual_docs", []))
        if not expected_docs:
            return EvalResult(
                dimension=EvalDimension.RETRIEVAL_ACCURACY,
                score=1.0,
                pass_fail=True,
                details="No expected docs specified — skipped",
            )
        if not actual_docs:
            return EvalResult(
                dimension=EvalDimension.RETRIEVAL_ACCURACY,
                score=0.0,
                pass_fail=False,
                details="No docs retrieved",
            )
        intersection = expected_docs & actual_docs
        precision = len(intersection) / len(actual_docs) if actual_docs else 0.0
        recall = len(intersection) / len(expected_docs) if expected_docs else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        return EvalResult(
            dimension=EvalDimension.RETRIEVAL_ACCURACY,
            score=f1,
            pass_fail=recall >= 0.8,
            details=f"P={precision:.2f} R={recall:.2f} F1={f1:.2f}",
            metadata={"precision": precision, "recall": recall, "f1": f1},
        )

    def evaluate_correctness(self, case: EvalCase) -> EvalResult:
        """Did it answer correctly? Uses exact + fuzzy matching."""
        expected = case.expected_output.strip().lower()
        actual = case.actual_output.strip().lower()
        if not expected:
            return EvalResult(
                dimension=EvalDimension.ANSWER_CORRECTNESS,
                score=1.0,
                pass_fail=True,
                details="No expected output — skipped",
            )
        # Exact match
        if expected == actual:
            return EvalResult(
                dimension=EvalDimension.ANSWER_CORRECTNESS,
                score=1.0,
                pass_fail=True,
                details="Exact match",
            )
        # Containment check
        if expected in actual:
            return EvalResult(
                dimension=EvalDimension.ANSWER_CORRECTNESS,
                score=0.8,
                pass_fail=True,
                details="Expected contained in actual",
            )
        # Token overlap
        expected_tokens = set(expected.split())
        actual_tokens = set(actual.split())
        if expected_tokens and actual_tokens:
            overlap = len(expected_tokens & actual_tokens) / len(expected_tokens)
            return EvalResult(
                dimension=EvalDimension.ANSWER_CORRECTNESS,
                score=overlap,
                pass_fail=overlap >= 0.7,
                details=f"Token overlap: {overlap:.2f}",
            )
        return EvalResult(
            dimension=EvalDimension.ANSWER_CORRECTNESS,
            score=0.0,
            pass_fail=False,
            details="No match",
        )

    def evaluate_constraints(self, case: EvalCase) -> EvalResult:
        """Did it follow constraints (max length, required format, etc.)?"""
        constraints = case.context.get("constraints", {})
        if not constraints:
            return EvalResult(
                dimension=EvalDimension.CONSTRAINT_FOLLOWING,
                score=1.0,
                pass_fail=True,
                details="No constraints specified",
            )
        violations = []
        len(constraints)
        passed_count = 0
        max_length = constraints.get("max_length")
        if max_length and len(case.actual_output) > int(max_length):
            violations.append(f"Output exceeds max_length ({len(case.actual_output)} > {max_length})")
        else:
            passed_count += 1 if max_length else 0

        required_keywords = constraints.get("required_keywords", [])
        for kw in required_keywords:
            if kw.lower() in case.actual_output.lower():
                passed_count += 1
            else:
                violations.append(f"Missing required keyword: {kw}")

        forbidden_keywords = constraints.get("forbidden_keywords", [])
        for kw in forbidden_keywords:
            if kw.lower() in case.actual_output.lower():
                violations.append(f"Contains forbidden keyword: {kw}")
            else:
                passed_count += 1

        total_checks = (1 if max_length else 0) + len(required_keywords) + len(forbidden_keywords)
        score = passed_count / total_checks if total_checks > 0 else 1.0
        return EvalResult(
            dimension=EvalDimension.CONSTRAINT_FOLLOWING,
            score=score,
            pass_fail=len(violations) == 0,
            details="; ".join(violations) if violations else "All constraints met",
        )

    def evaluate_hallucination(self, case: EvalCase) -> EvalResult:
        """Basic hallucination detection (checks for known-false claims)."""
        known_facts = case.context.get("known_facts", [])
        if not known_facts:
            return EvalResult(
                dimension=EvalDimension.HALLUCINATION,
                score=1.0,
                pass_fail=True,
                details="No known facts to check against",
            )
        contradictions = []
        for fact in known_facts:
            negation = fact.get("negation", "")
            if negation and negation.lower() in case.actual_output.lower():
                contradictions.append(f"Contradicts fact: {fact.get('claim', '')}")

        score = 1.0 - (len(contradictions) / len(known_facts)) if known_facts else 1.0
        return EvalResult(
            dimension=EvalDimension.HALLUCINATION,
            score=max(0.0, score),
            pass_fail=len(contradictions) == 0,
            details="; ".join(contradictions) if contradictions else "No hallucinations detected",
        )

    def evaluate_latency(self, case: EvalCase) -> EvalResult:
        """Was the response fast enough?"""
        threshold_ms = case.context.get("latency_threshold_ms", 2000)
        score = min(1.0, threshold_ms / max(case.latency_ms, 1))
        return EvalResult(
            dimension=EvalDimension.LATENCY,
            score=score,
            pass_fail=case.latency_ms <= threshold_ms,
            details=f"{case.latency_ms:.0f}ms (threshold: {threshold_ms}ms)",
        )

    def evaluate_token_efficiency(self, case: EvalCase) -> EvalResult:
        """Token burn analysis."""
        max_tokens = case.context.get("max_tokens", 4096)
        total_tokens = case.tokens_in + case.tokens_out
        efficiency = 1.0 - (total_tokens / max(max_tokens, 1))
        efficiency = max(0.0, min(1.0, efficiency))
        return EvalResult(
            dimension=EvalDimension.TOKEN_EFFICIENCY,
            score=efficiency,
            pass_fail=total_tokens <= max_tokens,
            details=f"Used {total_tokens} of {max_tokens} token budget",
        )

    def get_results(
        self,
        task_type: str | None = None,
        model: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve stored eval results."""
        results: list[dict[str, Any]] = []
        for f in sorted(self._storage_dir.glob("*.json"), reverse=True):
            if len(results) >= limit:
                break
            data = json.loads(f.read_text())
            if task_type and data.get("task_type") != task_type:
                continue
            if model and data.get("model") != model:
                continue
            results.append(data)
        return results

    def get_summary(
        self,
        task_type: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate summary across eval results."""
        results = self.get_results(task_type=task_type, model=model, limit=10000)
        if not results:
            return {"total": 0, "passed": 0, "failed": 0, "avg_score": 0.0}

        total = len(results)
        passed = sum(1 for r in results if r.get("passed", False))
        scores = [r.get("overall_score", 0.0) for r in results]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Per-dimension breakdown
        dim_scores: dict[str, list[float]] = {}
        for r in results:
            for er in r.get("results", []):
                dim = er.get("dimension", "unknown")
                dim_scores.setdefault(dim, []).append(er.get("score", 0.0))

        dim_summary = {}
        for dim, s in dim_scores.items():
            dim_summary[dim] = {
                "avg": sum(s) / len(s),
                "min": min(s),
                "max": max(s),
                "count": len(s),
            }

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "avg_score": avg_score,
            "dimensions": dim_summary,
        }

    def _get_evaluator(self, dim: EvalDimension) -> Any:
        """Route to the correct evaluator method by dimension."""
        evaluators = {
            EvalDimension.TOOL_SELECTION: self.evaluate_tool_selection,
            EvalDimension.RETRIEVAL_ACCURACY: self.evaluate_retrieval,
            EvalDimension.ANSWER_CORRECTNESS: self.evaluate_correctness,
            EvalDimension.CONSTRAINT_FOLLOWING: self.evaluate_constraints,
            EvalDimension.HALLUCINATION: self.evaluate_hallucination,
            EvalDimension.LATENCY: self.evaluate_latency,
            EvalDimension.TOKEN_EFFICIENCY: self.evaluate_token_efficiency,
        }
        return evaluators.get(dim, self._noop_evaluator)

    @staticmethod
    def _noop_evaluator(case: EvalCase) -> EvalResult:
        return EvalResult(
            dimension="unknown",
            score=1.0,
            pass_fail=True,
            details="No evaluator for this dimension",
        )

    def _persist_case(self, case: EvalCase) -> None:
        out_path = self._storage_dir / f"{case.case_id}.json"
        out_path.write_text(json.dumps(case.to_dict(), indent=2, default=str))
