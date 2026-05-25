# Evaluation Discipline — Agentop Implementation

> Adapted from Ordo evaluation-driven development methodology.
> Canonical reference for measuring and improving agent quality.

## Core Principle

Every change must be measured. Unmeasured changes are invisible changes.
Invisible changes accumulate into uncontrolled drift.

## Quantitative Metrics

### Test Health
| Metric | Description | Target |
|--------|-------------|--------|
| Test count | Total collected tests across all suites | Monotonically increasing |
| Pass rate | Tests passing / tests collected | ≥ 99% (excluding known failures) |
| Coverage | Lines covered / total lines | ≥ 58% (CI gate) |
| Coverage delta | Change in coverage per sprint | ≥ 0% (never decrease) |

### Code Quality
| Metric | Description | Target |
|--------|-------------|--------|
| Ruff violations | Lint errors from `ruff check` | 0 |
| Type errors | Errors from `mypy` | 0 |
| Audit findings | Open HIGH/CRITICAL severity findings | 0 |

### Agent Quality
| Metric | Description | Target |
|--------|-------------|--------|
| Routing accuracy | Correct agent selected / total requests | ≥ 85% on golden set |
| Epistemic violations | FLAGGED sessions / total sessions | ≤ 5% |
| Tool call accuracy | Correct tool + args / total tool calls | ≥ 90% |

## Golden Evaluation Set

A golden set is a curated collection of test cases with known-correct answers.
It is the ground truth for measuring agent quality.

### Construction Rules
1. Start with 20 canonical cases covering each agent boundary.
2. Include 30% adversarial cases (ambiguous, multi-agent, red-line).
3. Every case must have: user_message, expected_agent, expected_tools, difficulty.
4. Cases are immutable once added — add new cases, never modify existing ones.
5. Store golden set in `data/training/golden_eval/` as JSONL.

### Boundary Cases (Known Weak)
These agent boundaries have historically low routing accuracy:
- `knowledge_agent` ↔ `soul_core` (philosophical vs factual questions)
- `monitor_agent` ↔ `it_agent` (observability vs infrastructure)
- `code_review_agent` ↔ `security_agent` (code quality vs vulnerability)

## Sprint Tracking

Each sprint produces a quantitative snapshot:

```json
{
  "sprint": 5,
  "timestamp": "2026-04-17T14:30:00Z",
  "tests": {"collected": 2639, "passed": 2606, "failed": 1, "skipped": 5},
  "coverage": {"overall": 31, "backend": 74},
  "audit_findings": {"high": 0, "medium": 0, "low": 1},
  "knowledge_docs": {"seeded": 5, "collections": ["knowledge_agent"]},
  "delta": {
    "tests_added": 2,
    "coverage_change": "+0.1%",
    "findings_closed": 3
  }
}
```

Sprint snapshots are stored in `data/benchmarks/sprint_snapshots.jsonl`.

## Evaluation Loop

1. **Before sprint:** capture baseline snapshot.
2. **During sprint:** track tests added, findings closed, features implemented.
3. **After sprint:** capture new snapshot, compute deltas.
4. **Review:** if any metric regressed, explain why in commit message.

## Regression Prevention

- Every bug fix MUST include a regression test.
- Every new feature MUST include at least one happy-path and one error-path test.
- Coverage must not decrease without documented justification.
- The full test suite runs before every commit: `pytest backend/tests/ deerflow/tests/ -x --tb=short -q`.
