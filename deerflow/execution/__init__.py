"""
deerflow.execution — Post-execution analysis subsystem.

Inspired by HKUDS/OpenSpace's trajectory recording and analysis loop.
See docs/INSPIRATIONS.md for attribution.

Components:
    ExecutionRecorder  — writes a structured JSONL trajectory file per agent run
    ExecutionAnalyzer  — async LLM analysis of recorded runs; feeds judgments
                         into ToolHealthMonitor and ToolRepairEngine
"""

from deerflow.execution.recorder import ExecutionRecorder, RunRecord, ToolCallEntry
from deerflow.execution.analyzer import ExecutionAnalyzer, AnalysisJudgment

__all__ = [
    "ExecutionRecorder",
    "RunRecord",
    "ToolCallEntry",
    "ExecutionAnalyzer",
    "AnalysisJudgment",
]
