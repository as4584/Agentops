"""
ML Eval Routes — API endpoints for LLM evaluation, A/B experiments, benchmarks.
===============================================================================
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.ml.ab_experiment import ABExperimentHarness
from backend.ml.benchmark import BenchmarkSuite
from backend.ml.eval_framework import EvalCase, EvalDimension, LLMEvalFramework
from backend.ml.mlflow_tracker import MLflowTracker
from backend.ml.scoring import (
    GoldenTaskRegistry,
)
from backend.ml.vector_store import VectorStore

router = APIRouter(prefix="/ml/eval", tags=["ml-eval"])

# Singletons
_eval = LLMEvalFramework()
_ab = ABExperimentHarness()
_golden = GoldenTaskRegistry()
_bench = BenchmarkSuite()
_mlflow = MLflowTracker()
_vector = VectorStore(in_memory=True)  # Default to in-memory; override in prod


# ── Request Models ───────────────────────────────────────


class EvalRequest(BaseModel):
    case_id: str
    task_type: str = "general"
    input_prompt: str
    expected_output: str = ""
    actual_output: str
    model: str = ""
    temperature: float = 0.7
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    context: dict[str, Any] = {}
    dimensions: list[str] | None = None


class ABCreateRequest(BaseModel):
    name: str
    description: str = ""
    variants: list[dict[str, Any]]
    metric_for_winner: str = "avg_score"


class ABRecordRequest(BaseModel):
    variant_name: str
    case_result: dict[str, Any]


class GoldenTaskRequest(BaseModel):
    task_id: str
    task_type: str
    description: str
    input_prompt: str
    expected_output: str
    scoring_method: str = "exact_match"
    rubric_criteria: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    tags: list[str] = []
    difficulty: str = "medium"


class GoldenScoreRequest(BaseModel):
    actual_output: str


class SuiteCreateRequest(BaseModel):
    suite_id: str
    name: str
    description: str = ""
    cases: list[dict[str, Any]]


class MemoryStoreRequest(BaseModel):
    agent_name: str
    content: str
    embedding: list[float]
    memory_type: str = "conversation"
    metadata: dict[str, Any] = {}


class MemoryRecallRequest(BaseModel):
    agent_name: str
    query_embedding: list[float]
    limit: int = 10
    memory_type: str | None = None


class MLflowRunRequest(BaseModel):
    run_name: str
    params: dict[str, Any] = {}
    tags: dict[str, str] = {}


class MLflowLLMCallRequest(BaseModel):
    run_id: str
    model: str
    prompt: str
    response: str = ""
    temperature: float = 0.7
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    eval_score: float | None = None
    pass_fail: bool | None = None
    task_type: str = ""


# ── Eval Endpoints ───────────────────────────────────────


@router.post("/run")
async def run_evaluation(req: EvalRequest) -> dict[str, Any]:
    """Run LLM evaluation on a single case."""
    case = EvalCase(
        case_id=req.case_id,
        task_type=req.task_type,
        input_prompt=req.input_prompt,
        expected_output=req.expected_output,
        actual_output=req.actual_output,
        model=req.model,
        temperature=req.temperature,
        latency_ms=req.latency_ms,
        tokens_in=req.tokens_in,
        tokens_out=req.tokens_out,
        cost_usd=req.cost_usd,
        context=req.context,
    )
    dims = [EvalDimension(d) for d in req.dimensions] if req.dimensions else None
    result = _eval.evaluate(case, dimensions=dims)
    return result.to_dict()


@router.get("/results")
async def get_eval_results(
    task_type: str | None = None,
    model: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return _eval.get_results(task_type=task_type, model=model, limit=limit)


@router.get("/summary")
async def get_eval_summary(
    task_type: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _eval.get_summary(task_type=task_type, model=model)


# ── A/B Experiment Endpoints ─────────────────────────────


@router.post("/ab/create")
async def create_ab_experiment(req: ABCreateRequest) -> dict[str, Any]:
    exp_id = _ab.create_experiment(
        name=req.name,
        variants=req.variants,
        description=req.description,
        metric_for_winner=req.metric_for_winner,
    )
    return {"experiment_id": exp_id}


@router.post("/ab/{experiment_id}/record")
async def record_ab_case(experiment_id: str, req: ABRecordRequest) -> dict[str, str]:
    try:
        _ab.record_variant_case(experiment_id, req.variant_name, req.case_result)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "recorded"}


@router.post("/ab/{experiment_id}/complete")
async def complete_ab_experiment(experiment_id: str) -> dict[str, Any]:
    try:
        return _ab.complete_experiment(experiment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ab/{experiment_id}")
async def get_ab_experiment(experiment_id: str) -> dict[str, Any]:
    try:
        return _ab.get_experiment(experiment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ab/{experiment_id}/compare")
async def compare_ab_variants(experiment_id: str) -> dict[str, Any]:
    try:
        return _ab.compare_variants(experiment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ab")
async def list_ab_experiments(status: str | None = None) -> list[dict[str, Any]]:
    return _ab.list_experiments(status=status)


# ── Golden Task Endpoints ────────────────────────────────


@router.post("/golden/add")
async def add_golden_task(req: GoldenTaskRequest) -> dict[str, str]:
    task_id = _golden.add_task(req.model_dump())
    return {"task_id": task_id}


@router.get("/golden/{task_id}")
async def get_golden_task(task_id: str) -> dict[str, Any]:
    try:
        return _golden.get_task(task_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/golden")
async def list_golden_tasks(
    task_type: str | None = None,
    difficulty: str | None = None,
) -> list[dict[str, Any]]:
    return _golden.list_tasks(task_type=task_type, difficulty=difficulty)


@router.post("/golden/{task_id}/score")
async def score_golden_task(task_id: str, req: GoldenScoreRequest) -> dict[str, Any]:
    try:
        result = _golden.score_against_golden(task_id, req.actual_output)
        return result.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/golden/{task_id}")
async def delete_golden_task(task_id: str) -> dict[str, str]:
    _golden.remove_task(task_id)
    return {"status": "deleted"}


# ── Benchmark Endpoints ──────────────────────────────────


@router.post("/bench/suite")
async def create_benchmark_suite(req: SuiteCreateRequest) -> dict[str, str]:
    suite_id = _bench.create_suite(
        suite_id=req.suite_id,
        name=req.name,
        cases=req.cases,
        description=req.description,
    )
    return {"suite_id": suite_id}


@router.get("/bench/suites")
async def list_benchmark_suites() -> list[dict[str, Any]]:
    return _bench.list_suites()


@router.get("/bench/suite/{suite_id}")
async def get_benchmark_suite(suite_id: str) -> dict[str, Any]:
    try:
        return _bench.get_suite(suite_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/bench/history/{suite_id}")
async def get_benchmark_history(
    suite_id: str,
    model: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return _bench.get_history(suite_id, model=model, limit=limit)


@router.post("/bench/defaults/capabilities")
async def create_default_capability_suite() -> dict[str, str]:
    data = BenchmarkSuite.create_capability_suite()
    _bench.create_suite(**data)
    return {"suite_id": data["suite_id"]}


@router.post("/bench/defaults/webgen")
async def create_default_webgen_suite() -> dict[str, str]:
    data = BenchmarkSuite.create_webgen_suite()
    _bench.create_suite(**data)
    return {"suite_id": data["suite_id"]}


# ── Memory / Vector Store Endpoints ──────────────────────


@router.post("/memory/store")
async def store_memory(req: MemoryStoreRequest) -> dict[str, str]:
    point_id = _vector.store_memory(
        agent_name=req.agent_name,
        content=req.content,
        embedding=req.embedding,
        memory_type=req.memory_type,
        metadata=req.metadata,
    )
    return {"point_id": point_id}


@router.post("/memory/recall")
async def recall_memories(req: MemoryRecallRequest) -> list[dict[str, Any]]:
    return _vector.recall_memories(
        agent_name=req.agent_name,
        query_embedding=req.query_embedding,
        limit=req.limit,
        memory_type=req.memory_type,
    )


@router.get("/memory/collections")
async def list_collections() -> list[str]:
    return _vector.list_collections()


# ── MLflow Endpoints ─────────────────────────────────────


@router.get("/mlflow/runs")
async def search_mlflow_runs(
    filter_string: str = "",
    max_results: int = 100,
) -> list[dict[str, Any]]:
    return _mlflow.search_runs(filter_string=filter_string, max_results=max_results)


@router.get("/mlflow/best")
async def get_best_mlflow_run(
    metric: str = "eval_score",
    higher_is_better: bool = True,
) -> dict[str, Any]:
    result = _mlflow.get_best_run(metric=metric, higher_is_better=higher_is_better)
    if not result:
        raise HTTPException(status_code=404, detail="No runs found")
    return result


@router.post("/mlflow/log-llm-call")
async def log_mlflow_llm_call(req: MLflowLLMCallRequest) -> dict[str, str]:
    _mlflow.log_llm_call(
        run_id=req.run_id,
        model=req.model,
        prompt=req.prompt,
        response=req.response,
        temperature=req.temperature,
        latency_ms=req.latency_ms,
        tokens_in=req.tokens_in,
        tokens_out=req.tokens_out,
        cost_usd=req.cost_usd,
        eval_score=req.eval_score,
        pass_fail=req.pass_fail,
        task_type=req.task_type,
    )
    return {"status": "logged"}
