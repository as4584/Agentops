"""
Model profiles for popular open-source LLMs available through Ollama.
====================================================================
Each profile has metadata to help pick the right model for the right task.

Usage:
    from localllm.models import MODELS, recommend_model

    # Get a model by name
    profile = MODELS["llama3.2"]

    # Find the best model for a task
    model = recommend_model("creative_writing", max_vram_gb=8)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelProfile:
    """Metadata for a local LLM model."""
    name: str                          # Ollama model name (e.g. "llama3.2")
    family: str                        # Model family (e.g. "llama", "mistral")
    parameters: str                    # Parameter count (e.g. "8B", "70B")
    context_window: int                # Max context tokens
    vram_gb: float                     # Approximate VRAM requirement
    strengths: list[str] = field(default_factory=list)
    best_for: list[str] = field(default_factory=list)
    ollama_pull: str = ""              # Exact `ollama pull` command

    def __post_init__(self):
        if not self.ollama_pull:
            self.ollama_pull = self.name


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

MODELS: dict[str, ModelProfile] = {
    # ── Llama family ─────────────────────────────────────
    "llama3.2": ModelProfile(
        name="llama3.2",
        family="llama",
        parameters="3B",
        context_window=128_000,
        vram_gb=2.5,
        strengths=["fast", "efficient", "good reasoning"],
        best_for=["general", "scripting", "classification"],
    ),
    "llama3.2:1b": ModelProfile(
        name="llama3.2:1b",
        family="llama",
        parameters="1B",
        context_window=128_000,
        vram_gb=1.0,
        strengths=["ultra-fast", "minimal resources"],
        best_for=["classification", "extraction", "simple tasks"],
    ),
    "llama3.3": ModelProfile(
        name="llama3.3",
        family="llama",
        parameters="70B",
        context_window=128_000,
        vram_gb=40,
        strengths=["state-of-art reasoning", "instruction following"],
        best_for=["complex analysis", "code generation", "creative writing"],
    ),

    # ── Mistral family ───────────────────────────────────
    "mistral": ModelProfile(
        name="mistral",
        family="mistral",
        parameters="7B",
        context_window=32_000,
        vram_gb=4.5,
        strengths=["balanced", "fast", "good at instruction following"],
        best_for=["general", "scripting", "summarization"],
    ),
    "mistral-nemo": ModelProfile(
        name="mistral-nemo",
        family="mistral",
        parameters="12B",
        context_window=128_000,
        vram_gb=7.5,
        strengths=["large context", "multilingual", "strong reasoning"],
        best_for=["analysis", "long documents", "multi-step tasks"],
    ),
    "mistral-small": ModelProfile(
        name="mistral-small",
        family="mistral",
        parameters="24B",
        context_window=32_000,
        vram_gb=14,
        strengths=["strong instruction following", "good coding"],
        best_for=["code", "analysis", "structured output"],
    ),

    # ── DeepSeek family ──────────────────────────────────
    "deepseek-r1": ModelProfile(
        name="deepseek-r1",
        family="deepseek",
        parameters="7B",
        context_window=64_000,
        vram_gb=4.5,
        strengths=["chain-of-thought", "math", "reasoning"],
        best_for=["analysis", "data processing", "logic tasks"],
    ),
    "deepseek-r1:14b": ModelProfile(
        name="deepseek-r1:14b",
        family="deepseek",
        parameters="14B",
        context_window=64_000,
        vram_gb=9,
        strengths=["strong reasoning", "coding"],
        best_for=["code review", "complex analysis", "planning"],
    ),

    # ── Qwen family ──────────────────────────────────────
    "qwen2.5": ModelProfile(
        name="qwen2.5",
        family="qwen",
        parameters="7B",
        context_window=128_000,
        vram_gb=4.5,
        strengths=["multilingual", "code", "long context"],
        best_for=["code generation", "multilingual tasks", "analysis"],
    ),
    "qwen2.5-coder": ModelProfile(
        name="qwen2.5-coder",
        family="qwen",
        parameters="7B",
        context_window=128_000,
        vram_gb=4.5,
        strengths=["code-specialized", "inline completion"],
        best_for=["code generation", "refactoring", "debugging"],
    ),

    # ── Gemma family ─────────────────────────────────────
    "gemma2": ModelProfile(
        name="gemma2",
        family="gemma",
        parameters="9B",
        context_window=8_192,
        vram_gb=5.5,
        strengths=["balanced", "good at structured output"],
        best_for=["general", "classification", "extraction"],
    ),
    "gemma2:2b": ModelProfile(
        name="gemma2:2b",
        family="gemma",
        parameters="2B",
        context_window=8_192,
        vram_gb=1.5,
        strengths=["fast", "efficient"],
        best_for=["simple tasks", "classification", "edge deployment"],
    ),

    # ── Phi family ───────────────────────────────────────
    "phi4": ModelProfile(
        name="phi4",
        family="phi",
        parameters="14B",
        context_window=16_384,
        vram_gb=8,
        strengths=["strong reasoning", "instruction following"],
        best_for=["analysis", "coding", "structured output"],
    ),

    # ── Embedding models ─────────────────────────────────
    "nomic-embed-text": ModelProfile(
        name="nomic-embed-text",
        family="nomic",
        parameters="137M",
        context_window=8_192,
        vram_gb=0.3,
        strengths=["fast embeddings", "good clustering"],
        best_for=["embeddings", "semantic search", "RAG"],
    ),
    "mxbai-embed-large": ModelProfile(
        name="mxbai-embed-large",
        family="mixedbread",
        parameters="335M",
        context_window=512,
        vram_gb=0.7,
        strengths=["high quality embeddings"],
        best_for=["embeddings", "retrieval", "similarity"],
    ),
}


# ---------------------------------------------------------------------------
# Task → Model Recommendations
# ---------------------------------------------------------------------------

_TASK_MODELS: dict[str, list[str]] = {
    "script_writing": ["mistral-nemo", "llama3.2", "qwen2.5", "mistral"],
    "creative_writing": ["mistral-nemo", "llama3.3", "qwen2.5"],
    "code_generation": ["qwen2.5-coder", "deepseek-r1:14b", "mistral-small"],
    "analysis": ["deepseek-r1:14b", "phi4", "mistral-nemo"],
    "classification": ["llama3.2:1b", "gemma2:2b", "llama3.2"],
    "extraction": ["llama3.2", "gemma2", "mistral"],
    "summarization": ["mistral", "llama3.2", "gemma2"],
    "json_output": ["phi4", "mistral-small", "qwen2.5"],
    "embeddings": ["nomic-embed-text", "mxbai-embed-large"],
    "general": ["llama3.2", "mistral", "qwen2.5"],
    "hashtags": ["llama3.2", "mistral", "gemma2"],
    "qa_review": ["deepseek-r1", "phi4", "mistral-nemo"],
    "content_strategy": ["mistral-nemo", "deepseek-r1:14b", "llama3.3"],
}


def recommend_model(
    task: str,
    max_vram_gb: float = 999,
    prefer_fast: bool = False,
) -> Optional[str]:
    """
    Recommend the best available model for a task within VRAM constraints.

    Args:
        task: Task type key (see _TASK_MODELS).
        max_vram_gb: Maximum VRAM budget in GB.
        prefer_fast: If True, prefer smaller/faster models.

    Returns:
        Model name string, or None if no match.
    """
    candidates = _TASK_MODELS.get(task, _TASK_MODELS["general"])

    for name in candidates:
        profile = MODELS.get(name)
        if profile and profile.vram_gb <= max_vram_gb:
            return name

    # Fallback: smallest model that fits
    by_size = sorted(MODELS.values(), key=lambda m: m.vram_gb)
    for m in by_size:
        if m.vram_gb <= max_vram_gb and "embed" not in m.name:
            return m.name

    return None
