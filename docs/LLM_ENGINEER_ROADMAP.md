# LLM Engineer Roadmap — Lex Santiago

> From ML hobbyist → production LLM engineer
> Based on your current stack: Python, RTX 4070, Ollama, Agentop
> Last updated: 2026-03-30

---

## Where You Already Are

You're NOT starting from zero. You've already:
- Collected 121+ domain-specific training pairs
- Built 8 data collection strategies (git, specs, AST, synthesis)
- Wired up Ollama (local inference)
- Understood ShareGPT format (the industry standard for SFT data)
- Targeted Qwen2.5-7B with QLoRA (the right architecture for your GPU)

**You are at Phase 3 entry-point.** Most people spend months getting here.

---

## Phase 0 — Python ML Ecosystem (1–2 weeks)

Before PyTorch makes sense, know the tools around it:

```bash
pip install torch transformers datasets accelerate peft bitsandbytes trl unsloth
```

| Library | What it does | Why it matters |
|---|---|---|
| `torch` | Core tensor math + autograd | Everything runs on this |
| `transformers` | Pre-built model architectures | Load any model in 3 lines |
| `datasets` | Efficient data loading + HuggingFace Hub | Industry standard format |
| `peft` | LoRA / QLoRA adapters | Fine-tune without full GPU |
| `trl` | SFT, DPO, PPO trainers | The actual training loop |
| `unsloth` | Optimized QLoRA (2x faster, less VRAM) | Perfect for RTX 4070 |
| `bitsandbytes` | 4-bit/8-bit quantization | Makes 7B models fit in 12GB |

**First exercise**: Load Qwen2.5-7B and generate a response locally:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model_id = "Qwen/Qwen2.5-7B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16, device_map="auto")

prompt = "Explain how LangGraph routing works in one paragraph."
inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
outputs = model.generate(**inputs, max_new_tokens=200)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))
```

---

## Phase 1 — PyTorch Fundamentals (2–4 weeks)

Don't start with LLMs. Start with the building blocks.

### Core Concepts (in order)

**Week 1: Tensors & Autograd**
```python
import torch

# Tensors = multi-dimensional arrays that live on GPU
x = torch.tensor([[1.0, 2.0], [3.0, 4.0]], requires_grad=True)
y = (x ** 2).sum()
y.backward()          # compute gradients
print(x.grad)         # ∂y/∂x = 2x
```

**Week 2: nn.Module — building neural nets**
```python
import torch.nn as nn

class MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(128, 256)
        self.fc2 = nn.Linear(256, 10)
        self.relu = nn.ReLU()

    def forward(self, x):
        return self.fc2(self.relu(self.fc1(x)))

model = MLP().to("cuda")
x = torch.randn(32, 128).to("cuda")  # batch of 32
out = model(x)   # shape: (32, 10)
```

**Week 3: Training loop**
```python
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
loss_fn = nn.CrossEntropyLoss()

for epoch in range(10):
    optimizer.zero_grad()           # clear old gradients
    predictions = model(x_batch)    # forward pass
    loss = loss_fn(predictions, y_batch)
    loss.backward()                 # compute gradients
    optimizer.step()                # update weights
    print(f"epoch {epoch} loss: {loss.item():.4f}")
```

**Week 4: DataLoader**
```python
from torch.utils.data import Dataset, DataLoader

class MyDataset(Dataset):
    def __init__(self, data): self.data = data
    def __len__(self): return len(self.data)
    def __getitem__(self, idx): return self.data[idx]

loader = DataLoader(MyDataset(all_pairs), batch_size=4, shuffle=True)
for batch in loader:
    # process batch
    pass
```

### Key Resources for Phase 1

| Resource | Link | Time |
|---|---|---|
| Karpathy "Neural Networks: Zero to Hero" | youtube.com/@AndrejKarpathy | 10 hrs |
| PyTorch 60-min blitz | pytorch.org/tutorials | 2 hrs |
| fast.ai Lesson 1-3 | fast.ai/courses | 6 hrs |

---

## Phase 2 — Transformers Architecture (2–4 weeks)

Understand WHY LLMs work, not just how to call them.

### The Attention Mechanism (most important concept)

```python
import torch
import torch.nn.functional as F

def attention(Q, K, V):
    """
    Q = what I'm looking for
    K = what each token advertises about itself
    V = what each token actually contains
    """
    d_k = Q.size(-1)
    scores = torch.matmul(Q, K.transpose(-2, -1)) / (d_k ** 0.5)
    weights = F.softmax(scores, dim=-1)
    return torch.matmul(weights, V)
```

In plain English: every token asks "which other tokens do I need to pay attention to?" Attention is the core innovation of the Transformers paper.

### Key Concepts to Study

1. **Tokenization** — text → integers → embeddings
2. **Positional encoding** — how the model knows token order
3. **Multi-head attention** — run attention in parallel with different "perspectives"
4. **Feed-forward layers** — the "memory" between attention layers
5. **Layer normalization** — stabilizes training
6. **Causal masking** — why models only see past tokens, not future

### Build It From Scratch (best way to learn)

Karpathy's "makemore" and "nanoGPT" repos are the gold standard:
- Build bigram model → add MLP → add attention → add full transformer → you now understand GPT
- https://github.com/karpathy/nanoGPT

### Key Papers to Read (in order)

1. "Attention Is All You Need" (2017) — the original transformer
2. "GPT-3: Language Models are Few-Shot Learners" (2020) — scale laws
3. "LoRA: Low-Rank Adaptation of LLMs" (2021) — how you'll fine-tune
4. "QLoRA: Efficient Finetuning of Quantized LLMs" (2023) — how you'll actually fine-tune on RTX 4070
5. "Direct Preference Optimization" (2023) — how to align behavior

---

## Phase 3 — Supervised Fine-Tuning (SFT) ← YOU ARE HERE

This is where your Agentop dataset comes in. SFT teaches the model new patterns by continuing training on domain-specific examples.

### Unsloth QLoRA Fine-Tune (full script)

```python
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

# 1. Load base model with 4-bit quantization
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "Qwen/Qwen2.5-7B-Instruct",
    max_seq_length = 2048,
    dtype = None,         # auto-detect
    load_in_4bit = True,  # QLoRA — fits in 12GB
)

# 2. Attach LoRA adapters (only trains 1-3% of weights)
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,                          # rank — higher = more capacity, more VRAM
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
)

# 3. Load your training data
dataset = load_dataset("json", data_files="data/training/combined.jsonl", split="train")

# 4. Format to Qwen chat template
def format_pair(example):
    conversations = example["conversations"]
    return tokenizer.apply_chat_template(conversations, tokenize=False)

# 5. Train
trainer = SFTTrainer(
    model = model,
    train_dataset = dataset,
    args = TrainingArguments(
        output_dir = "models/lex_7b",
        num_train_epochs = 3,
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,  # effective batch = 8
        learning_rate = 2e-4,
        warmup_steps = 10,
        save_strategy = "epoch",
        fp16 = True,
        logging_steps = 10,
    ),
)
trainer.train()

# 6. Save and convert to GGUF for Ollama
model.save_pretrained_gguf("models/lex_7b_gguf", tokenizer, quantization_method="q4_k_m")
```

### Then load in Ollama:
```bash
# Create Modelfile
cat > Modelfile << 'EOF'
FROM ./models/lex_7b_gguf/model.gguf
SYSTEM "You are Lex's AI assistant, specialized in Agentop multi-agent systems, 3D web (Three.js, GSAP), and the IBDS dashboard platform."
EOF

ollama create lex_7b -f Modelfile
ollama run lex_7b "How do I add a new agent to Agentop?"
```

---

## Phase 4 — Alignment (DPO) ← NEXT BIG STEP

SFT teaches the model WHAT you want. DPO teaches it to **prefer** good responses over bad ones.

### What DPO data looks like:

```json
{
  "prompt": "How do I route a new intent in the LangGraph orchestrator?",
  "chosen": "To add routing in LangGraph: 1) Define a new node function... [detailed answer with code]",
  "rejected": "You can modify the orchestrator to handle new intents by editing the routing logic."
}
```

The model trains to maximize likelihood of `chosen` relative to `rejected`.

### Generate DPO pairs:

```bash
# Strategy 9 — DPO preference pairs (newly added script)
python scripts/build_dpo_pairs.py --limit 50

# Then train with DPO:
python scripts/train_dpo.py
```

See `scripts/build_dpo_pairs.py` for full implementation.

### DPO Training (with TRL):

```python
from trl import DPOTrainer
from datasets import load_dataset

dpo_dataset = load_dataset("json", data_files="data/training/dpo_pairs.jsonl", split="train")

dpo_trainer = DPOTrainer(
    model = model,          # already SFT-fine-tuned model
    ref_model = None,       # None = use implicit reference
    beta = 0.1,             # how strongly to enforce preferences
    train_dataset = dpo_dataset,
    tokenizer = tokenizer,
    args = training_args,
)
dpo_trainer.train()
```

---

## Phase 5 — Evaluation & Iteration

The feedback loop that makes a real engineer.

### Track everything:
```bash
# Before fine-tuning
python scripts/eval_model.py --model llama3.2

# After SFT
python scripts/eval_model.py --model lex_7b

# Compare
python scripts/eval_model.py --compare

# Dataset growth
python scripts/dataset_stats.py --all
```

### Iteration loop:
1. Run eval → find where model scores low
2. Generate more training data targeting those weak spots
3. Re-fine-tune (LoRA makes this cheap — 10-30min on RTX 4070)
4. Run eval again → measure delta
5. Repeat

---

## Phase 6 — Advanced Topics (ongoing)

Once you can train and evaluate a fine-tuned model, these are the next frontiers:

| Topic | What it is | Tools |
|---|---|---|
| Flash Attention 2 | 2-4x faster attention | `flash-attn` pip package |
| Gradient checkpointing | Trade compute for memory savings | built into Unsloth |
| GRPO (Group Relative Policy Opt.) | DeepSeek-R1 style reasoning | TRL GRPO trainer |
| Continued pre-training | Train on raw docs before SFT | same loop, different data format |
| Multi-turn conversations | Complex agent-style training | filter data for multi-turn |
| Merging LoRA adapters | Combine multiple fine-tunes | `peft` merge utilities |
| vLLM inference | 10-20x faster serving than Ollama | `vllm` pip package |
| AWQ / GPTQ quantization | Smaller models, fast inference | `autoawq`, `auto-gptq` |

---

## Learning Path Summary

```
Week 1-2:   PyTorch tensors + autograd + nn.Module
Week 3-4:   Training loops + DataLoader + optimizer
Week 5-6:   Build nanoGPT from scratch (Karpathy)
Week 7-8:   HuggingFace Transformers API + fine-tune basics
Week 9-10:  YOUR FIRST FINE-TUNE — Agentop data on Qwen2.5-7B
Week 11-12: Eval, iterate, DPO alignment
Month 4+:   Advanced (GRPO, continued pre-training, deployment)
```

---

## Best Resources (prioritized)

### Videos (watch first)
1. **Andrej Karpathy — "Let's build GPT from scratch"** — 2 hours, best explanation of transformers ever made
2. **Andrej Karpathy — "Neural Networks: Zero to Hero"** — full playlist, builds intuition for everything
3. **fast.ai Practical Deep Learning** — lesson 1-5 for engineering mindset

### Books
1. **"Build a Large Language Model From Scratch"** by Sebastian Raschka — best book on the topic, 2024
2. **"Designing Machine Learning Systems"** by Chip Huyen — for production ML

### Courses
1. **HuggingFace NLP Course** (free) — nlp-course.huggingface.co
2. **DeepLearning.AI "Fine-tuning LLMs"** (short, practical)

### GitHub repos to study
1. `karpathy/nanoGPT` — cleanest transformer implementation
2. `unsloth/unsloth` — how optimized QLoRA works
3. `huggingface/trl` — SFT/DPO/PPO trainers
4. `microsoft/DeepSpeed` — distributed training

---

## What You're Building (the big picture)

```
llama3.2 (generic) 
    → + your 500 domain pairs (SFT)
    → lex_7b (knows Agentop, IBDS, 3D web)
        → + DPO preference pairs (alignment)
        → lex_7b_aligned (gives good answers, avoids bad ones)
            → + deployment via Ollama/vLLM
            → production agent in VS Code + Agentop
```

You're not just using LLMs. You're manufacturing them for your specific domain. That's the difference between an LLM user and an LLM engineer.

---

## Quick Commands

```bash
# Check dataset readiness
python scripts/dataset_stats.py --all

# Establish baseline score (before fine-tune)
python scripts/eval_model.py --model llama3.2

# Generate DPO preference pairs (Strategy 9)
python scripts/build_dpo_pairs.py --limit 50

# Grow dataset to 500
./scripts/run_ml_training.sh --ollama

# Fine-tune when ready (500+ pairs)
python scripts/train_sft.py

# Evaluate after fine-tune
python scripts/eval_model.py --model lex_7b
python scripts/eval_model.py --compare
```
