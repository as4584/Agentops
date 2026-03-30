"""
Tests for backend/models/__init__.py and backend/models/gsd.py.

Pure Pydantic models — no external dependencies.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from backend.models import (
    AgentDefinition,
    AgentState,
    AgentStatus,
    CampaignGenerateRequest,
    CampaignGenerateResponse,
    ChangeImpactLevel,
    ChangeLogEntry,
    ChatRequest,
    ChatResponse,
    DriftEvent,
    DriftReport,
    DriftStatus,
    IntakeAnswerRequest,
    IntakeStartRequest,
    IntakeStartResponse,
    IntakeStatusResponse,
    ModificationType,
    SystemStatus,
    ToolDefinition,
    ToolExecutionRecord,
)
from backend.models.gsd import (
    GSDExecutionResult,
    GSDMapResult,
    GSDPlan,
    GSDQuickRequest,
    GSDQuickResult,
    GSDRoadmapEntry,
    GSDStateFile,
    GSDTask,
    GSDVerifyReport,
    PhaseStatus,
    TaskStatus,
    VerifyCheckItem,
    WaveResult,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------

class TestEnums:
    def test_modification_type_values(self):
        assert ModificationType.READ_ONLY == "READ_ONLY"
        assert ModificationType.STATE_MODIFY == "STATE_MODIFY"
        assert ModificationType.ARCHITECTURAL_MODIFY == "ARCHITECTURAL_MODIFY"

    def test_change_impact_levels(self):
        assert ChangeImpactLevel.LOW == "LOW"
        assert ChangeImpactLevel.MEDIUM == "MEDIUM"
        assert ChangeImpactLevel.HIGH == "HIGH"
        assert ChangeImpactLevel.CRITICAL == "CRITICAL"

    def test_drift_status_values(self):
        assert DriftStatus.GREEN == "GREEN"
        assert DriftStatus.YELLOW == "YELLOW"
        assert DriftStatus.RED == "RED"

    def test_agent_status_values(self):
        assert AgentStatus.IDLE == "IDLE"
        assert AgentStatus.ACTIVE == "ACTIVE"
        assert AgentStatus.ERROR == "ERROR"
        assert AgentStatus.HALTED == "HALTED"

    def test_phase_status_values(self):
        assert PhaseStatus.PENDING == "pending"
        assert PhaseStatus.COMPLETED == "completed"
        assert PhaseStatus.FAILED == "failed"

    def test_task_status_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"


# ---------------------------------------------------------------------------
# AgentDefinition
# ---------------------------------------------------------------------------

class TestAgentDefinition:
    def _make(self, **kwargs):
        defaults = {
            "agent_id": "test_agent",
            "role": "Tester",
            "system_prompt": "You test things.",
            "memory_namespace": "agents/test",
            "change_impact_level": ChangeImpactLevel.LOW,
        }
        defaults.update(kwargs)
        return AgentDefinition(**defaults)

    def test_minimal_creation(self):
        agent = self._make()
        assert agent.agent_id == "test_agent"
        assert agent.tool_permissions == []
        assert agent.allowed_actions == []
        assert agent.skills == []

    def test_with_permissions_and_skills(self):
        agent = self._make(
            tool_permissions=["safe_shell", "file_reader"],
            skills=["business_analysis"],
            change_impact_level=ChangeImpactLevel.HIGH,
        )
        assert "safe_shell" in agent.tool_permissions
        assert "business_analysis" in agent.skills
        assert agent.change_impact_level == ChangeImpactLevel.HIGH

    def test_serialization_round_trip(self):
        agent = self._make(tool_permissions=["git_ops"])
        data = agent.model_dump()
        restored = AgentDefinition(**data)
        assert restored.agent_id == agent.agent_id
        assert restored.tool_permissions == ["git_ops"]


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------

class TestAgentState:
    def test_defaults(self):
        state = AgentState(agent_id="soul_core")
        assert state.status == AgentStatus.IDLE
        assert state.last_active is None
        assert state.memory_size_bytes == 0
        assert state.total_actions == 0
        assert state.error_count == 0

    def test_can_update_status(self):
        state = AgentState(agent_id="devops_agent", status=AgentStatus.ACTIVE)
        assert state.status == AgentStatus.ACTIVE


# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------

class TestToolDefinition:
    def test_creation(self):
        tool = ToolDefinition(
            name="safe_shell",
            description="Execute whitelisted shell commands",
            modification_type=ModificationType.STATE_MODIFY,
        )
        assert tool.name == "safe_shell"
        assert tool.requires_doc_update is False

    def test_arch_modify_requires_doc_update(self):
        tool = ToolDefinition(
            name="doc_updater",
            description="Update governance docs",
            modification_type=ModificationType.ARCHITECTURAL_MODIFY,
            requires_doc_update=True,
        )
        assert tool.requires_doc_update is True


# ---------------------------------------------------------------------------
# ToolExecutionRecord
# ---------------------------------------------------------------------------

class TestToolExecutionRecord:
    def test_defaults(self):
        rec = ToolExecutionRecord(
            tool_name="file_reader",
            agent_id="knowledge_agent",
            modification_type=ModificationType.READ_ONLY,
        )
        assert rec.success is True
        assert rec.error is None
        assert rec.doc_updated is False
        assert isinstance(rec.timestamp, datetime)

    def test_failed_record(self):
        rec = ToolExecutionRecord(
            tool_name="safe_shell",
            agent_id="devops_agent",
            modification_type=ModificationType.STATE_MODIFY,
            success=False,
            error="Permission denied",
        )
        assert rec.success is False
        assert rec.error == "Permission denied"


# ---------------------------------------------------------------------------
# DriftEvent + DriftReport
# ---------------------------------------------------------------------------

class TestDriftModels:
    def test_drift_event_defaults(self):
        event = DriftEvent(
            invariant_id="INV-1",
            description="Frontend imported backend module",
            severity=ChangeImpactLevel.HIGH,
        )
        assert event.resolved is False
        assert event.severity == ChangeImpactLevel.HIGH

    def test_drift_report_defaults(self):
        report = DriftReport()
        assert report.status == DriftStatus.GREEN
        assert report.pending_updates == []
        assert report.violations == []

    def test_drift_report_with_violations(self):
        event = DriftEvent(
            invariant_id="INV-3",
            description="Dynamic tool registered",
            severity=ChangeImpactLevel.CRITICAL,
        )
        report = DriftReport(status=DriftStatus.RED, violations=[event])
        assert report.status == DriftStatus.RED
        assert len(report.violations) == 1


# ---------------------------------------------------------------------------
# ChangeLogEntry
# ---------------------------------------------------------------------------

class TestChangeLogEntry:
    def test_creation(self):
        entry = ChangeLogEntry(
            agent_id="code_review_agent",
            reason="Refactored routing",
            risk_assessment=ChangeImpactLevel.MEDIUM,
        )
        assert entry.documentation_updated is False
        assert entry.files_modified == []
        assert entry.impacted_subsystems == []


# ---------------------------------------------------------------------------
# Chat models
# ---------------------------------------------------------------------------

class TestChatModels:
    def test_chat_request(self):
        req = ChatRequest(agent_id="monitor_agent", message="check system health")
        assert req.context == {}

    def test_chat_response_defaults(self):
        resp = ChatResponse(agent_id="monitor_agent", message="All systems nominal")
        assert resp.drift_status == DriftStatus.GREEN
        assert resp.tool_calls == []

    def test_system_status_defaults(self):
        status = SystemStatus()
        assert status.agents == []
        assert status.total_tool_executions == 0


# ---------------------------------------------------------------------------
# Intake models
# ---------------------------------------------------------------------------

class TestIntakeModels:
    def test_intake_start_request(self):
        req = IntakeStartRequest(business_id="acme_corp")
        assert req.business_id == "acme_corp"

    def test_intake_start_response(self):
        resp = IntakeStartResponse(
            business_id="acme",
            current_question_index=0,
            total_questions=10,
            question_key="name",
            question="What is your business name?",
        )
        assert resp.completed is False

    def test_intake_answer_request(self):
        req = IntakeAnswerRequest(business_id="acme", answer="Acme Corp")
        assert req.answer == "Acme Corp"

    def test_intake_status_response(self):
        resp = IntakeStatusResponse(
            business_id="acme",
            current_question_index=2,
            total_questions=10,
            completed=False,
        )
        assert resp.answers == {}


# ---------------------------------------------------------------------------
# Campaign models
# ---------------------------------------------------------------------------

class TestCampaignModels:
    def test_campaign_generate_request_defaults(self):
        req = CampaignGenerateRequest(
            business_id="acme",
            platform="instagram",
            objective="brand_awareness",
        )
        assert req.format_type == "reel"
        assert req.duration_seconds == 30

    def test_campaign_generate_response(self):
        resp = CampaignGenerateResponse(
            business_id="acme",
            platform="instagram",
            objective="brand_awareness",
            format_type="reel",
            duration_seconds=30,
            generated_at="2025-01-01T00:00:00Z",
            campaign={"script": "Hello world"},
        )
        assert resp.campaign["script"] == "Hello world"


# ---------------------------------------------------------------------------
# GSD models
# ---------------------------------------------------------------------------

class TestGSDModels:
    def test_gsd_task_defaults(self):
        task = GSDTask(id="task-1", description="Write tests")
        assert task.status == TaskStatus.PENDING
        assert task.wave == 1
        assert task.file_targets == []
        assert task.depends_on == []
        assert task.result_summary == ""

    def test_gsd_plan_defaults(self):
        plan = GSDPlan(phase=1, title="Phase 1", description="Initial phase")
        assert plan.status == PhaseStatus.PLANNED
        assert plan.tasks == []
        assert plan.gatekeeper_violations == []
        assert plan.gatekeeper_revision == 0

    def test_gsd_plan_with_tasks(self):
        t1 = GSDTask(id="t1", description="Task 1")
        t2 = GSDTask(id="t2", description="Task 2", depends_on=["t1"])
        plan = GSDPlan(phase=2, title="Phase 2", description="Execution", tasks=[t1, t2])
        assert len(plan.tasks) == 2
        assert plan.tasks[1].depends_on == ["t1"]

    def test_gsd_map_result(self):
        result = GSDMapResult(stack="Python/FastAPI", architecture="layered")
        assert result.stack == "Python/FastAPI"
        assert isinstance(result.generated_at, datetime)

    def test_wave_result(self):
        wave = WaveResult(wave=1, task_results=[{"id": "t1", "ok": True}])
        assert wave.wave == 1
        assert len(wave.task_results) == 1
        assert wave.errors == []

    def test_gsd_execution_result_defaults(self):
        result = GSDExecutionResult(phase=1)
        assert result.waves_completed == 0
        assert result.gatekeeper_approved is False
        assert result.status == PhaseStatus.EXECUTING

    def test_gsd_quick_request_validates_length(self):
        req = GSDQuickRequest(prompt="refactor utils")
        assert req.full is False

    def test_gsd_quick_request_empty_prompt_raises(self):
        with pytest.raises(Exception):
            GSDQuickRequest(prompt="")

    def test_gsd_quick_result(self):
        result = GSDQuickResult(prompt="refactor utils", response="Done")
        assert result.committed is False

    def test_verify_check_item(self):
        item = VerifyCheckItem(description="Tests pass", status="passed")
        assert item.detail == ""

    def test_gsd_verify_report(self):
        passed = VerifyCheckItem(description="All tests green", status="passed")
        report = GSDVerifyReport(phase=1, passed=[passed])
        assert len(report.passed) == 1
        assert report.failed == []

    def test_gsd_roadmap_entry(self):
        entry = GSDRoadmapEntry(title="Phase 2", milestone="v2.0")
        assert entry.priority == 1
        assert entry.done is False

    def test_gsd_state_file_defaults(self):
        state = GSDStateFile()
        assert state.active_phase is None
        assert state.completed_phases == []
        assert state.roadmap == []

    def test_gsd_state_file_with_data(self):
        state = GSDStateFile(
            active_phase=3,
            completed_phases=[1, 2],
            quick_log=["2025-01-01: refactor utils"],
        )
        assert state.active_phase == 3
        assert 2 in state.completed_phases
