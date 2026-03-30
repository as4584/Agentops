"""
ML Pipeline Module — Local-first machine learning infrastructure.
=================================================================
Provides experiment tracking, pipeline orchestration, model monitoring,
data versioning, and documentation enforcement for Agentop's ML workloads.

All state is persisted locally (JSON/SQLite). No cloud ML services.
"""

from backend.ml.experiment_tracker import ExperimentTracker
from backend.ml.pipeline import MLPipeline, PipelineStep, PipelineRun
from backend.ml.monitor import MLMonitor
from backend.ml.data_version import DataVersioner
from backend.ml.doc_enforcer import MLDocEnforcer
from backend.ml.mlflow_tracker import MLflowTracker
from backend.ml.eval_framework import LLMEvalFramework, EvalCase, EvalDimension, EvalResult
from backend.ml.ab_experiment import ABExperimentHarness, ABExperiment, Variant, VariantResult
from backend.ml.scoring import (
    ExactMatchScorer,
    RubricScorer,
    AgentJudgeScorer,
    GoldenTaskRegistry,
    GoldenTask,
)
from backend.ml.vector_store import VectorStore
from backend.ml.benchmark import BenchmarkSuite, BenchmarkCase, BenchmarkResult, SuiteReport
from backend.ml.turbo_quant import TurboQuantizer

__all__ = [
    "ExperimentTracker",
    "MLPipeline",
    "PipelineStep",
    "PipelineRun",
    "MLMonitor",
    "DataVersioner",
    "MLDocEnforcer",
    "MLflowTracker",
    "LLMEvalFramework",
    "EvalCase",
    "EvalDimension",
    "EvalResult",
    "ABExperimentHarness",
    "ABExperiment",
    "Variant",
    "VariantResult",
    "ExactMatchScorer",
    "RubricScorer",
    "AgentJudgeScorer",
    "GoldenTaskRegistry",
    "GoldenTask",
    "VectorStore",
    "BenchmarkSuite",
    "BenchmarkCase",
    "BenchmarkResult",
    "SuiteReport",
    "TurboQuantizer",
]
