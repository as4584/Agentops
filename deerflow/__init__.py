"""
DeerFlow — High-value components inspired by ByteDance's deer-flow architecture
and HKUDS/OpenSpace's skill evolution engine.

Composable middleware, LLM-powered fact memory, context summarization,
sub-agent task delegation, progressive skill loading, tool health tracking,
and post-execution analysis — all wired into Agentop's governance model
(DriftGuard, MemoryStore, OllamaClient).

See docs/INSPIRATIONS.md for attribution and design rationale.
"""

from deerflow.middleware.chain import MiddlewareChain, Middleware
from deerflow.memory.facts import FactMemory, Fact
from deerflow.middleware.summarization import SummarizationMiddleware
from deerflow.delegation.task import TaskDelegator, SubTask, TaskResult
from deerflow.skills.progressive import ProgressiveSkillLoader
from deerflow.tools.health import ToolHealthMonitor, ToolFailureRecord, ToolHealthStats
from deerflow.tools.repair import ToolRepairEngine, RepairSuggestion
from deerflow.tools.middleware import detect_tool_failure, ToolHealthMiddleware
from deerflow.execution.recorder import ExecutionRecorder, RunRecord, ToolCallEntry
from deerflow.execution.analyzer import ExecutionAnalyzer, AnalysisJudgment

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
