"""
LLM Model Knowledge Base — Comprehensive model index for intelligent routing.
=============================================================================
Contains structured knowledge about every major open-source LLM available
through Ollama, with use-case vectors for the prompt_engineer agent to
query when recommending the optimal model for a task.

This is the SOURCE OF TRUTH for model capabilities within Agentop.
Updated: 2026-03-01
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Structured model knowledge entries — each model gets a rich profile
# ---------------------------------------------------------------------------

LLM_MODEL_KNOWLEDGE: list[dict[str, Any]] = [
    # ── Llama Family ──────────────────────────────────────────────────────
    {
        "model_id": "llama3.2:latest",
        "family": "Meta Llama",
        "parameters": "3B",
        "quantisation": "Q4_K_M",
        "vram_gb": 2.5,
        "context_window": 131072,
        "licence": "Llama 3.2 Community",
        "release_date": "2024-09",
        "strengths": [
            "Fast inference on low-end hardware",
            "Good general chat quality for size",
            "Efficient for high-throughput workloads",
            "Strong instruction following",
        ],
        "weaknesses": [
            "Limited reasoning on complex multi-step problems",
            "Weaker code generation than larger models",
            "May hallucinate on niche technical topics",
        ],
        "best_for": [
            "Quick chat responses",
            "Simple Q&A routing",
            "Customer support triage",
            "Lightweight classification tasks",
            "High-volume low-latency workloads",
        ],
        "avoid_for": [
            "Complex code generation",
            "Multi-step mathematical reasoning",
            "Legal or medical analysis",
        ],
        "ollama_pull": "ollama pull llama3.2",
        "speed_tier": "fast",
        "quality_tier": "good",
        "code_score": 5,
        "reasoning_score": 5,
        "instruction_score": 7,
        "multilingual_score": 4,
        "creative_score": 6,
    },
    {
        "model_id": "llama3.1:8b",
        "family": "Meta Llama",
        "parameters": "8B",
        "quantisation": "Q4_K_M",
        "vram_gb": 6,
        "context_window": 131072,
        "licence": "Llama 3.1 Community",
        "release_date": "2024-07",
        "strengths": [
            "Strong general reasoning",
            "Good balance of speed and quality",
            "Excellent instruction following",
            "Solid multi-turn conversation",
            "128K context window",
        ],
        "weaknesses": [
            "Code generation below specialised models",
            "Can be verbose",
        ],
        "best_for": [
            "General-purpose agent backbone",
            "Soul Core reasoning",
            "Multi-turn dialogue",
            "Summarisation and analysis",
            "Document Q&A with long context",
        ],
        "avoid_for": [
            "Specialised code completion",
            "Sub-second latency requirements",
        ],
        "ollama_pull": "ollama pull llama3.1:8b",
        "speed_tier": "medium",
        "quality_tier": "high",
        "code_score": 6,
        "reasoning_score": 8,
        "instruction_score": 8,
        "multilingual_score": 6,
        "creative_score": 7,
    },
    {
        "model_id": "llama3.1:70b",
        "family": "Meta Llama",
        "parameters": "70B",
        "quantisation": "Q4_K_M",
        "vram_gb": 40,
        "context_window": 131072,
        "licence": "Llama 3.1 Community",
        "release_date": "2024-07",
        "strengths": [
            "Near frontier-model reasoning",
            "Excellent nuanced instruction following",
            "Strong at complex analysis",
            "Good code generation",
        ],
        "weaknesses": [
            "Requires 40GB+ VRAM",
            "Slow inference without GPU offload",
            "Overkill for simple tasks",
        ],
        "best_for": [
            "Complex multi-step reasoning",
            "Architecture review and planning",
            "Legal/compliance analysis",
            "Long-form content generation",
        ],
        "avoid_for": [
            "Simple classification or routing",
            "High-throughput low-latency needs",
            "Machines with < 40GB VRAM",
        ],
        "ollama_pull": "ollama pull llama3.1:70b",
        "speed_tier": "slow",
        "quality_tier": "excellent",
        "code_score": 8,
        "reasoning_score": 9,
        "instruction_score": 9,
        "multilingual_score": 7,
        "creative_score": 8,
    },
    {
        "model_id": "llama3.3:70b",
        "family": "Meta Llama",
        "parameters": "70B",
        "quantisation": "Q4_K_M",
        "vram_gb": 40,
        "context_window": 131072,
        "licence": "Llama 3.3 Community",
        "release_date": "2024-12",
        "strengths": [
            "Improved reasoning over 3.1",
            "Better tool calling",
            "Enhanced multilingual performance",
            "State of the art for open 70B",
        ],
        "weaknesses": [
            "Same VRAM requirements as 3.1:70b",
            "Slow without dedicated GPU",
        ],
        "best_for": [
            "Top-tier local reasoning",
            "Tool-use orchestration",
            "Complex analysis and planning",
            "Multilingual enterprise tasks",
        ],
        "avoid_for": [
            "Low-end hardware",
            "Simple chat / triage",
        ],
        "ollama_pull": "ollama pull llama3.3:70b",
        "speed_tier": "slow",
        "quality_tier": "excellent",
        "code_score": 8,
        "reasoning_score": 10,
        "instruction_score": 9,
        "multilingual_score": 8,
        "creative_score": 8,
    },
    # ── Mistral Family ────────────────────────────────────────────────────
    {
        "model_id": "mistral:7b",
        "family": "Mistral AI",
        "parameters": "7B",
        "quantisation": "Q4_K_M",
        "vram_gb": 6,
        "context_window": 32768,
        "licence": "Apache 2.0",
        "release_date": "2023-09",
        "strengths": [
            "Excellent speed-to-quality ratio",
            "Strong code generation for 7B class",
            "Good at structured output (JSON, YAML)",
            "Apache 2.0 licence — fully commercial",
        ],
        "weaknesses": [
            "32K context (shorter than Llama)",
            "Weaker at creative/narrative writing",
        ],
        "best_for": [
            "Code generation and review",
            "DevOps agent tasks",
            "Structured output extraction",
            "IT operations",
            "API response generation",
        ],
        "avoid_for": [
            "Very long documents (>32K tokens)",
            "Creative writing",
        ],
        "ollama_pull": "ollama pull mistral:7b",
        "speed_tier": "fast",
        "quality_tier": "high",
        "code_score": 8,
        "reasoning_score": 7,
        "instruction_score": 7,
        "multilingual_score": 5,
        "creative_score": 5,
    },
    {
        "model_id": "mixtral:8x7b",
        "family": "Mistral AI",
        "parameters": "47B (8x7B MoE)",
        "quantisation": "Q4_K_M",
        "vram_gb": 24,
        "context_window": 32768,
        "licence": "Apache 2.0",
        "release_date": "2023-12",
        "strengths": [
            "Mixture-of-experts — only 12B active per token",
            "Excellent quality for effective compute",
            "Strong code and reasoning",
            "Good multilingual coverage",
        ],
        "weaknesses": [
            "Needs 24GB VRAM for full model",
            "Slower first-token latency than dense 7B",
        ],
        "best_for": [
            "Balanced quality + efficiency",
            "Multi-domain agent cluster backbone",
            "Code + reasoning hybrid tasks",
            "Multilingual support scenarios",
        ],
        "avoid_for": [
            "Machines with < 24GB VRAM",
            "Sub-100ms latency requirements",
        ],
        "ollama_pull": "ollama pull mixtral:8x7b",
        "speed_tier": "medium",
        "quality_tier": "high",
        "code_score": 8,
        "reasoning_score": 8,
        "instruction_score": 8,
        "multilingual_score": 7,
        "creative_score": 7,
    },
    {
        "model_id": "codestral:latest",
        "family": "Mistral AI",
        "parameters": "22B",
        "quantisation": "Q4_K_M",
        "vram_gb": 14,
        "context_window": 32768,
        "licence": "Mistral AI Non-Production",
        "release_date": "2024-05",
        "strengths": [
            "Purpose-built for code generation",
            "Supports 80+ programming languages",
            "Excellent at code completion and infilling",
            "Strong at explaining code",
        ],
        "weaknesses": [
            "Non-production licence restricts commercial use",
            "Weaker at non-code tasks",
        ],
        "best_for": [
            "Code generation and completion",
            "Code review agent",
            "Bug analysis and fix suggestions",
            "Documentation generation from code",
            "Refactoring recommendations",
        ],
        "avoid_for": [
            "General chat or customer support",
            "Commercial production without licence review",
        ],
        "ollama_pull": "ollama pull codestral",
        "speed_tier": "medium",
        "quality_tier": "excellent",
        "code_score": 10,
        "reasoning_score": 7,
        "instruction_score": 7,
        "multilingual_score": 3,
        "creative_score": 3,
    },
    # ── DeepSeek Family ───────────────────────────────────────────────────
    {
        "model_id": "deepseek-coder-v2:latest",
        "family": "DeepSeek",
        "parameters": "16B",
        "quantisation": "Q4_K_M",
        "vram_gb": 10,
        "context_window": 128000,
        "licence": "DeepSeek",
        "release_date": "2024-06",
        "strengths": [
            "Exceptional code generation",
            "128K context window",
            "Strong at code reasoning and debugging",
            "Good at mathematical problem solving",
        ],
        "weaknesses": [
            "Weaker at general chat than Llama 3.1",
            "Less creative writing ability",
        ],
        "best_for": [
            "Code review and security audit",
            "DevOps automation scripts",
            "Mathematical and algorithmic tasks",
            "Large codebase analysis (128K context)",
            "Self-healer remediation scripts",
        ],
        "avoid_for": [
            "Customer support dialogue",
            "Creative content generation",
        ],
        "ollama_pull": "ollama pull deepseek-coder-v2",
        "speed_tier": "medium",
        "quality_tier": "excellent",
        "code_score": 10,
        "reasoning_score": 8,
        "instruction_score": 7,
        "multilingual_score": 4,
        "creative_score": 3,
    },
    {
        "model_id": "deepseek-r1:latest",
        "family": "DeepSeek",
        "parameters": "7B (distilled)",
        "quantisation": "Q4_K_M",
        "vram_gb": 5,
        "context_window": 65536,
        "licence": "MIT",
        "release_date": "2025-01",
        "strengths": [
            "Chain-of-thought reasoning built in",
            "Excellent mathematical reasoning",
            "Shows working steps explicitly",
            "MIT licence — fully open",
        ],
        "weaknesses": [
            "Verbose due to chain-of-thought scaffolding",
            "Slower effective throughput",
            "Sometimes over-reasons on simple tasks",
        ],
        "best_for": [
            "Complex multi-step reasoning",
            "Mathematical problem solving",
            "Decision analysis with explicit rationale",
            "Planning and strategy tasks",
        ],
        "avoid_for": [
            "Simple quick-answer tasks",
            "High-throughput workloads",
            "Tasks requiring concise output",
        ],
        "ollama_pull": "ollama pull deepseek-r1",
        "speed_tier": "medium",
        "quality_tier": "high",
        "code_score": 7,
        "reasoning_score": 9,
        "instruction_score": 7,
        "multilingual_score": 5,
        "creative_score": 5,
    },
    # ── Qwen Family ───────────────────────────────────────────────────────
    {
        "model_id": "qwen2.5:7b",
        "family": "Alibaba Qwen",
        "parameters": "7B",
        "quantisation": "Q4_K_M",
        "vram_gb": 5,
        "context_window": 131072,
        "licence": "Apache 2.0",
        "release_date": "2024-09",
        "strengths": [
            "Excellent multilingual performance (29 languages)",
            "Strong code generation for 7B class",
            "128K context window",
            "Apache 2.0 — fully commercial",
            "Best-in-class structured output",
        ],
        "weaknesses": [
            "Slightly weaker creative English than Llama 3.1",
        ],
        "best_for": [
            "Multilingual customer support",
            "Data analysis and extraction",
            "JSON/structured output generation",
            "International markets / multi-language ops",
            "Code generation with long context",
        ],
        "avoid_for": [
            "Tasks requiring peak English creative writing",
        ],
        "ollama_pull": "ollama pull qwen2.5:7b",
        "speed_tier": "fast",
        "quality_tier": "high",
        "code_score": 8,
        "reasoning_score": 7,
        "instruction_score": 8,
        "multilingual_score": 10,
        "creative_score": 6,
    },
    {
        "model_id": "qwen2.5:72b",
        "family": "Alibaba Qwen",
        "parameters": "72B",
        "quantisation": "Q4_K_M",
        "vram_gb": 42,
        "context_window": 131072,
        "licence": "Qwen",
        "release_date": "2024-09",
        "strengths": [
            "One of the strongest open 72B models",
            "Excellent across all dimensions",
            "State-of-the-art multilingual",
            "128K context",
        ],
        "weaknesses": [
            "Requires 42GB+ VRAM",
            "Slow without dedicated GPU",
        ],
        "best_for": [
            "Enterprise-grade reasoning",
            "Multilingual complex analysis",
            "Long-document understanding",
        ],
        "avoid_for": [
            "Low-end hardware",
            "Simple routing tasks",
        ],
        "ollama_pull": "ollama pull qwen2.5:72b",
        "speed_tier": "slow",
        "quality_tier": "excellent",
        "code_score": 9,
        "reasoning_score": 9,
        "instruction_score": 9,
        "multilingual_score": 10,
        "creative_score": 8,
    },
    {
        "model_id": "qwen2.5-coder:7b",
        "family": "Alibaba Qwen",
        "parameters": "7B",
        "quantisation": "Q4_K_M",
        "vram_gb": 5,
        "context_window": 131072,
        "licence": "Apache 2.0",
        "release_date": "2024-11",
        "strengths": [
            "Purpose-built for code — on par with much larger models",
            "128K context for large codebase analysis",
            "Strong at code explanation and docstring generation",
            "Apache 2.0 licence",
        ],
        "weaknesses": [
            "Weaker at non-code tasks",
        ],
        "best_for": [
            "Code review agent",
            "Security scanning code analysis",
            "Automated refactoring suggestions",
            "Code documentation generation",
        ],
        "avoid_for": [
            "General chat",
            "Non-technical tasks",
        ],
        "ollama_pull": "ollama pull qwen2.5-coder:7b",
        "speed_tier": "fast",
        "quality_tier": "high",
        "code_score": 9,
        "reasoning_score": 6,
        "instruction_score": 7,
        "multilingual_score": 5,
        "creative_score": 3,
    },
    # ── Google Gemma Family ───────────────────────────────────────────────
    {
        "model_id": "gemma2:9b",
        "family": "Google Gemma",
        "parameters": "9B",
        "quantisation": "Q4_K_M",
        "vram_gb": 7,
        "context_window": 8192,
        "licence": "Gemma Terms of Use",
        "release_date": "2024-06",
        "strengths": [
            "Strong reasoning for size",
            "Google's training data quality",
            "Good for knowledge-intensive Q&A",
            "Efficient architecture",
        ],
        "weaknesses": [
            "Only 8K context window",
            "Weaker code generation than specialists",
        ],
        "best_for": [
            "Knowledge Q&A",
            "Short-context reasoning",
            "General assistant tasks",
            "Summarisation",
        ],
        "avoid_for": [
            "Long document analysis",
            "Code-heavy workflows",
        ],
        "ollama_pull": "ollama pull gemma2:9b",
        "speed_tier": "fast",
        "quality_tier": "high",
        "code_score": 6,
        "reasoning_score": 8,
        "instruction_score": 7,
        "multilingual_score": 6,
        "creative_score": 7,
    },
    {
        "model_id": "gemma2:27b",
        "family": "Google Gemma",
        "parameters": "27B",
        "quantisation": "Q4_K_M",
        "vram_gb": 18,
        "context_window": 8192,
        "licence": "Gemma Terms of Use",
        "release_date": "2024-06",
        "strengths": [
            "Excellent reasoning",
            "Strong safety alignment",
            "Good knowledge breadth",
        ],
        "weaknesses": [
            "8K context only",
            "Needs 18GB VRAM",
        ],
        "best_for": [
            "Complex reasoning on short inputs",
            "Safety-critical applications",
            "Knowledge Q&A",
        ],
        "avoid_for": [
            "Long context tasks",
            "Low-end hardware",
        ],
        "ollama_pull": "ollama pull gemma2:27b",
        "speed_tier": "medium",
        "quality_tier": "excellent",
        "code_score": 7,
        "reasoning_score": 9,
        "instruction_score": 8,
        "multilingual_score": 7,
        "creative_score": 7,
    },
    # ── Microsoft Phi Family ──────────────────────────────────────────────
    {
        "model_id": "phi3:medium",
        "family": "Microsoft Phi",
        "parameters": "14B",
        "quantisation": "Q4_K_M",
        "vram_gb": 10,
        "context_window": 128000,
        "licence": "MIT",
        "release_date": "2024-04",
        "strengths": [
            "Punches well above weight",
            "128K context window",
            "MIT licence",
            "Strong at reasoning and math",
            "Efficient inference",
        ],
        "weaknesses": [
            "Can be overly safety-cautious",
            "Weaker multilingual than Qwen",
        ],
        "best_for": [
            "Mid-tier reasoning tasks",
            "Long-context analysis",
            "Mathematical and logical tasks",
            "Monitor/analysis agents",
        ],
        "avoid_for": [
            "Tasks requiring edgy or unfiltered output",
            "Heavy multilingual workflows",
        ],
        "ollama_pull": "ollama pull phi3:medium",
        "speed_tier": "medium",
        "quality_tier": "high",
        "code_score": 7,
        "reasoning_score": 8,
        "instruction_score": 7,
        "multilingual_score": 5,
        "creative_score": 6,
    },
    {
        "model_id": "phi4:latest",
        "family": "Microsoft Phi",
        "parameters": "14B",
        "quantisation": "Q4_K_M",
        "vram_gb": 10,
        "context_window": 16384,
        "licence": "MIT",
        "release_date": "2024-12",
        "strengths": [
            "State-of-the-art for 14B class",
            "Excellent reasoning and STEM",
            "Strong coding ability",
            "MIT licence",
        ],
        "weaknesses": [
            "16K context (shorter than phi3)",
        ],
        "best_for": [
            "STEM reasoning",
            "Code generation",
            "Agent backbone for technical tasks",
        ],
        "avoid_for": [
            "Very long documents",
            "Multilingual edge cases",
        ],
        "ollama_pull": "ollama pull phi4",
        "speed_tier": "medium",
        "quality_tier": "excellent",
        "code_score": 8,
        "reasoning_score": 9,
        "instruction_score": 8,
        "multilingual_score": 5,
        "creative_score": 6,
    },
    # ── Embedding Models ──────────────────────────────────────────────────
    {
        "model_id": "nomic-embed-text:latest",
        "family": "Nomic AI",
        "parameters": "137M",
        "quantisation": "FP16",
        "vram_gb": 0.5,
        "context_window": 8192,
        "licence": "Apache 2.0",
        "release_date": "2024-02",
        "strengths": [
            "Purpose-built for text embeddings",
            "8K context for long passages",
            "Extremely fast",
            "Perfect for RAG pipelines",
        ],
        "weaknesses": [
            "Not a generative model — embeddings only",
        ],
        "best_for": [
            "Vector search / RAG pipelines",
            "Semantic similarity",
            "Document clustering",
            "Knowledge base indexing",
        ],
        "avoid_for": [
            "Text generation of any kind",
        ],
        "ollama_pull": "ollama pull nomic-embed-text",
        "speed_tier": "instant",
        "quality_tier": "excellent",
        "code_score": 0,
        "reasoning_score": 0,
        "instruction_score": 0,
        "multilingual_score": 5,
        "creative_score": 0,
    },
    {
        "model_id": "mxbai-embed-large:latest",
        "family": "Mixed Bread AI",
        "parameters": "335M",
        "quantisation": "FP16",
        "vram_gb": 1,
        "context_window": 512,
        "licence": "Apache 2.0",
        "release_date": "2024-03",
        "strengths": [
            "High-quality dense embeddings",
            "Strong retrieval performance on MTEB benchmarks",
        ],
        "weaknesses": [
            "512 token context limit",
            "Not generative",
        ],
        "best_for": [
            "Short-passage retrieval",
            "FAQ matching",
            "Semantic search on sentences",
        ],
        "avoid_for": [
            "Long documents",
            "Text generation",
        ],
        "ollama_pull": "ollama pull mxbai-embed-large",
        "speed_tier": "instant",
        "quality_tier": "high",
        "code_score": 0,
        "reasoning_score": 0,
        "instruction_score": 0,
        "multilingual_score": 4,
        "creative_score": 0,
    },
    # ── Kimi K2 (Moonshot AI) ─────────────────────────────────────────────
    {
        "model_id": "kimi-k2.5",
        "family": "Moonshot AI",
        "parameters": "236B (MoE, ~32B active)",
        "quantisation": "N/A — not yet in Ollama",
        "vram_gb": 128,
        "context_window": 131072,
        "licence": "Open weights (research)",
        "release_date": "2025-06",
        "strengths": [
            "Massive MoE architecture — 236B total, ~32B active per token",
            "Near GPT-4 level reasoning",
            "128K context window",
            "Strong agentic and tool-use capabilities",
            "Excellent code generation",
        ],
        "weaknesses": [
            "Not yet available via Ollama as of March 2026",
            "Requires 128GB+ VRAM for full precision",
            "Must be run via llama.cpp GGUF manually",
            "Quantised versions reduce quality noticeably",
        ],
        "best_for": [
            "Frontier-level reasoning (when hardware allows)",
            "Complex agentic workflows",
            "Large-scale code generation and review",
            "Enterprise analysis tasks",
        ],
        "avoid_for": [
            "Any machine with < 64GB VRAM",
            "Production deployments until Ollama support lands",
            "Latency-sensitive applications",
        ],
        "ollama_pull": "# NOT AVAILABLE YET — check monthly: ollama pull kimi-k2.5",
        "speed_tier": "slow",
        "quality_tier": "frontier",
        "code_score": 9,
        "reasoning_score": 10,
        "instruction_score": 9,
        "multilingual_score": 8,
        "creative_score": 8,
        "availability_note": "Weights released June 2025. Ollama GGUF pending as of March 2026. Monitor https://ollama.com/library for availability.",
    },
    # ── Specialized: Starcoder ────────────────────────────────────────────
    {
        "model_id": "starcoder2:7b",
        "family": "BigCode",
        "parameters": "7B",
        "quantisation": "Q4_K_M",
        "vram_gb": 5,
        "context_window": 16384,
        "licence": "BigCode OpenRAIL-M",
        "release_date": "2024-02",
        "strengths": [
            "Trained on 600+ languages of code",
            "Strong fill-in-the-middle capability",
            "Good at code completion",
        ],
        "weaknesses": [
            "Not designed for chat or instruction following",
            "Limited natural language ability",
        ],
        "best_for": [
            "Pure code completion / infilling",
            "IDE-style code suggestions",
        ],
        "avoid_for": [
            "Chat or dialogue",
            "Non-code tasks",
        ],
        "ollama_pull": "ollama pull starcoder2:7b",
        "speed_tier": "fast",
        "quality_tier": "high",
        "code_score": 9,
        "reasoning_score": 4,
        "instruction_score": 3,
        "multilingual_score": 2,
        "creative_score": 1,
    },
    # ── Command R (Cohere) ────────────────────────────────────────────────
    {
        "model_id": "command-r:latest",
        "family": "Cohere",
        "parameters": "35B",
        "quantisation": "Q4_K_M",
        "vram_gb": 20,
        "context_window": 131072,
        "licence": "CC-BY-NC-4.0",
        "release_date": "2024-03",
        "strengths": [
            "Purpose-built for RAG workflows",
            "128K context window",
            "Excellent citation and grounding",
            "Strong tool-use ability",
        ],
        "weaknesses": [
            "Non-commercial licence",
            "Needs 20GB+ VRAM",
        ],
        "best_for": [
            "Knowledge agent / RAG backbone",
            "Grounded Q&A with citations",
            "Tool-augmented generation",
            "Enterprise search assistants",
        ],
        "avoid_for": [
            "Commercial production without licence review",
            "Simple chat on low-end hardware",
        ],
        "ollama_pull": "ollama pull command-r",
        "speed_tier": "medium",
        "quality_tier": "excellent",
        "code_score": 6,
        "reasoning_score": 8,
        "instruction_score": 8,
        "multilingual_score": 8,
        "creative_score": 6,
    },
]


# ---------------------------------------------------------------------------
# Recommended agent → model mapping based on knowledge base analysis
# ---------------------------------------------------------------------------

RECOMMENDED_AGENT_MODELS: dict[str, list[dict[str, Any]]] = {
    "cs_agent": [
        {"model": "llama3.2:latest", "reason": "Fast responses, good instruction following, low VRAM"},
        {"model": "qwen2.5:7b", "reason": "Best multilingual support if international customers"},
    ],
    "it_agent": [
        {"model": "mistral:7b", "reason": "Strong structured output + ops commands"},
        {"model": "phi4:latest", "reason": "Excellent STEM/technical reasoning"},
    ],
    "soul_core": [
        {"model": "llama3.1:8b", "reason": "Best balance of reasoning + conversation for governance"},
        {"model": "llama3.3:70b", "reason": "Top-tier reasoning if VRAM allows"},
    ],
    "devops_agent": [
        {"model": "deepseek-coder-v2:latest", "reason": "128K context for large configs + strong code"},
        {"model": "mistral:7b", "reason": "Fast fallback with good code quality"},
    ],
    "monitor_agent": [
        {"model": "llama3.2:latest", "reason": "Fast, lightweight — monitoring is high-frequency"},
        {"model": "phi3:medium", "reason": "Better analysis when deeper reasoning needed"},
    ],
    "self_healer_agent": [
        {"model": "mistral:7b", "reason": "Good at structured remediation scripts"},
        {"model": "deepseek-coder-v2:latest", "reason": "Strong code debugging"},
    ],
    "code_review_agent": [
        {"model": "deepseek-coder-v2:latest", "reason": "Best code analysis + 128K context"},
        {"model": "qwen2.5-coder:7b", "reason": "Fast code-specialised alternative"},
    ],
    "security_agent": [
        {"model": "deepseek-coder-v2:latest", "reason": "Excellent at pattern detection in code"},
        {"model": "qwen2.5-coder:7b", "reason": "Good code scanning with 128K context"},
    ],
    "data_agent": [
        {"model": "qwen2.5:7b", "reason": "Strong structured data extraction + multilingual"},
        {"model": "phi4:latest", "reason": "Excellent at data reasoning and analysis"},
    ],
    "comms_agent": [
        {"model": "llama3.2:latest", "reason": "Good natural language, fast for message drafting"},
        {"model": "llama3.1:8b", "reason": "Better quality for important communications"},
    ],
    "prompt_engineer": [
        {"model": "llama3.1:8b", "reason": "Needs strong meta-reasoning about prompt structure"},
        {"model": "phi4:latest", "reason": "Excellent analytical reasoning for prompt evaluation"},
    ],
    "knowledge_agent": [
        {"model": "command-r:latest", "reason": "Purpose-built for RAG with citation grounding"},
        {"model": "llama3.1:8b", "reason": "Good general RAG backbone with 128K context"},
    ],
}


def get_model_knowledge() -> list[dict[str, Any]]:
    """Return the full LLM model knowledge base."""
    return LLM_MODEL_KNOWLEDGE


def get_model_by_id(model_id: str) -> dict[str, Any] | None:
    """Look up a specific model by its Ollama ID."""
    for m in LLM_MODEL_KNOWLEDGE:
        if m["model_id"] == model_id:
            return m
    return None


def get_models_for_task(task_category: str) -> list[dict[str, Any]]:
    """
    Return models ranked by relevance for a task category.
    
    Categories: code, reasoning, creative, multilingual, speed, embedding
    """
    score_key = {
        "code": "code_score",
        "reasoning": "reasoning_score",
        "creative": "creative_score",
        "multilingual": "multilingual_score",
        "instruction": "instruction_score",
    }.get(task_category, "reasoning_score")

    scored = [
        {**m, "_relevance": m.get(score_key, 0)}
        for m in LLM_MODEL_KNOWLEDGE
        if m.get(score_key, 0) > 0  # exclude embedding models for gen tasks
    ]
    scored.sort(key=lambda x: x["_relevance"], reverse=True)
    return scored


def get_agent_model_recommendation(agent_id: str) -> list[dict[str, Any]]:
    """Return recommended models for a specific agent."""
    return RECOMMENDED_AGENT_MODELS.get(agent_id, [])
