# ML Training Plan — Agentop Fine-Tuning Roadmap

> **Trigger phrase:** Say "work on machine learning" to pick up from here.
> Full learning roadmap: see `docs/LLM_ENGINEER_ROADMAP.md`
> Last updated: 2026-03-30

---

## Hardware

| Spec | Value |
|---|---|
| GPU | RTX 4070 (12GB VRAM) |
| Target model | Qwen2.5-7B-Instruct (4-bit QLoRA ~5-6GB) |
| Fine-tune stack | Unsloth + TRL + HuggingFace Transformers |
| Training format | ShareGPT JSONL |
| Output | `models/lex_7b/` → export GGUF → Ollama as `lex_7b` |

---

## Current Dataset Status

```bash
# Check pair counts
wc -l data/training/*.jsonl 2>/dev/null || echo "No data yet — run scripts below"

# Combine all outputs
cat data/training/*.jsonl > data/training/combined.jsonl && wc -l data/training/combined.jsonl
```

| File | Description | Target Pairs |
|---|---|---|
| `3d-web_*.jsonl` | Three.js, GSAP, WebGL seeds | 20 |
| `git_pairs_*.jsonl` | Commit diff → before/after pairs | 50–100 |
| `pytest_pairs_*.jsonl` | Real test failures → diagnosis+fix | 20–50 |
| `spec_pairs_*.jsonl` | IBDS component specs → implementations | 34 |
| `review_pairs_*.jsonl` | Code smell → refactored version | 30–50 |
| `architecture_pairs_*.jsonl` | Agentop system design Q&A | 30 |
| `agentop_*.jsonl` | Codebase synthesis (via Ollama) | 100–200 |
| **combined.jsonl** | **Total target** | **500+** |

---

## Strategy 1 — Git Diff Pairs (Before/After)

Extracts every commit in the repo's history. Each commit becomes a training pair:
`"Here's this code diff → what was wrong and what was the fix?"`

```bash
# Raw mode — instant, no LLM needed
python scripts/build_git_pairs.py --raw --limit 50

# With Ollama (richer explanations)  
python scripts/build_git_pairs.py --ollama --limit 50
```

**Output:** `data/training/git_pairs_<timestamp>.jsonl`

---

## Strategy 2 — pytest Failure → Error+Fix Pairs

Runs the full test suite, captures failures with tracebacks, generates diagnosis pairs.

```bash
# Extract raw failures (no LLM)
python scripts/build_pytest_pairs.py --raw

# With Ollama — Ollama explains each error and proposes a fix  
python scripts/build_pytest_pairs.py --ollama
```

**Output:** `data/training/pytest_pairs_<timestamp>.jsonl`

---

## Strategy 3 — IBDS Spec → Component Implementation Pairs

34 detailed component specs in `clients/ibds/specs/` — each becomes a pair:
`"Implement <ComponentName> from this spec"` → TypeScript/Mantine code

```bash
# Raw mode — creates placeholder pairs + spec content as context
python scripts/build_spec_pairs.py --raw

# With Ollama — Ollama writes the full TypeScript component
python scripts/build_spec_pairs.py --ollama
```

**Output:** `data/training/spec_pairs_<timestamp>.jsonl`

---

## Strategy 4 — Code Review Pairs (Bad → Good)

Scans backend Python files, flags common issues (long functions, missing types,
unused imports, broad try/except), produces before/after pairs.

```bash
python scripts/build_review_pairs.py --raw
python scripts/build_review_pairs.py --ollama
```

**Output:** `data/training/review_pairs_<timestamp>.jsonl`

---

## Strategy 5 — Architecture Explanation Pairs

Hardcoded + generated Q&A about Agentop's design philosophy, agent registry,
tool governance, LangGraph routing, drift guard invariants.

```bash
python scripts/build_architecture_pairs.py
```

**Output:** `data/training/architecture_pairs_<timestamp>.jsonl`

---

## Strategy 6 — Multi-Turn Debugging Conversations

Uses pytest failures + git blame to simulate "I have this bug, walk me through fixing it"
multi-turn conversations. These are highest-value for coding assistant fine-tuning.

```bash
# Included in build_pytest_pairs.py --multi-turn
python scripts/build_pytest_pairs.py --multi-turn --ollama
```

---

## Strategy 7 — Codebase Synthesis via Ollama

The main synthesizer, now with Ollama backend (no API key needed).

```bash
# Scan entire backend/ + docs/ with Ollama
python scripts/synthesize_training_data.py --domain agentop --backend ollama

# Scan IBDS client
python scripts/synthesize_training_data.py --domain ibds --backend ollama

# 3D web seeds (20 hardcoded, no LLM)
python scripts/synthesize_training_data.py --domain 3d-web --seeds-only
```

---

## Strategy 8 — 3D Web Pairs (50+ Seeds)

20 hardcoded premium pairs (Three.js, GSAP, WebGL, CSS 3D) — grows over time.

```bash
python scripts/synthesize_training_data.py --domain 3d-web --seeds-only
```

---

## Strategy 9 — DPO Preference Pairs (Alignment)

Takes your SFT pairs (chosen) and uses Ollama to generate a degraded "rejected" version.
DPO trains the model to prefer good answers over vague/incomplete ones.
This is Phase 2 of training — run AFTER you've done SFT fine-tuning.

```bash
# Rule-based rejected (no LLM, instant)
python scripts/build_dpo_pairs.py --raw --limit 50

# Ollama-generated rejected (richer contrast)
python scripts/build_dpo_pairs.py --limit 50

# Quality check
python scripts/build_dpo_pairs.py --check
```

**Output format:** `data/dpo/dpo_pairs_<timestamp>.jsonl`
```json
{"prompt": "...", "chosen": "<detailed answer>", "rejected": "<vague answer>"}
```

Full DPO learning path: see `docs/LLM_ENGINEER_ROADMAP.md` → Phase 4

---

## Running Everything (Full Pipeline)

```bash
# Activate venv first
source .venv/bin/activate

# Run all collection strategies
./scripts/run_ml_training.sh

# Or run individually
python scripts/build_git_pairs.py --raw --limit 100
python scripts/build_spec_pairs.py --raw
python scripts/build_architecture_pairs.py
python scripts/synthesize_training_data.py --domain 3d-web --seeds-only
python scripts/synthesize_training_data.py --domain agentop --backend ollama --budget 50

# Combine
cat data/training/*.jsonl > data/training/combined.jsonl
echo "Total pairs: $(wc -l < data/training/combined.jsonl)"
```

---

## Fine-Tuning Pipeline (After 500+ Pairs Collected)

### Step 1 — Install Unsloth

```bash
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps trl peft accelerate bitsandbytes
```

### Step 2 — Verify dataset

```bash
python -c "
import json
with open('data/training/combined.jsonl') as f:
    lines = f.readlines()
print(f'Total: {len(lines)} pairs')
# Check format
sample = json.loads(lines[0])
print('Format OK:', 'conversations' in sample)
print('Sample Q:', sample['conversations'][0]['value'][:80])
"
```

### Step 3 — Fine-tune (run in Python or Jupyter)

```python
# scripts/finetune_lex7b.py
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

MODEL = "Qwen/Qwen2.5-7B-Instruct"
OUTPUT = "models/lex_7b"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL,
    max_seq_length=4096,
    load_in_4bit=True,       # 4-bit → fits in 12GB VRAM
    dtype=None,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,                    # LoRA rank — 16 is a good default
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=3407,
)

dataset = load_dataset("json", data_files="data/training/combined.jsonl", split="train")

def format_sharegpt(example):
    convs = example["conversations"]
    text = ""
    for turn in convs:
        role = "user" if turn["from"] == "human" else "assistant"
        text += f"<|{role}|>\n{turn['value']}\n"
    return {"text": text + "<|end|>"}

dataset = dataset.map(format_sharegpt)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=4096,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        output_dir=OUTPUT,
        save_strategy="epoch",
    ),
)

trainer.train()
model.save_pretrained(OUTPUT)
tokenizer.save_pretrained(OUTPUT)
print(f"✓ Saved to {OUTPUT}")
```

### Step 4 — Export to GGUF + load in Ollama

```bash
# Export from fine-tuned model
cd models/lex_7b
python -c "
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained('.')
model.save_pretrained_gguf('.', tokenizer, quantization_method='q4_k_m')
"

# Create Ollama model
ollama create lex_7b -f - <<EOF
FROM ./lex_7b-unsloth.Q4_K_M.gguf
SYSTEM "You are Lex, a NJIT CS student and AI agency founder. You build production multi-agent systems with FastAPI, LangGraph, and Next.js. You write clean, opinionated code and deliver results fast."
EOF

# Test it
ollama run lex_7b "How do I add a new agent to Agentop?"
```

---

## Dataset Quality Checks

```bash
python -c "
import json
from pathlib import Path

files = list(Path('data/training').glob('*.jsonl'))
total = 0
issues = 0

for f in files:
    if f.name == 'combined.jsonl':
        continue
    with open(f) as fh:
        for i, line in enumerate(fh):
            total += 1
            try:
                rec = json.loads(line)
                convs = rec.get('conversations', [])
                if len(convs) < 2:
                    issues += 1
                # Check minimum answer length (200 chars = quality floor)
                answer = convs[1]['value'] if len(convs) > 1 else ''
                if len(answer) < 200:
                    issues += 1
            except Exception:
                issues += 1

print(f'Total pairs: {total}')
print(f'Quality issues: {issues} ({100*issues//max(total,1)}%)')
print(f'Status: {\"✓ READY\" if total >= 500 and issues/total < 0.1 else \"⏳ COLLECTING\"}')
"
```

---

## Progress Tracker

| Strategy | Status | Script | Pairs |
|---|---|---|---|
| 3D Web Seeds | ✅ Done (8→20) | `synthesize_training_data.py --seeds-only` | 20 |
| Git Diff Pairs | ⏳ Ready | `build_git_pairs.py --raw` | 0 |
| Pytest Pairs | ⏳ Ready | `build_pytest_pairs.py --raw` | 0 |
| Spec Pairs | ⏳ Ready | `build_spec_pairs.py --raw` | 0 |
| Review Pairs | ⏳ Ready | `build_review_pairs.py --raw` | 0 |
| Architecture Pairs | ⏳ Ready | `build_architecture_pairs.py` | 0 |
| Ollama Synthesis | ⏳ Needs Ollama | `synthesize_training_data.py --backend ollama` | 0 |
| **Total** | | `run_ml_training.sh` | **20/500** |

---

## Notes

- **No API key needed** — all scripts work with `--raw` mode or `--backend ollama`
- **Ollama model** defaults to `llama3.2` (set `OLLAMA_MODEL` env var to override)
- **Data quality floor**: answers must be >200 chars; use the quality check script above
- **Combine before fine-tuning**: always `cat data/training/*.jsonl > data/training/combined.jsonl`
- The `--raw` extracts data as-is (no LLM synthesis). It's valid training data — the Q always contains context and the A contains the reference.
