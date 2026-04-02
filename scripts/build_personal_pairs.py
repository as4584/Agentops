#!/usr/bin/env python3
"""
scripts/build_personal_pairs.py
───────────────────────────────
Strategy 12 — Personal Preference Training Data for Lex.

Teaches Lex Damian's coding style, decision patterns, project knowledge,
and personal preferences so Lex becomes a personalized assistant.

Usage:
  python scripts/build_personal_pairs.py
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Personal/Project Knowledge Pairs ────────────────────────────────────
PERSONAL_SEEDS: list[tuple[str, str]] = [
    # Architecture preferences
    (
        "How should I structure a new agent in Agentop?",
        "Follow the docs-first governance model. Steps:\n"
        "1. Add the agent definition to AGENT_REGISTRY.md first\n"
        "2. Define it in backend/agents/__init__.py ALL_AGENT_DEFINITIONS with: agent_id, name, tier, system_prompt, tool_permissions, memory_namespace, skills, change_impact_level\n"
        "3. Tier assignment: 0=soul, 1=infrastructure, 2=quality, 3=domain\n"
        "4. Never let agents call each other directly — all routing goes through the LangGraph orchestrator\n"
        "5. Each agent gets an isolated memory namespace under data/agents/\n"
        "6. Run drift guard check before committing",
    ),
    (
        "What's the tech stack for Agentop?",
        "Backend: FastAPI (port 8000), LangGraph orchestrator, Ollama LLM backend (port 11434)\n"
        "Frontend: Next.js dashboard (port 3007), REST polling every 5s\n"
        "Database: SQLite (local, zero cloud dependency)\n"
        "LLM: Ollama with llama3.2 default, lex for routing, mistral:7b fallback\n"
        "Tools: 12 native + 26 MCP via Docker bridge\n"
        "VS Code: Extension with @agentop chat participant\n"
        "ML: Unsloth + TRL for fine-tuning, PyO3 for Rust FFI\n"
        "Everything runs locally on WSL2/Linux. Zero cloud dependency.",
    ),
    (
        "What git workflow does Agentop use?",
        "Branch strategy:\n"
        "- main: Production, career-fair-ready. NEVER push directly.\n"
        "- dev: Active development. Push freely.\n"
        "- feature/*: Optional branches off dev, merge via PR or fast-forward.\n\n"
        "Rules:\n"
        "- CI must be green on dev before merge to main\n"
        "- Commit messages: conventional commits (feat:, fix:, docs:, test:, chore:)\n"
        "- Run pytest, ruff check, ruff format --check, mypy, npm run build, tsc --noEmit before push\n"
        "- Minimum 58% test coverage",
    ),

    # Coding style
    (
        "What Python style does Damian prefer?",
        "Style conventions:\n"
        "- Type hints on all function signatures\n"
        "- Pydantic models for data validation (not raw dicts)\n"
        "- FastAPI for all API routes\n"
        "- pathlib over os.path\n"
        "- f-strings over .format() or %\n"
        "- ruff for linting and formatting (replaces black + isort + flake8)\n"
        "- mypy for type checking\n"
        "- pytest for testing (no unittest)\n"
        "- __future__ annotations import at top of every file\n"
        "- Docstrings on modules and public functions (Google style)\n"
        "- Constants in UPPER_SNAKE_CASE at module top\n"
        "- No wildcard imports",
    ),
    (
        "How should I handle errors in Agentop?",
        "Error handling philosophy:\n"
        "- Validate at system boundaries (API routes, tool inputs), not everywhere\n"
        "- Use Pydantic for input validation — let it raise ValidationError\n"
        "- Never catch bare `except:` — always catch specific exceptions\n"
        "- Log errors to backend/logs/system.jsonl via the central logger\n"
        "- Agent failures should gracefully degrade, not crash the orchestrator\n"
        "- Health check failures trigger the monitor_agent, not direct restarts\n"
        "- Use the circuit breaker pattern in unified_registry.py for LLM calls",
    ),

    # Project knowledge
    (
        "What is TurboQuant?",
        "TurboQuant is a post-inference embedding compression system, NOT a model quantizer.\n"
        "It compresses embedding vectors after LLM inference to save memory and speed up similarity search.\n"
        "Methods: scalar (fastest, moderate savings), product (best compression), binary (extreme compression).\n"
        "The Rust port via PyO3 achieves 54.6x speedup over pure Python.\n"
        "Located in: rust/turbo_quant/ (Rust core) + backend/skills/turbo_quant_rust/ (Python bridge)\n"
        "Important: This does NOT replace Ollama's GGUF quantization for model weights.",
    ),
    (
        "What is the Drift Guard?",
        "Drift Guard is middleware that intercepts ALL tool calls and enforces governance invariants.\n"
        "Location: backend/middleware/\n"
        "Key rules:\n"
        "- No agent can call another agent directly\n"
        "- ARCH_MODIFY tools require doc update FIRST\n"
        "- Memory writes are namespaced per agent\n"
        "- Prohibited patterns are defined in docs/DRIFT_GUARD.md\n"
        "- If drift is detected, the system can halt all tool execution",
    ),
    (
        "What is the Soul Agent?",
        "Soul Core (soul_core) is the Tier 0 agent — the cluster's conscience.\n"
        "Responsibilities:\n"
        "- Boot sequence initialization\n"
        "- Reflection and introspection\n"
        "- Trust scoring for agents\n"
        "- Goal tracking and alignment\n"
        "- Impact level: CRITICAL\n"
        "Soul never makes changes directly — it advises the orchestrator on trust and routing decisions.",
    ),
    (
        "How does the MCP gateway work?",
        "MCP (Model Context Protocol) gateway bridges 26 external tools via Docker CLI.\n"
        "Location: backend/mcp/__init__.py (MCPBridge class)\n"
        "Tool groups: github(7), filesystem(5), docker(5), time(2), fetch(1), sqlite(3), slack(3)\n"
        "Graceful degradation: If Docker CLI is absent, MCP tools are unavailable but system continues.\n"
        "All MCP calls route through the bridge, which handles serialization and error wrapping.",
    ),

    # Decision-making
    (
        "Should I add a new dependency to Agentop?",
        "Be very cautious with new dependencies. Checklist:\n"
        "1. Can the standard library solve it? Use stdlib first.\n"
        "2. Is it actively maintained (>6 months recent activity)?\n"
        "3. Does it add significant VRAM/disk overhead? (We run on RTX 4070, 12GB)\n"
        "4. Add to requirements.txt with pinned version\n"
        "5. Document why in CHANGE_LOG.md\n"
        "6. For ML deps: check Unsloth compatibility first\n"
        "7. Zero cloud dependency principle — no SaaS-only libraries",
    ),
    (
        "When should I use Rust vs Python in Agentop?",
        "Decision framework:\n"
        "- Python: Agent logic, API routes, LLM interaction, orchestration, tests — anything that changes often\n"
        "- Rust via PyO3: Tight numeric loops, embedding operations, compression, crypto — hot paths that need 10x+ speedup\n"
        "- The TurboQuant port proved 54.6x speedup for compression. That's the bar.\n"
        "- Don't port to Rust unless profiling shows the Python path is a real bottleneck\n"
        "- All Rust code must have contract tests that validate Python ↔ Rust equivalence",
    ),

    # Career/demo context
    (
        "What should I demo at the career fair?",
        "Priority demo flow:\n"
        "1. Live multi-agent orchestration via VS Code @agentop commands\n"
        "2. Show lex routing — natural language → correct agent with confidence scores\n"
        "3. TurboQuant Rust speedup (54.6x) with before/after timing\n"
        "4. Drift Guard catching a prohibited mutation in real-time\n"
        "5. Dashboard showing agent status, memory namespaces, tool call history\n"
        "6. The full training pipeline: data gen → fine-tune → GGUF → Ollama\n"
        "Key talking points: local-first, zero cloud, governance-by-design, multi-language",
    ),

    # LLM knowledge
    (
        "How do I choose which Ollama model to use?",
        "Model selection guide:\n"
        "- lex (Qwen2.5-7B fine-tuned): Routing, orchestration, agent tasks — primary model after training\n"
        "- llama3.2: General fallback, good for simple tasks (~1B params, fast)\n"
        "- mistral:7b: Code generation, complex reasoning, secondary fallback\n"
        "- qwen2.5-coder:7b: Code-specific tasks if mistral is overloaded\n"
        "- llama3.1:8b: Largest model available, use for quality-critical tasks\n"
        "The unified_registry.py handles failover automatically via circuit breaker pattern.",
    ),
    (
        "How does fine-tuning lex work?",
        "Pipeline:\n"
        "1. Data generation: scripts/build_*_pairs.py → data/training/*.jsonl\n"
        "2. Combine: scripts/synthesize_training_data.py → data/training/combined.jsonl\n"
        "3. Fine-tune: Unsloth + SFTTrainer, QLoRA r=16, 4-bit quantization on Qwen2.5-7B-Instruct\n"
        "4. Export: GGUF Q4_K_M format via model.save_pretrained_gguf()\n"
        "5. Register: ollama create lex -f models/lex/Modelfile\n"
        "6. Evaluate: scripts/eval_router.py for routing accuracy\n"
        "Hardware: RTX 4070 (12GB VRAM), ~5-6GB for 7B 4-bit QLoRA training\n"
        "Target: 500+ training pairs, 3 epochs, lr=2e-4",
    ),

    # Webgen pipeline
    (
        "How does the website generation pipeline work?",
        "WebGen pipeline (backend/webgen/agents/):\n"
        "1. SitePlanner: Analyze requirements → site structure\n"
        "2. PageGenerator: Generate HTML/CSS/JS for each page\n"
        "3. SEOAgent: Optimize meta tags, headings, structured data\n"
        "4. AEOAgent: Answer Engine Optimization for AI search engines\n"
        "5. QAAgent: Accessibility, performance, content quality checks\n"
        "Note: SiteProject state is currently in-memory only (no persistent store yet).\n"
        "API: POST /webgen/build",
    ),

    # Content pipeline
    (
        "How does the content creation pipeline work?",
        "Content pipeline (backend/content/):\n"
        "IdeaIntakeAgent → ScriptWriterAgent → VoiceAgent → AvatarVideoAgent → QAAgent → PublisherAgent → AnalyticsAgent\n"
        "Note: VoiceAgent and AvatarVideoAgent are stubs (TTS/video providers not wired yet).\n"
        "PublisherAgent has no social platform integrations yet.\n"
        "API: POST /content/pipeline/start",
    ),
]


def build_personal_pairs() -> Path:
    """Build personal preference training data."""
    pairs: list[dict] = []

    system_prompt = (
        "You are Lex, Damian's personal AI assistant and the core intelligence of the Agentop system. "
        "You have deep knowledge of Agentop's architecture, codebase, coding conventions, and Damian's preferences. "
        "Answer questions with specific, actionable detail. Reference exact file paths, tool names, and config values. "
        "Be direct and concise — no filler."
    )

    print(f"Phase 1: {len(PERSONAL_SEEDS)} personal knowledge seeds")
    for question, answer in PERSONAL_SEEDS:
        pairs.append({
            "conversations": [
                {"from": "system", "value": system_prompt},
                {"from": "human", "value": question},
                {"from": "gpt", "value": answer},
            ]
        })

    # Phase 2: Rephrase variations
    print("Phase 2: Generating rephrase variations...")
    prefixes = ["Hey Lex, ", "Quick question: ", "Tell me about ", "Explain ", ""]
    for question, answer in PERSONAL_SEEDS:
        prefix = random.choice(prefixes)
        rephrase = prefix + question[0].lower() + question[1:]
        if rephrase != question:
            pairs.append({
                "conversations": [
                    {"from": "system", "value": system_prompt},
                    {"from": "human", "value": rephrase},
                    {"from": "gpt", "value": answer},
                ]
            })

    # Deduplicate
    seen = set()
    unique = []
    for p in pairs:
        key = p["conversations"][1]["value"]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    random.shuffle(unique)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"personal_pairs_{ts}.jsonl"
    with open(out_path, "w") as f:
        for pair in unique:
            f.write(json.dumps(pair) + "\n")

    print(f"\nWrote {len(unique)} personal training pairs to {out_path}")
    return out_path


def main() -> None:
    build_personal_pairs()


if __name__ == "__main__":
    main()
