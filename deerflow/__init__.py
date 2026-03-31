"""
DeerFlow — High-value components inspired by ByteDance's deer-flow architecture
and HKUDS/OpenSpace's skill evolution engine.

Composable middleware, LLM-powered fact memory, context summarization,
sub-agent task delegation, progressive skill loading, tool health tracking,
and post-execution analysis — all wired into Agentop's governance model
(DriftGuard, MemoryStore, OllamaClient).

See docs/INSPIRATIONS.md for attribution and design rationale.
"""

from deerflow.delegation.task import SubTask, TaskDelegator, TaskResult
from deerflow.execution.analyzer import AnalysisJudgment, ExecutionAnalyzer
from deerflow.execution.recorder import ExecutionRecorder, RunRecord, ToolCallEntry
from deerflow.memory.facts import Fact, FactMemory
from deerflow.middleware.chain import Middleware, MiddlewareChain
from deerflow.middleware.summarization import SummarizationMiddleware
from deerflow.skills.progressive import ProgressiveSkillLoader
from deerflow.tools.health import ToolFailureRecord, ToolHealthMonitor, ToolHealthStats
from deerflow.tools.middleware import ToolHealthMiddleware, detect_tool_failure
from deerflow.tools.repair import RepairSuggestion, ToolRepairEngine

__all__ = [
    "MiddlewareChain",
    "Middleware",
    "FactMemory",
    "Fact",
    "SummarizationMiddleware",
    "TaskDelegator",
    "SubTask",
    "TaskResult",
    "ProgressiveSkillLoader",
    "ToolHealthMonitor",
    "ToolFailureRecord",
    "ToolHealthStats",
    "ToolRepairEngine",
    "RepairSuggestion",
    "detect_tool_failure",
    "ToolHealthMiddleware",
    "ExecutionRecorder",
    "RunRecord",
    "ToolCallEntry",
    "ExecutionAnalyzer",
    "AnalysisJudgment",
]
