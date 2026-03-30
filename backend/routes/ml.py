"""
ML Routes — API endpoints for ML pipeline management.
======================================================
Exposes experiment tracking, monitoring, data versioning,
and documentation enforcement via REST API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from backend.ml.experiment_tracker import ExperimentTracker
from backend.ml.monitor import MLMonitor
from backend.ml.data_version import DataVersioner
from backend.ml.doc_enforcer import MLDocEnforcer
from backend.utils import logger

router = APIRouter(prefix="/ml", tags=["ml"])

# Singletons — initialized once, reused across requests
_tracker = ExperimentTracker()
_monitor = MLMonitor()
_versioner = DataVersioner()
_doc_enforcer = MLDocEnforcer()


# ── Request Models ───────────────────────────────────────


class StartRunRequest(BaseModel):
    experiment_name: str
    hyperparameters: dict[str, Any] = {}
    model_type: str = ""
    dataset_version: str = ""
    tags: dict[str, str] = {}


class LogMetricRequest(BaseModel):
    name: str
    value: float
    step: Optional[int] = None


class EndRunRequest(BaseModel):
    status: str = "completed"
    notes: str = ""


class LogChangeRequest(BaseModel):
    agent_name: str
    change_type: str
    description: str
    details: dict[str, Any] = {}
    run_id: str = ""


class LogGoalRequest(BaseModel):
    agent_name: str
    goal: str
    success_criteria: str = ""


class RecordLatencyRequest(BaseModel):
    endpoint: str
    latency_ms: float
    model_name: str = ""


class RecordPredictionRequest(BaseModel):
    model_name: str
    predicted: Any
    actual: Any = None
    confidence: Optional[float] = None


class RecordEndpointRequest(BaseModel):
    endpoint: str
    status_code: int
    error: Optional[str] = None


class SetBaselineRequest(BaseModel):
    model_name: str
    features: dict[str, dict[str, float]]


# ── Experiment Tracking ──────────────────────────────────


@router.post("/experiments/start")
async def start_experiment(req: StartRunRequest) -> dict[str, str]:
    run_id = _tracker.start_run(
        experiment_name=req.experiment_name,
        hyperparameters=req.hyperparameters,
        model_type=req.model_type,
        dataset_version=req.dataset_version,
        tags=req.tags,
    )
    return {"run_id": run_id}


@router.post("/experiments/{run_id}/metric")
async def log_metric(run_id: str, req: LogMetricRequest) -> dict[str, str]:
    try:
        _tracker.log_metric(run_id, req.name, req.value, req.step)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {"status": "ok"}


@router.post("/experiments/{run_id}/artifact")
async def log_artifact(run_id: str, artifact_path: str) -> dict[str, str]:
    try:
        _tracker.log_artifact(run_id, artifact_path)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {"status": "ok"}


@router.post("/experiments/{run_id}/end")
async def end_experiment(run_id: str, req: EndRunRequest) -> dict[str, str]:
    try:
        _tracker.end_run(run_id, status=req.status, notes=req.notes)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {"status": "ok"}


@router.get("/experiments/{run_id}")
async def get_experiment(run_id: str) -> dict[str, Any]:
    try:
        return _tracker.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


@router.get("/experiments")
async def list_experiments(
    experiment_name: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    return _tracker.list_runs(experiment_name=experiment_name, status=status)


@router.post("/experiments/compare")
async def compare_experiments(run_ids: list[str]) -> list[dict[str, Any]]:
    try:
        return _tracker.compare_runs(run_ids)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiments/best/{experiment_name}")
async def best_experiment(
    experiment_name: str,
    metric: str = "accuracy",
    higher_is_better: bool = True,
) -> dict[str, Any]:
    result = _tracker.best_run(experiment_name, metric, higher_is_better)
    if not result:
        raise HTTPException(status_code=404, detail="No runs with that metric found")
    return result


# ── Monitoring ───────────────────────────────────────────


@router.post("/monitoring/latency")
async def record_latency(req: RecordLatencyRequest) -> dict[str, str]:
    _monitor.record_latency(req.endpoint, req.latency_ms, req.model_name)
    return {"status": "ok"}


@router.post("/monitoring/prediction")
async def record_prediction(req: RecordPredictionRequest) -> dict[str, str]:
    _monitor.record_prediction(req.model_name, req.predicted, req.actual, req.confidence)
    return {"status": "ok"}


@router.post("/monitoring/endpoint")
async def record_endpoint(req: RecordEndpointRequest) -> dict[str, str]:
    _monitor.record_endpoint_result(req.endpoint, req.status_code, req.error)
    return {"status": "ok"}


@router.post("/monitoring/baseline")
async def set_baseline(req: SetBaselineRequest) -> dict[str, str]:
    _monitor.set_baseline(req.model_name, req.features)
    return {"status": "ok"}


@router.get("/monitoring/health")
async def health_report(model_name: str = "") -> dict[str, Any]:
    return _monitor.get_health_report(model_name=model_name)


@router.get("/monitoring/latency")
async def check_latency(endpoint: Optional[str] = None) -> dict[str, Any]:
    return _monitor.check_latency(endpoint=endpoint)


@router.get("/monitoring/accuracy/{model_name}")
async def check_accuracy(model_name: str, window: int = 100) -> dict[str, Any]:
    return _monitor.check_accuracy(model_name, window=window)


@router.get("/monitoring/drift/{model_name}")
async def check_drift(model_name: str) -> list[dict[str, Any]]:
    return _monitor.check_data_drift(model_name)


@router.get("/monitoring/endpoints")
async def check_endpoints() -> dict[str, Any]:
    return _monitor.check_endpoints()


@router.get("/monitoring/alerts")
async def get_alerts(
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _monitor.get_alerts(alert_type=alert_type, severity=severity, limit=limit)


@router.post("/monitoring/alerts/acknowledge")
async def acknowledge_alerts(alert_type: Optional[str] = None) -> dict[str, int]:
    count = _monitor.acknowledge_alerts(alert_type=alert_type)
    return {"acknowledged": count}


# ── Data Versioning ──────────────────────────────────────


@router.post("/data/version")
async def compute_data_version(subdir: str = "") -> dict[str, Any]:
    try:
        return _versioner.compute_version(subdir=subdir)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/data/versions")
async def list_data_versions() -> list[dict[str, Any]]:
    return _versioner.list_versions()


@router.get("/data/version/{version_hash}")
async def get_data_version(version_hash: str) -> dict[str, Any]:
    result = _versioner.get_version(version_hash)
    if not result:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_hash}")
    return result


@router.get("/data/diff")
async def diff_data_versions(v1: str, v2: str) -> dict[str, Any]:
    try:
        return _versioner.diff_versions(v1, v2)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Documentation ────────────────────────────────────────


@router.post("/docs/log")
async def log_ml_change(req: LogChangeRequest) -> dict[str, str]:
    _doc_enforcer.log_change(
        agent_name=req.agent_name,
        change_type=req.change_type,
        description=req.description,
        details=req.details,
        run_id=req.run_id,
    )
    return {"status": "ok"}


@router.post("/docs/goal")
async def log_ml_goal(req: LogGoalRequest) -> dict[str, str]:
    _doc_enforcer.log_goal(
        agent_name=req.agent_name,
        goal=req.goal,
        success_criteria=req.success_criteria,
    )
    return {"status": "ok"}


@router.get("/docs/recent")
async def recent_ml_docs(limit: int = 20) -> list[dict[str, Any]]:
    return _doc_enforcer.get_recent_entries(limit=limit)


@router.post("/docs/audit")
async def audit_compliance(run_ids: list[str]) -> dict[str, Any]:
    return _doc_enforcer.audit_compliance(run_ids)
