#!/usr/bin/env python3
"""
scripts/finetune_lex.py
───────────────────────
Fine-tune Lex — Damian's personal OpenClaw router LLM.

Training pipeline:
  1. Merge all ShareGPT JSONL sources (combined.jsonl, router, tool, personal pairs)
  2. Validate + deduplicate conversations
  3. Convert to Unsloth-compatible format (ChatML template)
  4. Run QLoRA fine-tuning (4-bit, targets RTX 4070 / 12 GB VRAM)
  5. Merge LoRA adapters → full model
  6. Export to GGUF for Ollama import
  7. Log everything to ExperimentTracker

Usage:
  # Full pipeline (requires GPU + unsloth)
  python scripts/finetune_lex.py

  # Data prep only (no GPU needed)
  python scripts/finetune_lex.py --prep-only

  # Resume from checkpoint
  python scripts/finetune_lex.py --resume /path/to/checkpoint

  # Custom base model
  python scripts/finetune_lex.py --base-model unsloth/Qwen2.5-7B-Instruct-bnb-4bit

  # DPO alignment pass (after SFT)
  python scripts/finetune_lex.py --dpo --sft-model ./output/lex-sft

Environment:
  OLLAMA_MODEL          Base model name for Ollama import (default: lex)
  LEX_BASE_MODEL        HuggingFace base model (default: unsloth/Qwen2.5-7B-Instruct-bnb-4bit)
  LEX_EPOCHS            Training epochs (default: 3)
  LEX_LR                Learning rate (default: 2e-4)
  LEX_BATCH_SIZE        Per-device batch size (default: 2)
  LEX_GRAD_ACCUM        Gradient accumulation steps (default: 4)
  LEX_MAX_SEQ_LEN       Maximum sequence length (default: 4096)
  LEX_LORA_R            LoRA rank (default: 64)
  LEX_LORA_ALPHA         LoRA alpha (default: 16)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "training"
DPO_DIR = ROOT / "data" / "dpo"
OUTPUT_DIR = ROOT / "output" / "lex-finetune"
MERGED_DATASET = OUTPUT_DIR / "merged_train.jsonl"
EVAL_SPLIT = OUTPUT_DIR / "eval_split.jsonl"
GGUF_DIR = OUTPUT_DIR / "gguf"


# ── Hyperparameters (env-overridable) ─────────────────────────────────────
class HParams:
    base_model: str = os.getenv("LEX_BASE_MODEL", "unsloth/Qwen2.5-7B-Instruct-bnb-4bit")
    epochs: int = int(os.getenv("LEX_EPOCHS", "3"))
    lr: float = float(os.getenv("LEX_LR", "2e-4"))
    batch_size: int = int(os.getenv("LEX_BATCH_SIZE", "2"))
    grad_accum: int = int(os.getenv("LEX_GRAD_ACCUM", "4"))
    max_seq_len: int = int(os.getenv("LEX_MAX_SEQ_LEN", "4096"))
    lora_r: int = int(os.getenv("LEX_LORA_R", "64"))
    lora_alpha: int = int(os.getenv("LEX_LORA_ALPHA", "16"))
    lora_dropout: float = 0.0
    warmup_ratio: float = 0.03
    weight_decay: float = 0.01
    eval_split: float = 0.05  # 5% held out for eval
    seed: int = 42
    ollama_model_name: str = os.getenv("OLLAMA_MODEL", "lex")
    quant_method: str = "q4_k_m"  # GGUF quantization level

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(type(self)).items() if not k.startswith("_") and not callable(v)}


HP = HParams()


# ══════════════════════════════════════════════════════════════════════════
# Stage 1: Data Preparation
# ══════════════════════════════════════════════════════════════════════════


def load_sharegpt_file(path: Path) -> list[dict]:
    """Load a JSONL file of ShareGPT conversations."""
    records = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # ShareGPT format has "conversations" key
                if "conversations" in obj:
                    records.append(obj)
                # DPO format has "prompt", "chosen", "rejected"
                elif "prompt" in obj and "chosen" in obj:
                    records.append(obj)
                else:
                    print(f"  [WARN] {path.name}:{i} — unknown format, skipping")
            except json.JSONDecodeError:
                print(f"  [WARN] {path.name}:{i} — invalid JSON, skipping")
    return records


def conversation_hash(conv: dict) -> str:
    """Hash a conversation for deduplication."""
    if "conversations" in conv:
        text = json.dumps(conv["conversations"], sort_keys=True)
    elif "prompt" in conv:
        text = conv["prompt"]
    else:
        text = json.dumps(conv, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def merge_and_deduplicate() -> tuple[list[dict], list[dict]]:
    """Merge all training JSONL files, deduplicate, split into train/eval."""
    print("\n═══ Stage 1: Data Preparation ═══")

    sft_records: list[dict] = []
    dpo_records: list[dict] = []

    # Load SFT data (ShareGPT format)
    if DATA_DIR.exists():
        for jsonl in sorted(DATA_DIR.glob("*.jsonl")):
            recs = load_sharegpt_file(jsonl)
            sft_count = sum(1 for r in recs if "conversations" in r)
            dpo_count = sum(1 for r in recs if "prompt" in r and "chosen" in r)
            sft_records.extend(r for r in recs if "conversations" in r)
            dpo_records.extend(r for r in recs if "prompt" in r and "chosen" in r)
            print(f"  Loaded {jsonl.name}: {sft_count} SFT + {dpo_count} DPO")

    # Load DPO data
    if DPO_DIR.exists():
        for jsonl in sorted(DPO_DIR.glob("*.jsonl")):
            recs = load_sharegpt_file(jsonl)
            dpo_records.extend(r for r in recs if "prompt" in r and "chosen" in r)
            print(f"  Loaded {jsonl.name}: {len(recs)} DPO pairs")

    # Deduplicate SFT
    seen: set[str] = set()
    unique_sft: list[dict] = []
    for rec in sft_records:
        h = conversation_hash(rec)
        if h not in seen:
            seen.add(h)
            unique_sft.append(rec)

    # Deduplicate DPO
    seen_dpo: set[str] = set()
    unique_dpo: list[dict] = []
    for rec in dpo_records:
        h = conversation_hash(rec)
        if h not in seen_dpo:
            seen_dpo.add(h)
            unique_dpo.append(rec)

    print(f"\n  SFT: {len(sft_records)} total → {len(unique_sft)} unique")
    print(f"  DPO: {len(dpo_records)} total → {len(unique_dpo)} unique")

    return unique_sft, unique_dpo


def validate_conversations(records: list[dict]) -> list[dict]:
    """Validate each conversation has proper structure."""
    valid = []
    for rec in records:
        convs = rec.get("conversations", [])
        if len(convs) < 2:
            continue
        # Must start with human turn
        if convs[0].get("from") != "human":
            continue
        # Must have at least one gpt response
        if not any(c.get("from") == "gpt" for c in convs):
            continue
        # Check for empty values
        if any(not c.get("value", "").strip() for c in convs):
            continue
        valid.append(rec)

    dropped = len(records) - len(valid)
    if dropped:
        print(f"  Validation: dropped {dropped} invalid conversations")
    return valid


def split_train_eval(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deterministic train/eval split."""
    import random as rng

    rng.seed(HP.seed)
    shuffled = records.copy()
    rng.shuffle(shuffled)
    split_idx = max(1, int(len(shuffled) * (1 - HP.eval_split)))
    return shuffled[:split_idx], shuffled[split_idx:]


def sharegpt_to_chatml(record: dict) -> str:
    """Convert a single ShareGPT record to ChatML format for training."""
    messages = []
    # Add system prompt for Lex identity
    messages.append(
        "<|im_start|>system\n"
        "You are Lex, Damian's personal AI assistant and OpenClaw router agent "
        "for the Agentop multi-agent system. You route requests to the correct "
        "agent, select appropriate tools, and provide expert help on Agentop's "
        "architecture, Python, Rust, TypeScript, DevOps, and ML engineering. "
        "You follow docs-first governance and never hallucinate agent capabilities."
        "<|im_end|>\n"
    )
    for turn in record.get("conversations", []):
        role = "user" if turn["from"] == "human" else "assistant"
        messages.append(f"<|im_start|>{role}\n{turn['value']}<|im_end|>\n")
    return "".join(messages)


def prepare_data() -> tuple[Path, Path, int, int]:
    """Full data prep pipeline. Returns (train_path, eval_path, n_train, n_eval)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sft_records, dpo_records = merge_and_deduplicate()
    sft_records = validate_conversations(sft_records)

    train_recs, eval_recs = split_train_eval(sft_records)

    # Write merged train set
    with open(MERGED_DATASET, "w") as f:
        for rec in train_recs:
            json.dump(rec, f)
            f.write("\n")

    # Write eval set
    with open(EVAL_SPLIT, "w") as f:
        for rec in eval_recs:
            json.dump(rec, f)
            f.write("\n")

    # Write DPO data alongside
    dpo_path = OUTPUT_DIR / "dpo_train.jsonl"
    with open(dpo_path, "w") as f:
        for rec in dpo_records:
            json.dump(rec, f)
            f.write("\n")

    print(f"\n  ✓ Train: {len(train_recs)} conversations → {MERGED_DATASET}")
    print(f"  ✓ Eval:  {len(eval_recs)} conversations → {EVAL_SPLIT}")
    print(f"  ✓ DPO:   {len(dpo_records)} pairs → {dpo_path}")

    return MERGED_DATASET, EVAL_SPLIT, len(train_recs), len(eval_recs)


# ══════════════════════════════════════════════════════════════════════════
# Stage 2: QLoRA Fine-tuning (Unsloth)
# ══════════════════════════════════════════════════════════════════════════


def check_gpu() -> dict:
    """Check GPU availability and VRAM."""
    info = {"has_cuda": False, "gpu_name": "none", "vram_gb": 0.0}
    try:
        import torch

        if torch.cuda.is_available():
            info["has_cuda"] = True
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["vram_gb"] = torch.cuda.get_device_properties(0).total_mem / (1024**3)
    except ImportError:
        pass
    return info


def run_sft(train_path: Path, eval_path: Path, resume_from: str | None = None) -> Path:
    """Run supervised fine-tuning with Unsloth + QLoRA."""
    print("\n═══ Stage 2: QLoRA Fine-tuning ═══")

    gpu_info = check_gpu()
    print(f"  GPU: {gpu_info['gpu_name']} ({gpu_info['vram_gb']:.1f} GB VRAM)")
    if not gpu_info["has_cuda"]:
        print("  [ERROR] No CUDA GPU detected. QLoRA requires a GPU.")
        print("  Try: --prep-only to prepare data without training,")
        print("       then transfer to a GPU machine.")
        sys.exit(1)

    # Import heavy dependencies only when training
    try:
        from unsloth import FastLanguageModel
    except ImportError:
        print("  [ERROR] unsloth not installed. Install with:")
        print("    pip install 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'")
        sys.exit(1)

    from datasets import load_dataset
    from transformers import TrainingArguments
    from trl import SFTTrainer

    # Load base model with 4-bit quantization
    print(f"  Loading base model: {HP.base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=HP.base_model,
        max_seq_length=HP.max_seq_len,
        dtype=None,  # auto-detect
        load_in_4bit=True,
    )

    # Apply LoRA adapters
    model = FastLanguageModel.get_peft_model(
        model,
        r=HP.lora_r,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=HP.lora_alpha,
        lora_dropout=HP.lora_dropout,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=HP.seed,
    )

    # Load datasets
    print("  Loading datasets...")
    train_ds = load_dataset("json", data_files=str(train_path), split="train")
    eval_ds = load_dataset("json", data_files=str(eval_path), split="train")

    def formatting_func(examples: dict) -> list[str]:
        """Convert ShareGPT batch to ChatML strings."""
        texts = []
        conversations_list = examples.get("conversations", [])
        for convs in conversations_list:
            record = {"conversations": convs}
            texts.append(sharegpt_to_chatml(record))
        return texts

    # Training arguments
    sft_output = OUTPUT_DIR / "sft-checkpoint"
    training_args = TrainingArguments(
        output_dir=str(sft_output),
        per_device_train_batch_size=HP.batch_size,
        gradient_accumulation_steps=HP.grad_accum,
        num_train_epochs=HP.epochs,
        learning_rate=HP.lr,
        warmup_ratio=HP.warmup_ratio,
        weight_decay=HP.weight_decay,
        fp16=not gpu_info.get("bf16", False),
        bf16=gpu_info.get("bf16", False),
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=3,
        seed=HP.seed,
        report_to="none",
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        max_grad_norm=0.3,
    )

    # Trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        formatting_func=formatting_func,
        max_seq_length=HP.max_seq_len,
        args=training_args,
        packing=True,  # Unsloth efficient packing
    )

    # Resume or start fresh
    print(f"  Training for {HP.epochs} epochs...")
    print(f"  Effective batch size: {HP.batch_size * HP.grad_accum}")
    start_time = time.monotonic()

    if resume_from:
        print(f"  Resuming from: {resume_from}")
        trainer.train(resume_from_checkpoint=resume_from)
    else:
        trainer.train()

    elapsed = time.monotonic() - start_time
    print(f"\n  ✓ SFT training complete ({elapsed:.0f}s)")

    # Save final model
    final_dir = OUTPUT_DIR / "lex-sft"
    model.save_pretrained(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))
    print(f"  ✓ Model saved to {final_dir}")

    # Log training metrics
    train_loss = trainer.state.log_history[-1].get("train_loss", 0)
    eval_loss = trainer.state.log_history[-1].get("eval_loss", 0)
    print(f"  Train loss: {train_loss:.4f}")
    print(f"  Eval loss:  {eval_loss:.4f}")

    return final_dir


def run_dpo(sft_model_path: Path) -> Path:
    """Run DPO alignment pass on the SFT model."""
    print("\n═══ Stage 2b: DPO Alignment ═══")

    dpo_path = OUTPUT_DIR / "dpo_train.jsonl"
    if not dpo_path.exists() or dpo_path.stat().st_size == 0:
        print("  [SKIP] No DPO data available. Skipping alignment.")
        return sft_model_path

    try:
        from unsloth import FastLanguageModel
    except ImportError:
        print("  [SKIP] Unsloth not installed. Skipping DPO.")
        return sft_model_path

    from datasets import load_dataset
    from trl import DPOConfig, DPOTrainer

    # Load SFT model
    print(f"  Loading SFT model: {sft_model_path}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(sft_model_path),
        max_seq_length=HP.max_seq_len,
        dtype=None,
        load_in_4bit=True,
    )

    # Load DPO dataset
    dpo_ds = load_dataset("json", data_files=str(dpo_path), split="train")
    print(f"  DPO dataset: {len(dpo_ds)} preference pairs")

    dpo_output = OUTPUT_DIR / "lex-dpo"
    dpo_config = DPOConfig(
        output_dir=str(dpo_output),
        per_device_train_batch_size=HP.batch_size,
        gradient_accumulation_steps=HP.grad_accum,
        num_train_epochs=1,  # DPO is typically 1 epoch
        learning_rate=HP.lr / 10,  # Lower LR for DPO
        warmup_ratio=0.1,
        beta=0.1,  # DPO beta (KL penalty strength)
        logging_steps=5,
        save_strategy="epoch",
        seed=HP.seed,
        report_to="none",
        optim="adamw_8bit",
    )

    trainer = DPOTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dpo_ds,
        args=dpo_config,
    )

    print("  Training DPO alignment...")
    start_time = time.monotonic()
    trainer.train()
    elapsed = time.monotonic() - start_time
    print(f"\n  ✓ DPO alignment complete ({elapsed:.0f}s)")

    # Save aligned model
    model.save_pretrained(str(dpo_output))
    tokenizer.save_pretrained(str(dpo_output))
    print(f"  ✓ Aligned model saved to {dpo_output}")

    return dpo_output


# ══════════════════════════════════════════════════════════════════════════
# Stage 3: Export to GGUF + Ollama
# ══════════════════════════════════════════════════════════════════════════


def export_gguf(model_path: Path) -> Path:
    """Convert fine-tuned model to GGUF format for Ollama."""
    print("\n═══ Stage 3: GGUF Export ═══")

    try:
        from unsloth import FastLanguageModel
    except ImportError:
        print("  [ERROR] Unsloth required for GGUF export.")
        sys.exit(1)

    GGUF_DIR.mkdir(parents=True, exist_ok=True)

    print(f"  Loading model from: {model_path}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(model_path),
        max_seq_length=HP.max_seq_len,
        dtype=None,
        load_in_4bit=True,
    )

    # Export to GGUF
    gguf_path = GGUF_DIR / f"lex-{HP.quant_method}.gguf"
    print(f"  Exporting to GGUF ({HP.quant_method})...")
    model.save_pretrained_gguf(
        str(GGUF_DIR),
        tokenizer,
        quantization_method=HP.quant_method,
    )
    print(f"  ✓ GGUF exported to {GGUF_DIR}")

    return gguf_path


def create_modelfile(gguf_path: Path) -> Path:
    """Generate Ollama Modelfile for the fine-tuned Lex."""
    modelfile_path = OUTPUT_DIR / "Modelfile"

    # Find the actual GGUF file (Unsloth names it differently)
    gguf_files = list(GGUF_DIR.glob("*.gguf"))
    if gguf_files:
        gguf_ref = gguf_files[0].name
    else:
        gguf_ref = f"lex-{HP.quant_method}.gguf"

    content = f"""# Lex — Damian's OpenClaw Router Agent
# Fine-tuned on Agentop routing, tool selection, and personal preferences
# Base: Qwen2.5-7B-Instruct | Method: QLoRA (r={HP.lora_r}) + DPO
# Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}

FROM ./gguf/{gguf_ref}

TEMPLATE \"\"\"<|im_start|>system
{{{{ .System }}}}<|im_end|>
<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
\"\"\"

SYSTEM \"\"\"You are Lex, Damian's personal AI assistant and OpenClaw router agent for the Agentop multi-agent system. You excel at:

1. ROUTING: Classify user intent and route to the correct agent (soul_core, devops_agent, monitor_agent, self_healer_agent, code_review_agent, security_agent, data_agent, comms_agent, cs_agent, it_agent, knowledge_agent)
2. TOOL SELECTION: Choose the right tools from 12 native + 26 MCP tools, considering risk levels and governance constraints
3. ARCHITECTURE: Deep knowledge of Agentop's LangGraph orchestrator, Drift Guard, A2UI event bus, and docs-first governance
4. CODING: Expert in Python (FastAPI, Pydantic, pytest), Rust (PyO3, nalgebra), TypeScript (Next.js), and DevOps
5. ML ENGINEERING: Fine-tuning, quantization (TurboQuant), embeddings, eval frameworks

You follow these invariants:
- Agents never call each other directly — all communication routes through the orchestrator
- Documentation precedes mutation (no silent architectural changes)
- No dynamic tool registration (INV-3)
- Every agent has an isolated memory namespace

When routing, respond with structured JSON including: agent_id, reasoning, tools_needed, urgency, confidence.\"\"\"

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER num_ctx 4096
PARAMETER repeat_penalty 1.1
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|im_start|>"
"""

    modelfile_path.write_text(content)
    print(f"  ✓ Modelfile written to {modelfile_path}")
    return modelfile_path


def import_to_ollama(modelfile_path: Path) -> bool:
    """Import the model into Ollama."""
    import subprocess

    model_name = HP.ollama_model_name
    print(f"\n  Importing as '{model_name}' into Ollama...")

    result = subprocess.run(
        ["ollama", "create", model_name, "-f", str(modelfile_path)],
        cwd=str(OUTPUT_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode == 0:
        print(f"  ✓ Model '{model_name}' imported to Ollama")
        print(f"    Test with: ollama run {model_name}")
        return True
    else:
        print(f"  [ERROR] Ollama import failed: {result.stderr}")
        return False


# ══════════════════════════════════════════════════════════════════════════
# Stage 4: Experiment Tracking
# ══════════════════════════════════════════════════════════════════════════


def track_experiment(
    n_train: int,
    n_eval: int,
    n_dpo: int,
    model_path: Path | None,
    gguf_path: Path | None,
    stages_completed: list[str],
    elapsed_s: float,
) -> str | None:
    """Log the full pipeline run to ExperimentTracker."""
    try:
        from backend.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        run_id = tracker.start_run(
            experiment_name="lex_finetune",
            hyperparameters=HP.to_dict(),
            model_type="qlora_sft_dpo",
            dataset_version=f"sft{n_train}_dpo{n_dpo}",
            tags={
                "base_model": HP.base_model,
                "pipeline": "finetune_lex",
                "target": "openclaw_router",
            },
        )

        tracker.log_metric(run_id, "sft_train_size", n_train)
        tracker.log_metric(run_id, "sft_eval_size", n_eval)
        tracker.log_metric(run_id, "dpo_pairs", n_dpo)
        tracker.log_metric(run_id, "total_elapsed_s", elapsed_s)

        if model_path and model_path.exists():
            tracker.log_artifact(run_id, str(model_path))
        if gguf_path and gguf_path.exists():
            tracker.log_artifact(run_id, str(gguf_path))

        tracker.end_run(
            run_id,
            status="completed",
            notes=f"Stages: {', '.join(stages_completed)}",
        )

        print(f"\n  ✓ Experiment tracked: {run_id}")
        return run_id

    except ImportError:
        print("  [WARN] ExperimentTracker not available, skipping tracking")
        return None


# ══════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════════


def print_banner() -> None:
    print(
        """
╔══════════════════════════════════════════════════════════════╗
║  LEX FINE-TUNING PIPELINE — OpenClaw Router Agent           ║
║  Base: Qwen2.5-7B-Instruct · Method: QLoRA + DPO           ║
║  Target: Agentop multi-agent routing & tool selection        ║
╚══════════════════════════════════════════════════════════════╝"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune Lex — OpenClaw Router Agent")
    parser.add_argument("--prep-only", action="store_true", help="Only prepare data (no GPU needed)")
    parser.add_argument("--resume", type=str, default=None, help="Resume from checkpoint path")
    parser.add_argument("--dpo", action="store_true", help="Run DPO alignment (requires --sft-model)")
    parser.add_argument("--sft-model", type=str, default=None, help="Path to SFT model for DPO or export")
    parser.add_argument("--export-only", action="store_true", help="Only export existing model to GGUF")
    parser.add_argument("--base-model", type=str, default=None, help="Override base model")
    parser.add_argument("--epochs", type=int, default=None, help="Override training epochs")
    parser.add_argument("--lr", type=float, default=None, help="Override learning rate")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip Ollama import step")
    args = parser.parse_args()

    # Apply overrides
    if args.base_model:
        HP.base_model = args.base_model
    if args.epochs:
        HP.epochs = args.epochs
    if args.lr:
        HP.lr = args.lr

    print_banner()
    start_time = time.monotonic()
    stages_completed: list[str] = []

    # ── Stage 1: Data Prep (always runs) ──
    train_path, eval_path, n_train, n_eval = prepare_data()
    stages_completed.append("data_prep")

    # Count DPO pairs
    dpo_path = OUTPUT_DIR / "dpo_train.jsonl"
    n_dpo = 0
    if dpo_path.exists():
        with open(dpo_path) as f:
            n_dpo = sum(1 for _ in f)

    print("\n  Dataset summary:")
    print(f"    SFT train:  {n_train} conversations")
    print(f"    SFT eval:   {n_eval} conversations")
    print(f"    DPO pairs:  {n_dpo}")
    print(f"    Base model: {HP.base_model}")
    print(f"    LoRA r={HP.lora_r}, α={HP.lora_alpha}")
    print(f"    Epochs={HP.epochs}, LR={HP.lr}, Batch={HP.batch_size}×{HP.grad_accum}")

    if args.prep_only:
        print("\n  --prep-only: Stopping after data preparation.")
        elapsed = time.monotonic() - start_time
        track_experiment(n_train, n_eval, n_dpo, None, None, stages_completed, elapsed)
        return

    # ── Stage 2: Fine-tuning ──
    model_path: Path | None = None

    if args.export_only:
        # Skip training, use existing model
        model_path = Path(args.sft_model) if args.sft_model else OUTPUT_DIR / "lex-sft"
        if not model_path.exists():
            print(f"  [ERROR] Model not found at {model_path}")
            sys.exit(1)
        print(f"\n  --export-only: Using existing model at {model_path}")
    elif args.dpo and args.sft_model:
        # DPO only
        sft_path = Path(args.sft_model)
        if not sft_path.exists():
            print(f"  [ERROR] SFT model not found at {sft_path}")
            sys.exit(1)
        model_path = run_dpo(sft_path)
        stages_completed.append("dpo")
    else:
        # Full SFT pipeline
        model_path = run_sft(train_path, eval_path, resume_from=args.resume)
        stages_completed.append("sft")

        # Optional DPO alignment
        if n_dpo > 0:
            model_path = run_dpo(model_path)
            stages_completed.append("dpo")

    # ── Stage 3: Export ──
    gguf_path = export_gguf(model_path)
    stages_completed.append("gguf_export")

    modelfile_path = create_modelfile(gguf_path)
    stages_completed.append("modelfile")

    if not args.skip_ollama:
        if import_to_ollama(modelfile_path):
            stages_completed.append("ollama_import")

    # ── Stage 4: Track ──
    elapsed = time.monotonic() - start_time
    track_experiment(n_train, n_eval, n_dpo, model_path, gguf_path, stages_completed, elapsed)

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  Pipeline complete in {elapsed:.0f}s")
    print(f"  Stages: {' → '.join(stages_completed)}")
    if model_path:
        print(f"  Model:  {model_path}")
    print(f"  GGUF:   {GGUF_DIR}")
    if not args.skip_ollama:
        print(f"  Ollama: ollama run {HP.ollama_model_name}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
