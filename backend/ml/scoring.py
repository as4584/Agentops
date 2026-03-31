"""
Scoring Methods — Exact match, rubric, agent-judge, golden tasks.
=================================================================
Provides pluggable scoring strategies for LLM output evaluation.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger

# ── Scorer Protocol ──────────────────────────────────────


class Scorer(Protocol):
    """Interface for all scoring strategies."""

    def score(self, expected: str, actual: str, context: dict[str, Any]) -> ScoringResult: ...


@dataclass
class ScoringResult:
    """Result from any scorer."""

    method: str
    score: float  # 0.0 – 1.0
    passed: bool
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Exact Match Scorer ───────────────────────────────────


class ExactMatchScorer:
    """Binary exact match (case-insensitive by default)."""

    def __init__(self, case_sensitive: bool = False, strip_whitespace: bool = True) -> None:
        self.case_sensitive = case_sensitive
        self.strip_whitespace = strip_whitespace

    def score(self, expected: str, actual: str, context: dict[str, Any] | None = None) -> ScoringResult:
        e = expected
        a = actual
        if self.strip_whitespace:
            e = e.strip()
            a = a.strip()
        if not self.case_sensitive:
            e = e.lower()
            a = a.lower()
        match = e == a
        return ScoringResult(
            method="exact_match",
            score=1.0 if match else 0.0,
            passed=match,
            reasoning="Exact match" if match else f"Expected '{expected[:100]}' got '{actual[:100]}'",
        )


# ── Rubric Scorer ────────────────────────────────────────


@dataclass
class RubricCriterion:
    """A single rubric criterion with weight."""

    name: str
    description: str
    weight: float = 1.0
    check_type: str = "contains"  # contains, regex, length, keyword_count
    check_value: Any = ""


class RubricScorer:
    """Score output against a multi-criteria rubric."""

    def __init__(self, criteria: list[dict[str, Any]] | None = None) -> None:
        self.criteria: list[RubricCriterion] = []
        if criteria:
            for c in criteria:
                self.criteria.append(RubricCriterion(**c))

    def score(self, expected: str, actual: str, context: dict[str, Any] | None = None) -> ScoringResult:
        if not self.criteria:
            return ScoringResult(
                method="rubric",
                score=1.0,
                passed=True,
                reasoning="No criteria defined",
            )

        total_weight = sum(c.weight for c in self.criteria)
        weighted_score = 0.0
        details: list[str] = []

        for criterion in self.criteria:
            met = self._check_criterion(criterion, actual)
            if met:
                weighted_score += criterion.weight
                details.append(f"✓ {criterion.name}")
            else:
                details.append(f"✗ {criterion.name}: {criterion.description}")

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0
        return ScoringResult(
            method="rubric",
            score=final_score,
            passed=final_score >= 0.7,
            reasoning="; ".join(details),
            metadata={"criteria_count": len(self.criteria), "met_count": sum(1 for d in details if d.startswith("✓"))},
        )

    def _check_criterion(self, criterion: RubricCriterion, actual: str) -> bool:
        check = criterion.check_type
        val = criterion.check_value
        actual_lower = actual.lower()

        if check == "contains":
            return str(val).lower() in actual_lower
        elif check == "not_contains":
            return str(val).lower() not in actual_lower
        elif check == "regex":
            return bool(re.search(str(val), actual, re.IGNORECASE))
        elif check == "min_length":
            return len(actual) >= int(val)
        elif check == "max_length":
            return len(actual) <= int(val)
        elif check == "keyword_count":
            keywords = val if isinstance(val, list) else [val]
            found = sum(1 for kw in keywords if str(kw).lower() in actual_lower)
            return found >= len(keywords)
        return False


# ── Agent-as-Judge Scorer ────────────────────────────────


class AgentJudgeScorer:
    """Uses an LLM (via callback) to judge output quality.

    The judge_fn is a callable that takes a prompt and returns a score response.
    This avoids coupling to a specific LLM client.
    """

    def __init__(
        self,
        judge_fn: Any | None = None,  # Callable[[str], str]
        judge_prompt_template: str = "",
    ) -> None:
        self.judge_fn = judge_fn
        self.template = judge_prompt_template or self._default_template()

    def score(self, expected: str, actual: str, context: dict[str, Any] | None = None) -> ScoringResult:
        if not self.judge_fn:
            return ScoringResult(
                method="agent_judge",
                score=0.5,
                passed=False,
                reasoning="No judge function configured — cannot score",
            )

        prompt = self.template.format(
            expected=expected[:1500],
            actual=actual[:1500],
            task=context.get("task", "general") if context else "general",
        )

        try:
            response = self.judge_fn(prompt)
            parsed = self._parse_judge_response(response)
            return ScoringResult(
                method="agent_judge",
                score=parsed["score"],
                passed=parsed["score"] >= 0.7,
                reasoning=parsed["reasoning"],
                metadata={"raw_response": response[:500]},
            )
        except Exception as e:
            logger.warning(f"[AgentJudge] Error: {e}")
            return ScoringResult(
                method="agent_judge",
                score=0.0,
                passed=False,
                reasoning=f"Judge error: {e}",
            )

    def _parse_judge_response(self, response: str) -> dict[str, Any]:
        """Extract score and reasoning from judge response."""
        # Try JSON format first
        try:
            data = json.loads(response)
            return {
                "score": float(data.get("score", 0)),
                "reasoning": data.get("reasoning", ""),
            }
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to extract a numeric score
        score_match = re.search(r"(?:score|rating)[:\s]*([0-9]*\.?[0-9]+)", response, re.IGNORECASE)
        if score_match:
            raw_score = float(score_match.group(1))
            # Normalize to 0-1 if it looks like 0-10 or 0-100
            if raw_score > 1.0:
                raw_score = raw_score / 10.0 if raw_score <= 10 else raw_score / 100.0
            return {"score": min(1.0, max(0.0, raw_score)), "reasoning": response[:200]}

        return {"score": 0.5, "reasoning": f"Could not parse judge response: {response[:200]}"}

    @staticmethod
    def _default_template() -> str:
        return (
            "You are an expert evaluator. Score the following output on a scale of 0.0 to 1.0.\n\n"
            "Task: {task}\n\n"
            "Expected output:\n{expected}\n\n"
            "Actual output:\n{actual}\n\n"
            'Respond with JSON: {{"score": <float>, "reasoning": "<explanation>"}}'
        )


# ── Golden Task Registry ─────────────────────────────────


@dataclass
class GoldenTask:
    """A curated reference task with known-correct output for regression testing."""

    task_id: str
    task_type: str  # tool_selection, retrieval, code, summarization, etc.
    description: str
    input_prompt: str
    expected_output: str
    scoring_method: str = "exact_match"  # exact_match, rubric, agent_judge
    rubric_criteria: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    difficulty: str = "medium"  # easy, medium, hard

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoldenTaskRegistry:
    """Manages a curated set of golden tasks for regression testing."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or (ML_EXPERIMENTS_DIR / "golden_tasks")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, GoldenTask] = {}
        self._load_tasks()

    def add_task(self, task_data: dict[str, Any]) -> str:
        """Add a golden task. Returns task_id."""
        task = GoldenTask(**task_data)
        self._tasks[task.task_id] = task
        self._save_task(task)
        logger.info(f"[GoldenTasks] Added: {task.task_id} ({task.task_type})")
        return task.task_id

    def get_task(self, task_id: str) -> dict[str, Any]:
        if task_id not in self._tasks:
            raise KeyError(f"Golden task not found: {task_id}")
        return self._tasks[task_id].to_dict()

    def list_tasks(
        self,
        task_type: str | None = None,
        difficulty: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        tasks = list(self._tasks.values())
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        if difficulty:
            tasks = [t for t in tasks if t.difficulty == difficulty]
        if tags:
            tag_set = set(tags)
            tasks = [t for t in tasks if tag_set.intersection(set(t.tags))]
        return [t.to_dict() for t in tasks]

    def remove_task(self, task_id: str) -> None:
        if task_id in self._tasks:
            del self._tasks[task_id]
            path = self._storage_dir / f"{task_id}.json"
            if path.exists():
                path.unlink()

    def score_against_golden(self, task_id: str, actual_output: str) -> ScoringResult:
        """Score an actual output against a golden task's expected output."""
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(f"Golden task not found: {task_id}")

        scorer: Any
        if task.scoring_method == "rubric" and task.rubric_criteria:
            scorer = RubricScorer(criteria=task.rubric_criteria)
        else:
            scorer = ExactMatchScorer()

        return scorer.score(task.expected_output, actual_output, task.context)

    def _save_task(self, task: GoldenTask) -> None:
        path = self._storage_dir / f"{task.task_id}.json"
        path.write_text(json.dumps(task.to_dict(), indent=2))

    def _load_tasks(self) -> None:
        for f in self._storage_dir.glob("*.json"):
            data = json.loads(f.read_text())
            task = GoldenTask(**data)
            self._tasks[task.task_id] = task
