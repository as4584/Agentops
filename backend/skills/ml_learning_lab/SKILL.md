# ML Learning Lab — Self-Improving Agent Intelligence

> Train. Evaluate. Benchmark. Repeat.

## What This Is

The ML Learning Lab is Agentop's self-improvement engine. It connects every piece
of ML infrastructure into a single workflow:

```
Collect Decisions → Generate Training Data → Fine-tune lex-v2
         ↓                                        ↓
   Evaluate Quality  ←  Run Benchmarks  ←  Deploy Model
         ↓
   A/B Test vs Baseline → Ship or Rollback
```

## Infrastructure Map

| Component | Module | What It Does |
|-----------|--------|-------------|
| **Experiment Tracker** | `backend/ml/experiment_tracker.py` | Log runs, hyperparams, metrics. JSON-backed (MLflow optional) |
| **Eval Framework** | `backend/ml/eval_framework.py` | 9-dimension scoring: accuracy, relevance, safety, latency, tool use, boundary respect, confidence calibration, reasoning quality, format compliance |
| **A/B Harness** | `backend/ml/ab_experiment.py` | Compare model vs model or prompt vs prompt with statistical significance |
| **Scoring** | `backend/ml/scoring.py` | ExactMatch, Rubric, AgentAsJudge + GoldenTaskRegistry for canonical eval sets |
| **Benchmark Suite** | `backend/ml/benchmark.py` | Regression tests + capability benchmarks with pass/fail thresholds |
| **Data Versioner** | `backend/ml/data_version.py` | Snapshot and version training datasets |
| **ML Monitor** | `backend/ml/monitor.py` | Track eval score trends, detect degradation, alert on regressions |
| **Training Generator** | `backend/ml/training_generator.py` | Extract routing examples, trajectories, DPO pairs from live sessions |
| **Decision Collector** | `backend/ml/decision_collector.py` | Hook into orchestrator to log every routing decision |
| **TurboQuant** | `backend/ml/turbo_quant.py` | 4-bit quantization for embeddings (8x compression, Rust-backed) |
| **Pipeline** | `backend/ml/pipeline.py` | Orchestrate multi-step training runs with checkpointing |
| **Doc Enforcer** | `backend/ml/doc_enforcer.py` | Ensure every ML change is documented before merge |

## API Endpoints (54 total)

### Experiment Management (`/ml/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ml/runs/start` | POST | Start experiment run |
| `/ml/runs/{id}/metric` | POST | Log metric to run |
| `/ml/runs/{id}/end` | POST | End run with status |
| `/ml/runs` | GET | List all runs |
| `/ml/runs/{id}` | GET | Get run details |
| `/ml/monitor/snapshot` | GET | Current health snapshot |
| `/ml/monitor/leaderboard` | GET | Model leaderboard |
| `/ml/versions` | GET | List dataset versions |
| `/ml/docs/check` | POST | Check doc compliance |

### Evaluation (`/ml/eval/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ml/eval/run` | POST | Run eval suite |
| `/ml/eval/golden-tasks` | GET/POST | Manage golden test set |
| `/ml/eval/ab/start` | POST | Start A/B experiment |
| `/ml/eval/ab/{id}/result` | GET | Get A/B results |
| `/ml/eval/benchmark/run` | POST | Run benchmark suite |
| `/ml/eval/benchmark/report` | GET | Latest benchmark report |

### Training Data (`/api/ml/training/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ml/training/files` | GET | List training JSONL files |

## Guided Workflows

### Workflow 1: Train lex-v2 on New Data

```bash
# 1. Generate routing examples from recent sessions
python scripts/generate_training_data.py --source data/training/ --output data/training/new_pairs.jsonl

# 2. Version the dataset
curl -X POST localhost:8000/ml/versions -d '{"name": "routing_v3", "path": "data/training/"}'

# 3. Fine-tune lex-v2
python scripts/finetune_lex.py --data data/training/new_pairs.jsonl --epochs 3

# 4. Evaluate against golden test set
curl -X POST localhost:8000/ml/eval/run -d '{"model": "lex-v2-new", "golden_set": "routing_canonical"}'

# 5. A/B test vs current production
curl -X POST localhost:8000/ml/eval/ab/start -d '{"control": "lex-v2", "treatment": "lex-v2-new", "sample_size": 200}'

# 6. Check results
curl localhost:8000/ml/eval/ab/{exp_id}/result
```

### Workflow 2: Build Golden Eval Set

```bash
# Register canonical test cases (known-correct routing decisions)
curl -X POST localhost:8000/ml/eval/golden-tasks -d '{
  "task_id": "boundary_knowledge_soul_01",
  "input": "what is our purpose as a system",
  "expected_agent": "soul_core",
  "expected_tools": [],
  "difficulty": "hard",
  "boundary": "knowledge_agent<>soul_core"
}'
```

### Workflow 3: Regression Benchmarks

```bash
# Run the full benchmark suite
curl -X POST localhost:8000/ml/eval/benchmark/run -d '{"suite": "routing_regression"}'

# Check for failures
curl localhost:8000/ml/eval/benchmark/report
```

## Training Data Pipeline

### Data Generation Scripts

| Script | Output | Pairs |
|--------|--------|-------|
| `scripts/build_git_pairs.py` | Commit diffs → explanations | 50-100 |
| `scripts/build_pytest_pairs.py` | Test failures → diagnoses | 20-50 |
| `scripts/build_spec_pairs.py` | Component specs → code | 34 |
| `scripts/build_review_pairs.py` | Bad code → good code | 30-50 |
| `scripts/finetune_lex.py` | Fine-tune lex-v2 on routing | — |
| `scripts/eval_lex_router.py` | Evaluate router accuracy | — |
| `scripts/synthesize_training_data.py` | Synthetic routing examples | Configurable |

### Live Data Collection

The `DecisionCollector` hooks into the orchestrator and logs every routing decision
automatically. Every Opus (Claude) session generates:
- Routing examples (`data/training/opus_session_routing_*.jsonl`)
- Trajectory examples (`data/training/opus_session_trajectories_*.jsonl`)
- DPO preference pairs (`data/dpo/opus_session_pairs_*.jsonl`)

Current dataset: **85+ JSONL files, 812+ routing pairs** (as of 2026-04-04).

## Current Model Performance

| Model | Task | Accuracy | Latency | Status |
|-------|------|----------|---------|--------|
| lex-v2 (3B) | Routing | 94.9% | ~800ms | Production |
| lex-baseline | Routing | 45% | ~300ms | Deprecated |
| llama3.2 (3B) | General | — | ~1.2s | Production |
| qwen2.5-coder (7B) | Code | — | ~2.0s | Production |

## 9-Dimension Eval Framework

Every agent response is scored across:

1. **Accuracy** — Is the answer factually correct?
2. **Relevance** — Does it address the actual question?
3. **Safety** — Does it avoid harmful or dangerous outputs?
4. **Latency** — Is the response time acceptable?
5. **Tool Use** — Were the right tools called with correct arguments?
6. **Boundary Respect** — Did the agent stay in its lane?
7. **Confidence Calibration** — Does stated confidence match actual accuracy?
8. **Reasoning Quality** — Is the chain of thought sound?
9. **Format Compliance** — Does output match expected schema?

## What's Next

- [ ] Auto-seed golden test set from `data/training/` high-confidence examples
- [ ] Dashboard for eval score trends (Next.js page)
- [ ] Automated nightly regression with alerting
- [ ] Cost-per-model tracking ($token analytics)
- [ ] Backtesting: replay past sessions with new models
- [ ] lex-v3 training with boundary-specific hard negatives
