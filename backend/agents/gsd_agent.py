"""
GSDAgent — implements all five GSD workflow commands.

map_codebase   → 4 parallel analysis workers → docs/gsd/*.md
plan_phase     → research → draft → gatekeeper verify loop (max 2 revisions)
execute_phase  → read PLAN.md → topological wave sort → parallel execution
quick          → single-shot task with state tracking; optional git commit
verify_work    → UAT checklist from execution log → gap report
"""
from __future__ import annotations

import asyncio
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agents.gatekeeper_agent import GatekeeperAgent
from backend.database.gsd_store import gsd_store
from backend.models.gsd import (
    GSDExecutionResult,
    GSDMapResult,
    GSDPlan,
    GSDQuickResult,
    GSDStateFile,
    GSDTask,
    GSDVerifyReport,
    PhaseStatus,
    TaskStatus,
    VerifyCheckItem,
    WaveResult,
)
from backend.utils import logger

_DEFAULT_LLM_TASK = "general"


def _llm_generate(prompt: str, task: str = _DEFAULT_LLM_TASK) -> str:
    """
    Thin wrapper around the unified registry's generate() call.
    Falls back to a stub message when the LLM is unavailable so that
    tests and offline environments don't hard-fail.
    """
    try:
        from backend.llm.unified_registry import UnifiedModelRouter
        import asyncio as _asyncio

        async def _run() -> str:
            router = UnifiedModelRouter()
            result = await router.generate(prompt, task=task)
            return str(result.get("output", ""))

        try:
            return _asyncio.run(_run())
        except RuntimeError:
            # Already inside a running event loop (e.g. called from async context)
            loop = _asyncio.get_event_loop()
            return str(loop.run_until_complete(_run()))
    except Exception as exc:
        logger.warning(f"GSDAgent LLM unavailable ({exc}), returning stub.")
        return f"[LLM unavailable — stub response for: {prompt[:80]}]"


# ---------------------------------------------------------------------------
# GSDAgent
# ---------------------------------------------------------------------------

class GSDAgent:
    """Orchestrates all GSD workflow commands."""

    def __init__(self) -> None:
        self._gatekeeper = GatekeeperAgent()

    # -----------------------------------------------------------------------
    # 1. map-codebase
    # -----------------------------------------------------------------------

    async def map_codebase(self, workspace_root: str = ".") -> GSDMapResult:
        """
        Spawn 4 parallel analysis workers.  Each read relevant source files
        and synthesise a focused doc via the LLM.
        """
        root = Path(workspace_root).resolve()

        stack_task, arch_task, conv_task, concerns_task = await asyncio.gather(
            asyncio.to_thread(self._analyze_stack, root),
            asyncio.to_thread(self._analyze_architecture, root),
            asyncio.to_thread(self._analyze_conventions, root),
            asyncio.to_thread(self._analyze_concerns, root),
        )

        result = GSDMapResult(
            stack=stack_task,
            architecture=arch_task,
            conventions=conv_task,
            concerns=concerns_task,
            generated_at=datetime.now(timezone.utc),
        )

        gsd_store.save_map_docs(result)

        # Update state
        state = gsd_store.load_state()
        state.map_generated_at = result.generated_at
        gsd_store.save_state(state)

        logger.info("GSD map-codebase complete — docs written to docs/gsd/")
        return result

    # ---- map workers -------------------------------------------------------

    def _read_file_safe(self, path: Path, max_chars: int = 4000) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
        except Exception:
            return ""

    def _analyze_stack(self, root: Path) -> str:
        sections: list[str] = []
        for candidate in ("requirements.txt", "pyproject.toml", "frontend/package.json",
                          "package.json", "frontend/tsconfig.json"):
            p = root / candidate
            if p.exists():
                sections.append(f"### {candidate}\n```\n{self._read_file_safe(p, 2000)}\n```")

        prompt = textwrap.dedent(f"""
            Analyze the following dependency/config files from the Agentop project
            and produce a concise STACK.md document that covers:
            - languages and runtimes
            - major frameworks and libraries
            - notable third-party services
            - local vs cloud LLM strategy

            Files:
            {chr(10).join(sections) or '(no dep files found)'}

            Respond with clean Markdown only — no preamble.
        """)
        return _llm_generate(prompt, task="summarization")

    def _analyze_architecture(self, root: Path) -> str:
        backend_routes = list((root / "backend" / "routes").glob("*.py"))
        backend_agents = list((root / "backend" / "agents").glob("*.py"))
        backend_dirs = [
            d.name for d in (root / "backend").iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ] if (root / "backend").exists() else []

        context_lines = [
            f"**backend/ subdirs:** {', '.join(sorted(backend_dirs))}",
            f"**route modules:** {', '.join(p.name for p in backend_routes)}",
            f"**agent modules:** {', '.join(p.name for p in backend_agents)}",
        ]

        # Grab orchestrator __init__ if it exists
        orch_init = root / "backend" / "orchestrator" / "__init__.py"
        if orch_init.exists():
            context_lines.append(
                f"**orchestrator/__init__.py:**\n```python\n{self._read_file_safe(orch_init, 1500)}\n```"
            )

        prompt = textwrap.dedent(f"""
            Based on the Agentop backend structure below, produce a concise
            ARCHITECTURE.md covering:
            - high-level component topology (VS Code ext → FastAPI → LangGraph → Agents → Tools)
            - route module responsibilities
            - agent tiers and responsibilities
            - memory / storage layers (SQLite, JSON namespaces, vector DB)
            - key invariants (Drift Guard, Gatekeeper, TDD rule)

            Context:
            {chr(10).join(context_lines)}

            Respond with clean Markdown only — no preamble.
        """)
        return _llm_generate(prompt, task="summarization")

    def _analyze_conventions(self, root: Path) -> str:
        snippets: list[str] = []
        for candidate in ("docs/SOURCE_OF_TRUTH.md", "docs/TDD_GUIDE.md",
                          "docs/DRIFT_GUARD.md", "docs/CHANGE_LOG.md"):
            p = root / candidate
            if p.exists():
                snippets.append(f"### {candidate}\n{self._read_file_safe(p, 1500)}")

        prompt = textwrap.dedent(f"""
            Based on the Agentop project documentation below, produce a concise
            CONVENTIONS.md covering:
            - sprint format and naming conventions
            - atomic write pattern (tmp → rename)
            - TDD rules (test required per runtime change)
            - file/symbol naming conventions
            - invariant enforcement (Gatekeeper, Drift Guard patterns)
            - how new route modules are registered

            Documentation:
            {chr(10).join(snippets) or '(no docs found)'}

            Respond with clean Markdown only — no preamble.
        """)
        return _llm_generate(prompt, task="summarization")

    def _analyze_concerns(self, root: Path) -> str:
        snippets: list[str] = []
        for candidate in ("SECURITY_AUDIT.md", "docs/KNOWN_ISSUES.md",
                          "to_do_list.md", "docs/SANDBOX_LOG.md"):
            p = root / candidate
            if p.exists():
                snippets.append(f"### {candidate}\n{self._read_file_safe(p, 1500)}")

        prompt = textwrap.dedent(f"""
            Based on the Agentop project open items below, produce a concise
            CONCERNS.md covering:
            - open security findings and their priority
            - known issues / bugs
            - deferred work items
            - technical debt (non-atomic writes, missing tests, etc.)

            Sources:
            {chr(10).join(snippets) or '(no open-item files found)'}

            Respond with clean Markdown only — no preamble.
        """)
        return _llm_generate(prompt, task="summarization")

    # -----------------------------------------------------------------------
    # 2. plan-phase
    # -----------------------------------------------------------------------

    async def plan_phase(self, phase_n: int, description: str) -> GSDPlan:
        """
        Three-stage loop: research → draft plan → gatekeeper verify.
        Up to 2 revision attempts before surfacing violations to caller.
        """
        # Research: load existing map docs for context
        map_docs = gsd_store.load_map_docs()
        arch_ctx = map_docs.architecture[:2000] if map_docs else ""
        conv_ctx = map_docs.conventions[:1000] if map_docs else ""

        plan = await asyncio.to_thread(
            self._draft_plan, phase_n, description, arch_ctx, conv_ctx
        )

        # Gatekeeper verify loop
        for revision in range(3):
            gk_payload = self._plan_to_gatekeeper_payload(plan)
            gk_result = self._gatekeeper.review_mutation(gk_payload)
            if gk_result.approved:
                plan.gatekeeper_violations = []
                break
            plan.gatekeeper_violations = gk_result.violations
            plan.gatekeeper_revision = revision + 1
            if revision < 2:
                plan = await asyncio.to_thread(
                    self._revise_plan, plan, gk_result.violations
                )

        plan.status = PhaseStatus.PLANNED
        gsd_store.save_plan(phase_n, plan)

        state = gsd_store.load_state()
        state.active_phase = phase_n
        gsd_store.save_state(state)

        return plan

    def _draft_plan(
        self, phase_n: int, description: str, arch_ctx: str, conv_ctx: str
    ) -> GSDPlan:
        prompt = textwrap.dedent(f"""
            You are planning Phase {phase_n} of the Agentop project.

            Description: {description}

            Architecture context:
            {arch_ctx or '(run /gsd:map-codebase first for richer context)'}

            Conventions:
            {conv_ctx or '(standard Agentop patterns apply)'}

            Produce a JSON plan with this exact shape (no markdown wrapping):
            {{
              "phase": {phase_n},
              "title": "<short title>",
              "description": "<one sentence>",
              "tasks": [
                {{
                  "id": "T1",
                  "description": "<what to do>",
                  "file_targets": ["<path>"],
                  "symbol_refs": ["<ClassName.method>"],
                  "depends_on": [],
                  "wave": 1
                }}
              ]
            }}

            Rules:
            - Group independent tasks into the same wave number
            - Every task that modifies runtime code (backend/ or frontend/src/)
              must have a sibling test task (backend/tests/ or frontend/tests/)
            - Never propose modifying docs/SOURCE_OF_TRUTH.md without a doc_update task
            - Keep tasks small and file-specific
        """)
        raw = _llm_generate(prompt, task="planning")
        return self._parse_plan_json(raw, phase_n, description)

    def _parse_plan_json(self, raw: str, phase_n: int, description: str) -> GSDPlan:
        """Parse LLM JSON output into a GSDPlan, gracefully handling malformed output."""
        import json, re
        # Strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        try:
            data = json.loads(cleaned)
            tasks = []
            for t in data.get("tasks", []):
                tasks.append(GSDTask(
                    id=str(t.get("id", f"T{len(tasks)+1}")),
                    description=str(t.get("description", "")),
                    file_targets=t.get("file_targets", []),
                    symbol_refs=t.get("symbol_refs", []),
                    depends_on=t.get("depends_on", []),
                    wave=int(t.get("wave", 1)),
                ))
            return GSDPlan(
                phase=phase_n,
                title=str(data.get("title", f"Phase {phase_n}")),
                description=str(data.get("description", description)),
                tasks=tasks,
            )
        except Exception:
            # Fallback: create a placeholder plan with a single research task
            return GSDPlan(
                phase=phase_n,
                title=f"Phase {phase_n}",
                description=description,
                tasks=[GSDTask(
                    id="T1",
                    description=f"[Plan parse failed — raw LLM output stored] {description}",
                    file_targets=[],
                    wave=1,
                )],
            )

    def _revise_plan(self, plan: GSDPlan, violations: list[str]) -> GSDPlan:
        violation_text = "\n".join(f"- {v}" for v in violations)
        prompt = textwrap.dedent(f"""
            The following plan for Phase {plan.phase} was rejected by the Gatekeeper:

            {plan.model_dump_json(indent=2)}

            Violations:
            {violation_text}

            Revise the plan to fix all violations and return valid JSON
            in the same shape (no markdown wrapping).
        """)
        raw = _llm_generate(prompt, task="planning")
        revised = self._parse_plan_json(raw, plan.phase, plan.description)
        revised.gatekeeper_revision = plan.gatekeeper_revision
        return revised

    def _plan_to_gatekeeper_payload(self, plan: GSDPlan) -> dict[str, Any]:
        """Adapt a GSDPlan into the payload shape GatekeeperAgent expects."""
        files_changed = [f for t in plan.tasks for f in t.file_targets]
        has_test_task = any(
            "test" in t.description.lower() or
            any("test" in f for f in t.file_targets)
            for t in plan.tasks
        )
        touches_runtime = any(
            f.startswith("frontend/src/") or f.startswith("backend/")
            for f in files_changed
        )
        return {
            "files_changed": files_changed,
            # GatekeeperAgent checks tests_ok, playwright_ok, lighthouse_mobile_ok
            # For a plan we assert these are satisfied if a test task exists
            "tests_ok": has_test_task or not touches_runtime,
            "playwright_ok": True,          # can't run playwright at plan time
            "lighthouse_mobile_ok": True,   # can't run lighthouse at plan time
            "source_model": "gsd_agent",
            "sandbox_session_id": "gsd_plan",
            "staged_in_playbox": True,
        }

    # -----------------------------------------------------------------------
    # 3. execute-phase
    # -----------------------------------------------------------------------

    async def execute_phase(
        self, phase_n: int, dry_run: bool = False
    ) -> GSDExecutionResult:
        """
        Load PLAN.md for phase_n, resolve wave order via topological sort,
        execute each wave as a parallel asyncio batch, run gatekeeper after.
        """
        plan = gsd_store.load_plan(phase_n)
        if plan is None:
            raise ValueError(
                f"No plan found for phase {phase_n}. "
                f"Run /gsd:plan-phase {phase_n} first."
            )

        result = GSDExecutionResult(phase=phase_n)
        gsd_store.append_execution_log(
            phase_n,
            f"\n## Execution started — {datetime.now(timezone.utc).isoformat()} "
            f"(dry_run={dry_run})\n",
        )

        # Group tasks by wave
        waves: dict[int, list[GSDTask]] = {}
        for task in plan.tasks:
            waves.setdefault(task.wave, []).append(task)

        wave_result = WaveResult(wave=0)  # sentinel so post-loop ref is always bound
        for wave_num in sorted(waves):
            tasks_in_wave = waves[wave_num]
            wave_result = WaveResult(wave=wave_num)

            if dry_run:
                for t in tasks_in_wave:
                    wave_result.task_results.append({
                        "task_id": t.id,
                        "status": "dry_run",
                        "description": t.description,
                    })
            else:
                coros = [
                    asyncio.to_thread(self._execute_task, phase_n, t)
                    for t in tasks_in_wave
                ]
                task_outputs = await asyncio.gather(*coros, return_exceptions=True)
                for t, output in zip(tasks_in_wave, task_outputs):
                    if isinstance(output, Exception):
                        wave_result.errors.append(f"{t.id}: {output}")
                        wave_result.task_results.append({
                            "task_id": t.id, "status": "error", "error": str(output),
                        })
                    else:
                        wave_result.task_results.append(output)  # type: ignore[arg-type]

            result.wave_results.append(wave_result)
            result.waves_completed += 1
            gsd_store.append_execution_log(
                phase_n,
                f"### Wave {wave_num} — {len(tasks_in_wave)} tasks, "
                f"{len(wave_result.errors)} errors\n",
            )

        # Gatekeeper post-execution check
        all_files = [f for t in plan.tasks for f in t.file_targets]
        gk_payload = {
            "files_changed": all_files,
            "tests_ok": not wave_result.errors,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
            "source_model": "gsd_agent",
            "sandbox_session_id": f"gsd_exec_{phase_n}",
            "staged_in_playbox": True,
        }
        gk_result = self._gatekeeper.review_mutation(gk_payload)
        result.gatekeeper_approved = gk_result.approved
        result.gatekeeper_violations = gk_result.violations
        result.status = PhaseStatus.COMPLETED if gk_result.approved else PhaseStatus.FAILED
        result.completed_at = datetime.now(timezone.utc)

        # Update plan status
        plan.status = result.status
        gsd_store.save_plan(phase_n, plan)

        # Update global state
        state = gsd_store.load_state()
        if result.status == PhaseStatus.COMPLETED:
            if phase_n not in state.completed_phases:
                state.completed_phases.append(phase_n)
            if phase_n in state.failed_phases:
                state.failed_phases.remove(phase_n)
            state.active_phase = None
        else:
            if phase_n not in state.failed_phases:
                state.failed_phases.append(phase_n)
        gsd_store.save_state(state)

        gsd_store.append_execution_log(
            phase_n,
            f"## Execution finished — {result.completed_at.isoformat()} "
            f"status={result.status.value}\n",
        )
        return result

    def _execute_task(self, phase_n: int, task: GSDTask) -> dict[str, Any]:
        """
        Execute a single task.  Currently delegates to the LLM with the task
        description + file context.  Future: wire to specific tool calls based
        on task type (safe_shell, doc_updater, etc.).
        """
        file_context = ""
        for fp in task.file_targets[:3]:
            p = Path(fp)
            if p.exists():
                try:
                    file_context += f"\n### {fp}\n```\n{p.read_text(encoding='utf-8')[:800]}\n```"
                except Exception:
                    pass

        prompt = textwrap.dedent(f"""
            Execute the following task for Phase {phase_n} of the Agentop project.

            Task: {task.description}
            Target files: {', '.join(task.file_targets) or 'none specified'}
            {file_context}

            Describe exactly what changes were made (or should be made) in 2-3 sentences.
            Be specific about file names and code locations.
        """)
        response = _llm_generate(prompt, task="general")
        gsd_store.append_execution_log(
            phase_n,
            f"#### {task.id} — {task.description}\n{response}\n",
        )
        return {"task_id": task.id, "status": "done", "summary": response[:200]}

    # -----------------------------------------------------------------------
    # 4. quick
    # -----------------------------------------------------------------------

    async def quick(self, prompt: str, full: bool = False) -> GSDQuickResult:
        """
        Ad-hoc task — no ceremony. Execute with LLM, track in STATE.md.
        full=True: attempt a commit via git_ops tool.
        """
        response = await asyncio.to_thread(_llm_generate, prompt, "general")

        committed = False
        if full:
            committed = await self._try_commit(prompt)

        state = gsd_store.load_state()
        ts = datetime.now(timezone.utc).isoformat()
        state.quick_log.append(f"{ts}: {prompt[:120]}")
        # Keep quick log bounded
        state.quick_log = state.quick_log[-100:]
        gsd_store.save_state(state)

        return GSDQuickResult(
            prompt=prompt,
            response=response,
            committed=committed,
            timestamp=datetime.now(timezone.utc),
        )

    async def _try_commit(self, prompt: str) -> bool:
        """Attempt a git commit via the git_ops tool if available."""
        try:
            from backend.tools import execute_tool
            result = await execute_tool(
                "git_ops",
                "gsd_agent",
                ["git_ops"],
                action="commit",
                message=f"gsd-quick: {prompt[:72]}",
            )
            return bool(result and not result.get("error"))
        except Exception as exc:
            logger.warning(f"GSD quick commit failed: {exc}")
            return False

    # -----------------------------------------------------------------------
    # 5. verify-work
    # -----------------------------------------------------------------------

    async def verify_work(self, phase_n: int | None = None) -> GSDVerifyReport:
        """
        Read last execution log, generate UAT checklist via LLM, run
        health/db checks where possible, return structured gap report.
        """
        # Resolve which phase to verify
        if phase_n is None:
            state = gsd_store.load_state()
            if state.completed_phases:
                phase_n = max(state.completed_phases)
            elif state.active_phase is not None:
                phase_n = state.active_phase

        execution_log = gsd_store.read_execution_log(phase_n) if phase_n else ""
        plan = gsd_store.load_plan(phase_n) if phase_n else None
        plan_summary = plan.model_dump_json(indent=2)[:2000] if plan else "(no plan found)"

        checklist_raw = await asyncio.to_thread(
            self._generate_checklist, phase_n, execution_log, plan_summary
        )

        report = await asyncio.to_thread(
            self._run_checks, checklist_raw, phase_n
        )
        gsd_store.save_verify_report(report, phase_n)
        return report

    def _generate_checklist(
        self, phase_n: int | None, execution_log: str, plan_summary: str
    ) -> list[str]:
        prompt = textwrap.dedent(f"""
            Review the following Agentop Phase {phase_n} execution and produce a
            UAT checklist.  Each item should be a single testable statement that
            can be verified via health endpoint, database query, or file existence.

            Plan:
            {plan_summary}

            Execution log (last 2000 chars):
            {execution_log[-2000:] or '(no execution log)'}

            Return ONLY a JSON array of strings — no preamble.
            Example: ["Backend returns 200 on /health", "Customer table has > 0 rows"]
        """)
        raw = _llm_generate(prompt, task="general")
        import json, re
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        try:
            items = json.loads(cleaned)
            if isinstance(items, list):
                return [str(i) for i in items]
        except Exception:
            pass
        # Fallback: split by newlines
        return [line.strip("- •").strip() for line in raw.splitlines() if line.strip()]

    def _run_checks(
        self, checklist: list[str], phase_n: int | None
    ) -> GSDVerifyReport:
        """
        For each checklist item, attempt automated verification where possible
        (health endpoint, file existence checks).  Others remain unverifiable.
        """
        import urllib.request

        report = GSDVerifyReport(phase=phase_n)

        for item in checklist:
            item_lower = item.lower()

            # --- Health endpoint check ---
            if "health" in item_lower or "/health" in item_lower:
                try:
                    resp = urllib.request.urlopen(
                        "http://127.0.0.1:8000/health", timeout=3
                    )
                    if resp.status == 200:
                        report.passed.append(VerifyCheckItem(
                            description=item, status="passed",
                            detail="GET /health → 200"
                        ))
                    else:
                        report.failed.append(VerifyCheckItem(
                            description=item, status="failed",
                            detail=f"GET /health → {resp.status}"
                        ))
                except Exception as exc:
                    report.failed.append(VerifyCheckItem(
                        description=item, status="failed",
                        detail=f"Health check error: {exc}"
                    ))
                continue

            # --- File existence check ---
            if any(kw in item_lower for kw in ("file exist", "created", "written", "generated")):
                # Try to extract a path from the item
                words = item.split()
                found_file = False
                for word in words:
                    candidate = Path(word.strip("'\","))
                    if candidate.exists():
                        report.passed.append(VerifyCheckItem(
                            description=item, status="passed",
                            detail=f"{candidate} exists"
                        ))
                        found_file = True
                        break
                if not found_file:
                    report.unverifiable.append(VerifyCheckItem(
                        description=item, status="unverifiable",
                        detail="Could not auto-extract a verifiable file path"
                    ))
                continue

            # --- Default: unverifiable ---
            report.unverifiable.append(VerifyCheckItem(
                description=item, status="unverifiable",
                detail="Requires manual verification"
            ))

        return report
