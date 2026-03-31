# ML Eval Framework — Architecture & Usage Guide

> Agentop's LLM evaluation, benchmarking, and optimization stack.
> Added: 2026-03-30 · Commit: `2e9bdcf`

---

## Why This Exists

Running local LLMs (Llama, Qwen, etc.) without measurement is flying blind. This stack answers:

- **Is model A better than model B** for our specific tasks?
- **Did that prompt tweak help** or hurt?
- **Are we regressing** after a config change?
- **How much does quality cost** in tokens, latency, and dollars?

Everything persists to disk (JSON + MLflow) so results survive restarts and build history over time.

---

## Module Map

```
backend/ml/
├── mlflow_tracker.py     # MLflow experiment tracking (or JSON fallback)
├── eval_framework.py     # 9-dimension LLM output evaluator
├── ab_experiment.py      # A/B testing: model vs model, prompt vs prompt
├── scoring.py            # Exact match, rubric, agent-as-judge, golden tasks
├── vector_store.py       # Qdrant persistent memory (agent-namespaced)
├── benchmark.py          # Regression suites + capability benchmarks
├── turbo_quant.py        # TurboQuant-inspired embedding compression
└── (existing modules)
    ├── experiment_tracker.py
    ├── pipeline.py
    ├── monitor.py
    ├── data_version.py
    └── doc_enforcer.py

backend/routes/ml_eval.py  # ~35 REST endpoints under /ml/eval/
```

---

## 1. MLflow Tracker (`mlflow_tracker.py`)

**What it does:** Logs every LLM call with full metadata so you can query, compare, and reproduce runs.

**What it tracks per call:**
| Field | Example |
|---|---|
| `model` | `llama3.2`, `qwen2.5:7b` |
| `prompt` | The system + user prompt (truncated to 2KB) |
| `temperature` | `0.7` |
| `latency_ms` | `1240.5` |
| `tokens_in` / `tokens_out` | `512` / `380` |
| `cost_usd` | `0.0` (local) or actual API cost |
| `eval_score` | `0.85` |
| `pass_fail` | `true` / `false` |
| `task_type` | `summarization`, `tool_selection`, `code_assistance` |

**How to use it:**

```python
from backend.ml.mlflow_tracker import MLflowTracker

tracker = MLflowTracker()

with tracker.start_run("qwen_eval_batch", params={"dataset": "golden_v2"}) as run_id:
    tracker.log_llm_call(
        run_id,
        model="qwen2.5:7b",
        prompt="Summarize this document...",
        response="The document covers...",
        temperature=0.3,
        latency_ms=890,
        tokens_in=1200,
        tokens_out=150,
        eval_score=0.92,
        pass_fail=True,
        task_type="summarization",
    )

# Later — find the best run
best = tracker.get_best_run(metric="eval_score")
```

**Fallback:** If MLflow isn't installed, it silently writes JSON files to `backend/ml/experiments/mlflow_fallback/`. Same API, no exceptions.

---

## 2. Eval Framework (`eval_framework.py`)

**What it does:** Evaluates any LLM output across 9 dimensions — answering all the questions like "did it pick the right tool?", "did it hallucinate?", "did it stay within constraints?"

### The 9 Evaluation Dimensions

| Dimension | What It Checks | How |
|---|---|---|
| `TOOL_SELECTION` | Did it choose the right tool? | Exact match on `context.expected_tool` vs `context.actual_tool` |
| `RETRIEVAL_ACCURACY` | Did it retrieve the right docs? | Precision / Recall / F1 on `context.expected_docs` vs `context.actual_docs` |
| `ANSWER_CORRECTNESS` | Did it answer correctly? | Exact match + containment + token overlap scoring |
| `CONSTRAINT_FOLLOWING` | Did it follow the rules? | Checks max_length, required_keywords, forbidden_keywords from context |
| `HALLUCINATION` | Did it make things up? | Flags claims not in `context.known_facts` |
| `LATENCY` | How fast was it? | Pass/fail against configurable threshold (default: context or 5000ms) |
| `TOKEN_EFFICIENCY` | How many tokens did it burn? | Checks `tokens_out` against `context.token_budget` |
| `CODE_QUALITY` | Is the code good? | Placeholder (returns 1.0) — wire to linter/test runner |
| `FORMAT_COMPLIANCE` | Is the format correct? | Placeholder (returns 1.0) — wire to schema validator |

**How to use it:**

```python
from backend.ml.eval_framework import LLMEvalFramework, EvalCase, EvalDimension

evaluator = LLMEvalFramework()

case = EvalCase(
    case_id="tool_test_001",
    task_type="tool_selection",
    input_prompt="Check latest git commits",
    expected_output="git_ops",
    actual_output="git_ops",
    model="llama3.2",
    latency_ms=340,
    tokens_in=45,
    tokens_out=12,
    context={
        "expected_tool": "git_ops",
        "actual_tool": "git_ops",
    },
)

result = evaluator.evaluate(case, dimensions=[
    EvalDimension.TOOL_SELECTION,
    EvalDimension.LATENCY,
    EvalDimension.TOKEN_EFFICIENCY,
])

print(result.overall_score)  # 0.0 – 1.0
print(result.passed)         # True if ALL dimensions pass
```

**REST:** `POST /ml/eval/run` with the case payload; `GET /ml/eval/summary` for aggregated results.

---

## 3. A/B Experiment Harness (`ab_experiment.py`)

**What it does:** Structured head-to-head comparisons. Define variants, run the same tasks through each, get a winner.

### What You Can A/B Test

| Variable | Example |
|---|---|
| Model | Qwen 2.5 7B vs Llama 3.2 3B |
| System prompt | Concise-analyst vs Verbose-explainer |
| Temperature | 0.3 vs 0.7 vs 1.0 |
| Chunk size | 256 vs 512 vs 1024 tokens |
| Embedding model | all-MiniLM-L6-v2 vs nomic-embed-text |
| Tool planner | ReAct vs function-calling |

**How to use it:**

```python
from backend.ml.ab_experiment import ABExperimentHarness

harness = ABExperimentHarness()

# 1. Define the experiment
exp_id = harness.create_experiment(
    name="Qwen vs Llama — Summarization",
    variants=[
        {"name": "qwen", "model": "qwen2.5:7b", "temperature": 0.3},
        {"name": "llama", "model": "llama3.2", "temperature": 0.3},
    ],
    metric_for_winner="avg_score",
)

# 2. Run tasks and record results for each variant
harness.record_variant_case(exp_id, "qwen", {
    "score": 0.92, "latency_ms": 890, "tokens_out": 150, "passed": True,
})
harness.record_variant_case(exp_id, "llama", {
    "score": 0.85, "latency_ms": 1200, "tokens_out": 210, "passed": True,
})

# 3. Complete and get winner
result = harness.complete_experiment(exp_id)
print(result["winner"])  # "qwen"
```

**REST:** `POST /ml/eval/ab/create`, `POST /ml/eval/ab/{id}/record`, `POST /ml/eval/ab/{id}/complete`, `GET /ml/eval/ab/{id}/compare`

---

## 4. Scoring Methods (`scoring.py`)

Four pluggable scoring strategies — use whichever fits the task.

### Exact Match
Binary — it's right or it's wrong.
```python
scorer = ExactMatchScorer(case_sensitive=False)
result = scorer.score(expected="git_ops", actual="git_ops")
# result.score = 1.0, result.passed = True
```

### Rubric Scoring
Multi-criteria weighted checklist. Good for open-ended tasks.
```python
scorer = RubricScorer(criteria=[
    {"name": "has_greeting", "description": "Starts with greeting", "check_type": "contains", "check_value": "hello", "weight": 1.0},
    {"name": "under_limit", "description": "Under 500 chars", "check_type": "max_length", "check_value": 500, "weight": 2.0},
    {"name": "mentions_product", "description": "Names the product", "check_type": "regex", "check_value": r"agentop|agent.op", "weight": 1.5},
])
result = scorer.score(expected="", actual="Hello! Agentop is...")
# result.score = weighted percentage of criteria met
```

**Rubric check types:** `contains`, `not_contains`, `regex`, `min_length`, `max_length`, `keyword_count`

### Agent-as-Judge
Uses another LLM to evaluate the output — useful when human-like judgment is needed.
```python
def my_judge(prompt: str) -> str:
    return ollama_call(prompt)  # Returns JSON: {"score": 0.85, "reasoning": "..."}

scorer = AgentJudgeScorer(judge_fn=my_judge)
result = scorer.score(expected="...", actual="...", context={"task": "summarization"})
```

### Golden Task Registry
Curated reference tasks with known-correct outputs for regression testing.
```python
registry = GoldenTaskRegistry()

registry.add_task({
    "task_id": "tool_select_git",
    "task_type": "tool_selection",
    "description": "Select the right tool for git operations",
    "input_prompt": "Check latest commits",
    "expected_output": "git_ops",
    "scoring_method": "exact_match",
    "difficulty": "easy",
    "tags": ["tool_selection", "core"],
})

# Score any output against the golden reference
result = registry.score_against_golden("tool_select_git", actual_output="git_ops")
```

**REST:** `POST /ml/eval/golden/add`, `POST /ml/eval/golden/{id}/score`, `GET /ml/eval/golden`

---

## 5. Benchmark Suite (`benchmark.py`)

**What it does:** Regression testing — run the same suite after every change and catch degradations automatically.

### Built-in Suites

**Capability Suite** — tests all 7 agent skills:
| Case | Task Type | Tests |
|---|---|---|
| `draft_email` | Drafting | Professional email composition |
| `plan_sprint` | Planning | Sprint plan with tasks, estimates, deps |
| `summarize_doc` | Summarization | Architectural document summary |
| `extract_entities` | Extraction | NER from technical text |
| `classify_intent` | Classification | User intent classification |
| `select_tool` | Tool Selection | Correct tool for a given task |
| `code_fastapi_endpoint` | Code Assistance | Working FastAPI endpoint generation |

**WebGen Suite** — tests website generation:
| Case | Tests |
|---|---|
| `landing_page` | Responsive landing page with hero, features, pricing, footer |
| `dashboard_component` | React dashboard with sidebar, topbar, data table |
| `form_validation` | Multi-field form with client-side validation |
| `api_documentation` | REST API docs page with endpoints, examples, auth |

### Regression Detection

When you set a baseline, every subsequent run is compared against it:

| Check | Threshold | Example |
|---|---|---|
| Pass rate drop | > 5% | Baseline 95% → Current 88% = REGRESSION |
| Avg score drop | > 5% | 0.90 → 0.83 = REGRESSION |
| Latency increase | > 20% | 500ms → 650ms = REGRESSION |
| Per-case regression | Was passing, now failing | `classify_intent` flipped = REGRESSION |

```python
suite = BenchmarkSuite()

# Create and run
data = BenchmarkSuite.create_capability_suite()
suite.create_suite(**data)

report = suite.run_suite("capabilities", model="llama3.2", runner_fn=my_runner)
suite.set_baseline("capabilities", "llama3.2", report)

# After a change — run again
new_report = suite.run_suite("capabilities", model="llama3.2", runner_fn=my_runner)
print(new_report.regressions)
# ["Pass rate dropped: 1.00 → 0.86", "Case regressed: classify_intent"]
```

**REST:** `POST /ml/eval/bench/suite`, `POST /ml/eval/bench/defaults/capabilities`, `GET /ml/eval/bench/history/{id}`

---

## 6. Qdrant Vector Store (`vector_store.py`)

**What it does:** Gives every agent persistent semantic memory that survives restarts. Search by meaning, not just keywords.

**Why Qdrant over PGVector:**
- Purpose-built for vectors — no relational overhead
- In-memory mode for CI tests (no Docker needed in test)
- Payload filtering for agent namespace isolation
- Built-in quantization support
- Scales to millions of vectors without a full database

### Agent Memory

Each agent gets its own namespace — Soul's memories don't leak into DevOps's memories:

```python
store = VectorStore(in_memory=True)  # For dev/test
# store = VectorStore(host="localhost", port=6333)  # Production with Docker

# Store a memory
point_id = store.store_memory(
    agent_name="soul_core",
    content="User prefers concise responses under 200 words",
    embedding=[0.1, 0.3, ...],  # 384-dim from all-MiniLM-L6-v2
    memory_type="preference",
    metadata={"source": "conversation_42"},
)

# Recall relevant memories
memories = store.recall_memories(
    agent_name="soul_core",
    query_embedding=[0.12, 0.28, ...],
    limit=5,
    memory_type="preference",
)
```

### Direct Vector Operations

```python
# Bulk upsert
store.upsert(
    vectors=[[0.1, 0.2, ...], [0.3, 0.4, ...]],
    payloads=[{"text": "doc1"}, {"text": "doc2"}],
    collection="knowledge_base",
    agent_namespace="knowledge_agent",
)

# Semantic search with filtering
results = store.search(
    query_vector=[0.15, 0.25, ...],
    limit=10,
    collection="knowledge_base",
    filters={"category": "architecture"},
)
```

**REST:** `POST /ml/eval/memory/store`, `POST /ml/eval/memory/recall`

---

## 7. TurboQuant Embedding Compression (`turbo_quant.py`)

### Source & Attribution

**Paper:** [TurboQuant: Online Vector Quantization via Random Rotation](https://arxiv.org/abs/2504.19874)
**Authors:** Haotian Jiang, Hossein Bateni, Laxman Dhulipala, Rajesh Jayaram, Vahab Mirrokni (Google Research)
**Published:** April 2025

### What Is TurboQuant?

A method for compressing embedding vectors while preserving their cosine similarity. Traditional quantization (like Product Quantization / PQ) requires training on data and expensive k-means clustering. TurboQuant is **data-oblivious** — it works on any vector with zero training.

### Key Insights From the Paper

1. **Random rotation normalizes coordinate distributions.** After multiplying by a random orthogonal matrix (generated via QR decomposition of a Gaussian), each coordinate follows $\text{Beta}(1/2, (d-1)/2)$, which concentrates around 0. This makes uniform scalar quantization near-optimal.

2. **Quality–compression tradeoffs are proven, not empirical:**
   - MSE bound: $\text{MSE} \leq \frac{3\pi}{2} \cdot \frac{1}{4^b}$ for $b$ bits per coordinate
   - 4-bit = quality neutral (8x compression)
   - 3.5-bit ≈ marginal degradation
   - 2.5-bit = still usable for approximate search

3. **Near-zero indexing time.** PQ needs minutes of k-means training; TurboQuant needs one QR decomposition (done once on init).

4. **Data-oblivious.** The rotation matrix depends only on dimension and a seed — not on the data. This means you can quantize new vectors without retraining.

### How We Use It

Our implementation compresses 384-dim `float32` embeddings (from all-MiniLM-L6-v2) before they enter Qdrant:

| Setting | Compression | MSE Bound | Use Case |
|---|---|---|---|
| 4-bit (default) | ~5.3x | 0.018 | Production — quality neutral |
| 3-bit | ~6.7x | 0.074 | High-volume / memory constrained |
| 2-bit | ~8x | 0.295 | Approximate search / fast filtering |

```python
from backend.ml.turbo_quant import TurboQuantizer
import numpy as np

quant = TurboQuantizer(dim=384, bits=4, seed=42)

# Compress
embedding = np.random.randn(384).astype(np.float32)
compressed = quant.quantize(embedding)  # ~196 bytes vs 1536 bytes

# Decompress
restored = quant.dequantize(compressed)

# Verify quality
cosine_sim = np.dot(embedding, restored) / (np.linalg.norm(embedding) * np.linalg.norm(restored))
print(f"Cosine similarity: {cosine_sim:.4f}")  # Typically > 0.99 at 4-bit

# Batch operations
batch = np.random.randn(1000, 384).astype(np.float32)
compressed_batch = quant.quantize_batch(batch)
print(f"Compression ratio: {quant.compression_ratio():.1f}x")
```

### Why This Matters for Agentop

| Without TurboQuant | With TurboQuant (4-bit) |
|---|---|
| 384 dims × 4 bytes = 1,536 bytes/vector | 384 dims × 0.5 bytes + 4 = 196 bytes/vector |
| 100K vectors = 146 MB | 100K vectors = 18.7 MB |
| RAM-bound at scale | Fits comfortably in memory |

The quantizer is **not yet wired into the VectorStore pipeline** — it's available as a standalone module. To integrate, compress before `upsert()` and decompress after `search()`, or let Qdrant's built-in quantization handle it (Qdrant has native scalar/product quantization too).

---

## REST API Quick Reference

All endpoints live under `/ml/eval/`. The server must be running on port 8000.

### Evaluation
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/run` | Evaluate a single LLM output |
| GET | `/ml/eval/results` | Query past evaluation results |
| GET | `/ml/eval/summary` | Aggregated eval summary |

### A/B Experiments
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/ab/create` | Create an A/B experiment |
| POST | `/ml/eval/ab/{id}/record` | Record a variant result |
| POST | `/ml/eval/ab/{id}/complete` | Finalize and pick a winner |
| GET | `/ml/eval/ab/{id}` | Get experiment details |
| GET | `/ml/eval/ab/{id}/compare` | Side-by-side variant comparison |
| GET | `/ml/eval/ab` | List all experiments |

### Golden Tasks
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/golden/add` | Register a golden task |
| GET | `/ml/eval/golden/{id}` | Get a golden task |
| POST | `/ml/eval/golden/{id}/score` | Score output against golden |
| GET | `/ml/eval/golden` | List golden tasks (filterable) |
| DELETE | `/ml/eval/golden/{id}` | Remove a golden task |

### Benchmarks
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/bench/suite` | Create a benchmark suite |
| GET | `/ml/eval/bench/suites` | List all suites |
| GET | `/ml/eval/bench/suite/{id}` | Get suite details |
| GET | `/ml/eval/bench/history/{id}` | Run history for a suite |
| POST | `/ml/eval/bench/defaults/capabilities` | Create the built-in capability suite |
| POST | `/ml/eval/bench/defaults/webgen` | Create the built-in webgen suite |

### Memory (Qdrant)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/memory/store` | Store an agent memory |
| POST | `/ml/eval/memory/recall` | Recall memories by semantic similarity |

### MLflow
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ml/eval/mlflow/start` | Start an MLflow tracking run |
| POST | `/ml/eval/mlflow/log-call` | Log an LLM call to a run |
| GET | `/ml/eval/mlflow/runs` | Search past runs |
| GET | `/ml/eval/mlflow/best` | Get the best run by metric |

---

## Typical Workflows

### "Is Qwen or Llama better for our summarization tasks?"

1. Create golden tasks: `POST /ml/eval/golden/add` (5-10 summarization tasks with known-good outputs)
2. Create A/B experiment: `POST /ml/eval/ab/create` with Qwen and Llama variants
3. For each golden task, run both models, record results: `POST /ml/eval/ab/{id}/record`
4. Complete: `POST /ml/eval/ab/{id}/complete` → get winner + per-dimension breakdown

### "Did my prompt change break anything?"

1. Create benchmark suite (or use built-in): `POST /ml/eval/bench/defaults/capabilities`
2. Run suite with current model: `run_suite()` → set as baseline
3. Make your prompt change
4. Run suite again → automatic regression detection
5. Check `report.regressions` for any degradation

### "Give agents persistent memory"

1. On every meaningful interaction, embed the content and call `store_memory()`
2. Before generating a response, call `recall_memories()` with the query embedding
3. Inject recalled context into the system prompt
4. Each agent's memories are isolated by namespace — no cross-contamination

---

## Test Coverage

102 tests across 7 test files, all passing:

| Test File | Tests | Covers |
|---|---|---|
| `test_ml_mlflow_tracker.py` | 10 | Run lifecycle, metrics, LLM call logging, search, fallback |
| `test_ml_eval_framework.py` | 21 | All 9 eval dimensions, edge cases, aggregation |
| `test_ml_ab_experiment.py` | 11 | Create, record, complete, compare, winner selection |
| `test_ml_scoring.py` | 26 | Exact match, rubric (all check types), agent judge, golden tasks |
| `test_ml_vector_store.py` | 11 | Upsert, search, get, delete, count, filters, store/recall memory |
| `test_ml_benchmark.py` | 12 | Create, run, baseline, regression detection, history, factories |
| `test_ml_turbo_quant.py` | 11 | Quantize/dequantize, batch, compression ratio, distortion, bit widths |

Full project: **783 tests, 61% coverage**.
