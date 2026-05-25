# Four-Phase Protocol — Agentop Implementation

> Adapted from Ordo AI-native project management discipline.
> Canonical reference for all agents performing multi-step tasks.

## Overview

Every non-trivial task MUST follow four sequential phases before execution.
Skipping phases produces ungrounded outputs and architectural drift.

## Phase I — Spec

**Purpose:** Lock the problem definition and acceptance criteria.

**Required outputs:**
- Problem statement (one sentence)
- Acceptance criteria (testable, enumerated)
- Scope boundary (what is explicitly OUT of scope)
- Confidence classification (which lane: development, evaluation, architecture, positioning)

**Rules:**
- No code may be written during Phase I.
- If confidence in lane classification is below 0.65, ask exactly one clarifying question.
- All factual claims must cite a source: file path, tool output, or corpus chunk.
- Claims without source are labeled INFERRED and capped at 0.70 confidence.

## Phase II — Blueprint

**Purpose:** Design the solution before writing any code.

**Required outputs:**
- File list (which files will be created or modified)
- Dependency map (what existing code is affected)
- Test plan (TDD: which tests will be written FIRST)
- Risk assessment (what could break, rated LOW/MEDIUM/HIGH/CRITICAL)

**Rules:**
- Run impact analysis on every symbol you plan to modify.
- If any dependency has HIGH or CRITICAL risk, flag it before proceeding.
- Blueprint must fit in a single document — if it doesn't, split the task.

## Phase III — Implementation

**Purpose:** Execute the blueprint with test-driven development.

**Required outputs:**
- Failing tests written first (TDD red phase)
- Implementation code (TDD green phase)
- All tests passing (TDD verify phase)

**Rules:**
- Write the failing test BEFORE the implementation.
- Each implementation change must make exactly one test pass.
- Never write code that doesn't have a corresponding test.
- Commit after each green phase (conventional commit format).

## Phase IV — QA

**Purpose:** Verify the implementation meets Phase I acceptance criteria.

**Required outputs:**
- All acceptance criteria checked (pass/fail)
- Regression test run (full suite, no new failures)
- Coverage delta (did coverage increase or decrease?)
- Quantitative snapshot (test count, pass rate, coverage %)

**Rules:**
- If any acceptance criterion fails, return to Phase III.
- If coverage decreased, justify why or add tests.
- Record the quantitative snapshot for sprint tracking.

## Anti-Patterns

1. **Spec-skip:** Jumping to code without Phase I → produces ungrounded implementations.
2. **Blueprint-skip:** No file list or test plan → causes regressions and scope creep.
3. **Test-after:** Writing tests after implementation → tests confirm bugs instead of preventing them.
4. **QA-skip:** Not running full regression → silent breakage in unrelated systems.
5. **Confidence inflation:** Claiming high confidence on inferred knowledge → degrades trust scoring.

## Integration with Epistemic Session

Every Phase III action should register claims via EpistemicSession:
- TOOL_OUTPUT (confidence up to 1.0) — from tool execution results
- CORPUS_RETRIEVED (up to 0.85) — from knowledge base search
- INSPECTED_FILE (up to 0.95) — from reading actual source code
- INFERRED (up to 0.70) — from reasoning without direct evidence
- PARAMETRIC (hard cap 0.50) — from model knowledge only (INV-02)

Empty sessions (no claims registered) are FLAGGED per governance §6.
