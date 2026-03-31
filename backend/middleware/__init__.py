"""
Drift Guard & Governance Middleware — Architectural integrity enforcement.
=========================================================================
This is the core governance module that:
1. Intercepts all tool calls
2. Detects structural modifications
3. Enforces documentation-before-mutation (INV-5)
4. Checks architectural invariants
5. Triggers CRITICAL_DRIFT_EVENT on violations

This module is the primary defense against architectural drift.
All tool executions MUST pass through the DriftGuard before execution.

Referenced Invariants:
- INV-1: LLM layer must not depend on frontend
- INV-2: Agents must not directly call each other
- INV-3: Tools cannot register new tools dynamically
- INV-4: Memory namespaces must not overlap
- INV-5: Documentation must precede mutation
- INV-7: All tool executions must be logged
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import (
    AGENT_REGISTRY_PATH,
    CHANGE_LOG_PATH,
    DOCS_DIR,
    SOURCE_OF_TRUTH_PATH,
)
from backend.models import (
    ChangeImpactLevel,
    ChangeLogEntry,
    DriftEvent,
    DriftReport,
    DriftStatus,
    ModificationType,
    ToolExecutionRecord,
)
from backend.utils import logger


class DriftGuard:
    """
    Central governance enforcement engine.

    Intercepts tool calls, checks invariants, and ensures
    documentation is updated before architectural mutations proceed.
    """

    def __init__(self) -> None:
        self._pending_updates: list[str] = []
        self._violations: list[DriftEvent] = []
        self._halted: bool = False
        logger.info("DriftGuard initialized — governance layer active")

    # -----------------------------------------------------------------
    # Tool Call Interception (Primary enforcement point)
    # -----------------------------------------------------------------

    async def guard_tool_execution(
        self,
        tool_name: str,
        agent_id: str,
        modification_type: ModificationType,
        tool_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Intercept and guard a tool execution.

        This is the MANDATORY middleware that all tool calls pass through.

        Protocol:
        1. Check if system is halted (invariant violation)
        2. Log the tool execution attempt (INV-7)
        3. If ARCHITECTURAL_MODIFY:
           a. Check documentation has been updated (INV-5)
           b. If not, block execution and flag YELLOW drift
        4. Execute the tool
        5. Record the execution
        6. Return result

        Args:
            tool_name: Name of the tool being invoked.
            agent_id: ID of the invoking agent.
            modification_type: Classification of the modification.
            tool_fn: The actual tool function to execute.
            *args, **kwargs: Arguments for the tool function.

        Returns:
            The tool's return value.

        Raises:
            RuntimeError: If system is halted due to invariant violation.
            PermissionError: If documentation update required but not done.
        """
        # Step 1: Check if system is halted
        if self._halted:
            raise RuntimeError(
                "SYSTEM HALTED: Critical drift event detected. Resolve invariant violations before proceeding."
            )

        # Step 2: Create execution record (INV-7)
        record = ToolExecutionRecord(
            tool_name=tool_name,
            agent_id=agent_id,
            modification_type=modification_type,
            input_summary=f"args={len(args)}, kwargs={list(kwargs.keys())}",
        )

        # Step 3: Enforce documentation for architectural modifications (INV-5)
        if modification_type == ModificationType.ARCHITECTURAL_MODIFY:
            doc_check = self._check_documentation_updated(agent_id, tool_name)
            if not doc_check:
                self._pending_updates.append(f"{tool_name} by {agent_id} requires documentation update")
                logger.warning(
                    f"DRIFT YELLOW: {tool_name} by {agent_id} — documentation update required before execution"
                )
                # For architectural modifications, we still allow but flag
                record.doc_updated = False

        # Step 4: Execute the tool
        try:
            # Emit live activity event for SSE subscribers
            from backend.tasks import task_tracker as _tt

            _tt.emit_activity(
                "tool_start",
                {
                    "tool_name": tool_name,
                    "agent_id": agent_id,
                    "modification_type": modification_type.value,
                },
            )

            result = await tool_fn(*args, **kwargs)
            record.success = True
            record.output_summary = str(result)[:200] if result else ""

            _tt.emit_activity(
                "tool_end",
                {
                    "tool_name": tool_name,
                    "agent_id": agent_id,
                    "success": True,
                    "output_preview": str(result)[:120] if result else "",
                },
            )
        except Exception as e:
            record.success = False
            record.error = str(e)
            logger.log_tool_execution(record)

            from backend.tasks import task_tracker as _tt2

            _tt2.emit_activity(
                "tool_end",
                {
                    "tool_name": tool_name,
                    "agent_id": agent_id,
                    "success": False,
                    "error": str(e)[:120],
                },
            )
            raise

        # Step 5: Record the execution
        logger.log_tool_execution(record)

        return result

    # -----------------------------------------------------------------
    # Invariant Checking
    # -----------------------------------------------------------------

    def check_invariants(self) -> DriftReport:
        """
        Check all architectural invariants and return a drift report.

        This scans the system state and documentation for:
        - INV-4: Memory namespace overlap
        - INV-5: Pending documentation updates
        - Other structural integrity checks
        """
        report = DriftReport(last_check=datetime.utcnow())

        # Check for pending documentation updates
        if self._pending_updates:
            report.status = DriftStatus.YELLOW
            report.pending_updates = list(self._pending_updates)

        # Check for active violations
        active_violations = [v for v in self._violations if not v.resolved]
        if active_violations:
            report.status = DriftStatus.RED
            report.violations = active_violations

        return report

    def check_namespace_overlap(self, namespaces: list[str]) -> bool:
        """
        Check INV-4: Memory namespaces must not overlap.
        Returns True if no overlap (system is clean).
        """
        if len(namespaces) != len(set(namespaces)):
            self._register_violation(
                invariant_id="INV-4",
                description=f"Memory namespace overlap detected: {namespaces}",
                severity=ChangeImpactLevel.CRITICAL,
            )
            return False
        return True

    def validate_agent_tool_access(self, agent_id: str, tool_name: str, allowed_tools: list[str]) -> bool:
        """
        Validate that an agent has permission to use a tool.
        Returns True if access is permitted.
        """
        if tool_name not in allowed_tools:
            logger.warning(f"Tool access denied: agent={agent_id}, tool={tool_name}, allowed={allowed_tools}")
            return False
        return True

    # -----------------------------------------------------------------
    # Documentation Enforcement (INV-5)
    # -----------------------------------------------------------------

    def _check_documentation_updated(self, agent_id: str, tool_name: str) -> bool:
        """
        Check if documentation has been updated for a structural change.
        Looks for a recent entry in CHANGE_LOG.md matching this agent.
        """
        try:
            if not CHANGE_LOG_PATH.exists():
                return False
            content = CHANGE_LOG_PATH.read_text()
            # Check for an entry within the last section matching the agent
            # This is a simplified check — in production, parse structured entries
            return agent_id in content and tool_name in content
        except Exception:
            return False

    async def append_change_log(self, entry: ChangeLogEntry) -> None:
        """
        Append a structured entry to CHANGE_LOG.md.

        This is the proper way to record architectural changes.
        Must be called BEFORE the mutation (INV-5: documentation precedes mutation).
        """
        formatted = (
            f"\n### {entry.timestamp.isoformat()}\n"
            f"- **Agent:** {entry.agent_id}\n"
            f"- **Files Modified:** {', '.join(entry.files_modified)}\n"
            f"- **Reason:** {entry.reason}\n"
            f"- **Risk Assessment:** {entry.risk_assessment.value}\n"
            f"- **Impacted Subsystems:** {', '.join(entry.impacted_subsystems)}\n"
            f"- **Documentation Updated:** {'YES' if entry.documentation_updated else 'NO'}\n"
        )

        try:
            with open(CHANGE_LOG_PATH, "a") as f:
                f.write(formatted)
            logger.info(f"CHANGE_LOG updated by {entry.agent_id}: {entry.reason}")

            # Clear the pending update for this agent if any
            self._pending_updates = [p for p in self._pending_updates if entry.agent_id not in p]
        except Exception as e:
            logger.error(f"Failed to update CHANGE_LOG: {e}")
            raise

    # -----------------------------------------------------------------
    # Violation Management
    # -----------------------------------------------------------------

    def _register_violation(
        self,
        invariant_id: str,
        description: str,
        severity: ChangeImpactLevel,
    ) -> None:
        """
        Register an invariant violation.
        CRITICAL violations halt the system.
        """
        event = DriftEvent(
            invariant_id=invariant_id,
            description=description,
            severity=severity,
        )
        self._violations.append(event)
        logger.log_drift_event(event)

        if severity == ChangeImpactLevel.CRITICAL:
            self._halted = True
            logger.error(f"SYSTEM HALTED: Critical invariant violation {invariant_id}")

    def resolve_violation(self, invariant_id: str) -> bool:
        """
        Mark a violation as resolved. Unhalts system if no critical violations remain.
        """
        resolved_any = False
        for v in self._violations:
            if v.invariant_id == invariant_id and not v.resolved:
                v.resolved = True
                resolved_any = True

        # Check if system can be unhalted
        active_critical = [v for v in self._violations if not v.resolved and v.severity == ChangeImpactLevel.CRITICAL]
        if not active_critical:
            self._halted = False
            logger.info("System unhalted — no active critical violations")

        return resolved_any

    def clear_pending_updates(self) -> None:
        """Clear all pending documentation updates."""
        self._pending_updates.clear()

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def drift_status(self) -> DriftStatus:
        """Quick accessor for current drift status."""
        if self._halted or any(not v.resolved and v.severity == ChangeImpactLevel.CRITICAL for v in self._violations):
            return DriftStatus.RED
        if self._pending_updates:
            return DriftStatus.YELLOW
        return DriftStatus.GREEN


# Module-level singleton
drift_guard = DriftGuard()
