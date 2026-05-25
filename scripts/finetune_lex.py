#!/usr/bin/env python3
# lex-v3: Gemma 3 12B (default) — also supports Qwen2.5 via LEX_BASE_MODEL env
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
  LEX_BASE_MODEL        HuggingFace base model (default: google/gemma-3-12b-it)
  LEX_EPOCHS            Training epochs (default: 3)
  LEX_LR                Learning rate (default: 2e-4)
  LEX_BATCH_SIZE        Per-device batch size (default: 1, safe for 12GB VRAM with Gemma3)
  LEX_GRAD_ACCUM        Gradient accumulation steps (default: 8, effective batch=8)
  LEX_MAX_SEQ_LEN       Maximum sequence length (default: 4096)
  LEX_LORA_R            LoRA rank (default: 64)
  LEX_LORA_ALPHA         LoRA alpha (default: 16)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = Path(os.getenv("LEX_TRAINING_DIR", str(ROOT / "data" / "training")))
DPO_DIR = Path(os.getenv("LEX_DPO_DIR", str(ROOT / "data" / "dpo")))
OUTPUT_DIR = Path(os.getenv("LEX_OUTPUT_DIR", str(ROOT / "output" / "lex-finetune")))
MERGED_DATASET = OUTPUT_DIR / "merged_train.jsonl"
EVAL_SPLIT = OUTPUT_DIR / "eval_split.jsonl"
GGUF_DIR = OUTPUT_DIR / "gguf"
TRAINING_METRICS_PATH = OUTPUT_DIR / "training_metrics.jsonl"
EVAL_ARTIFACT_PATH = OUTPUT_DIR / "eval.json"


# ── Hyperparameters (env-overridable) ─────────────────────────────────────
class HParams:
    base_model: str = os.getenv("LEX_BASE_MODEL", "google/gemma-3-12b-it")
    epochs: int = int(os.getenv("LEX_EPOCHS", "3"))
    lr: float = float(os.getenv("LEX_LR", "2e-4"))
    batch_size: int = int(os.getenv("LEX_BATCH_SIZE", "1"))   # 1 safe for 12GB VRAM w/ Gemma3
    grad_accum: int = int(os.getenv("LEX_GRAD_ACCUM", "8"))  # effective batch = 8
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


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")


def _append_training_metric(step: int, loss: float, accuracy: float) -> None:
    _append_jsonl(
        TRAINING_METRICS_PATH,
        {
            "step": step,
            "loss": loss,
            "accuracy": accuracy,
            "ts": datetime.now(UTC).isoformat(),
        },
    )


def _build_metrics_callback(callback_base: type[Any]) -> Any:
    class JsonlMetricsCallback(callback_base):
        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001, ANN202, D401
            del args, control, kwargs
            metrics = logs or {}
            if not state.global_step:
                return

            loss_value = metrics.get("loss", metrics.get("train_loss", metrics.get("eval_loss")))
            if loss_value is None:
                return

            accuracy_value = metrics.get(
                "accuracy",
                metrics.get("eval_accuracy", metrics.get("train_accuracy", metrics.get("reward_accuracy", 0.0))),
            )
            try:
                loss = float(loss_value)
            except (TypeError, ValueError):
                return
            try:
                accuracy = float(accuracy_value)
            except (TypeError, ValueError):
                accuracy = 0.0
            _append_training_metric(step=int(state.global_step), loss=loss, accuracy=accuracy)

    return JsonlMetricsCallback()


def _write_eval_artifact(eval_score: float, eval_n: int) -> None:
    EVAL_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVAL_ARTIFACT_PATH.write_text(
        json.dumps({"eval_score": eval_score, "eval_n": eval_n}, indent=2),
        encoding="utf-8",
    )


def _iter_routing_eval_examples(limit: int) -> list[tuple[str, str]]:
    samples: list[tuple[str, str]] = []
    if not DATA_DIR.exists():
        return samples

    for path in sorted(DATA_DIR.glob("*.jsonl")):
        try:
            with path.open(encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if len(samples) >= limit:
                        return samples
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    user_message = record.get("user_message")
                    expected_agent = record.get("expected_agent")
                    if not isinstance(user_message, str) or not isinstance(expected_agent, str):
                        continue
                    samples.append((user_message, expected_agent))
        except OSError:
            continue
    return samples


def run_native_routing_eval(model_name: str, limit: int = 100) -> dict[str, float | int]:
    """Run a quick local routing eval on the first N usable training rows."""
    print(f"\n  Running native routing eval against {model_name}...")
    samples = _iter_routing_eval_examples(limit)
    if not samples:
        result = {"eval_score": 0.0, "eval_n": 0}
        _write_eval_artifact(eval_score=0.0, eval_n=0)
        print("  [WARN] No usable routing eval rows found in data/training/*.jsonl")
        return result

    correct = 0
    for user_message, expected_agent in samples:
        try:
            completed = subprocess.run(
                ["ollama", "run", model_name, user_message],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            output = f"{completed.stdout}\n{completed.stderr}".lower()
        except (OSError, subprocess.SubprocessError):
            output = ""

        if expected_agent.lower() in output:
            correct += 1

    eval_n = len(samples)
    eval_score = correct / eval_n if eval_n else 0.0
    _write_eval_artifact(eval_score=eval_score, eval_n=eval_n)
    print(f"  Eval accuracy: {eval_score:.3f} ({correct}/{eval_n})")
    return {"eval_score": eval_score, "eval_n": eval_n}


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
                # live_dpo routing preference format → normalize on load
                elif "user_message" in obj and "chosen_agent" in obj:
                    normalized = _normalize_live_dpo(obj)
                    if normalized:
                        records.append(normalized)
                # routing pairs format: {user_message, expected_agent, reasoning, ...}
                elif "user_message" in obj and "expected_agent" in obj:
                    normalized = _normalize_routing_pair(obj)
                    if normalized:
                        records.append(normalized)
                # trajectory format: {task, task_type, goal, chosen_agent, plan, ...}
                elif "task_type" in obj and "chosen_agent" in obj:
                    normalized = _normalize_trajectory(obj)
                    if normalized:
                        records.append(normalized)
                else:
                    print(f"  [WARN] {path.name}:{i} \u2014 unknown format, skipping")
            except json.JSONDecodeError:
                print(f"  [WARN] {path.name}:{i} \u2014 invalid JSON, skipping")
    return records


def _normalize_routing_pair(rec: dict) -> dict | None:
    """Convert routing pair format to ShareGPT conversation for SFT.

    Routing pair format:
        {user_message, expected_agent, reasoning, difficulty, expected_tools, confidence}
    ShareGPT output:
        {conversations: [{from: human, value: ...}, {from: gpt, value: ...}]}
    """
    msg = rec.get("user_message") or rec.get("task")
    agent = rec.get("expected_agent")
    reasoning = rec.get("reasoning", "")
    tools = rec.get("expected_tools") or []
    if not msg or not agent:
        return None
    tools_str = f" using {', '.join(tools)}" if tools else ""
    human_turn = f"Route this request to the correct agent: {msg}"
    gpt_turn = f"I will route this to {agent}{tools_str}. {reasoning}".strip()
    return {
        "conversations": [
            {"from": "human", "value": human_turn},
            {"from": "gpt", "value": gpt_turn},
        ],
        "_source": "routing_pair",
        "_expected_agent": agent,
        "_difficulty": rec.get("difficulty", ""),
        "_confidence": rec.get("confidence", 0.0),
    }



def _normalize_trajectory(rec: dict) -> dict | None:
    """Convert trajectory format to ShareGPT conversation for SFT.

    Trajectory format:
        {task, task_type, goal, chosen_agent, plan, constraints, ...}
    """
    task = rec.get("task") or rec.get("goal")
    agent = rec.get("chosen_agent")
    plan = rec.get("plan") or []
    if not task or not agent:
        return None
    plan_str = " → ".join(plan) if plan else ""
    human_turn = f"Route this task to the correct agent: {task}"
    gpt_turn = f"I will route this to {agent}. Plan: {plan_str}".strip(" .")
    return {
        "conversations": [
            {"from": "human", "value": human_turn},
            {"from": "gpt", "value": gpt_turn},
        ],
        "_source": "trajectory",
        "_chosen_agent": agent,
        "_task_type": rec.get("task_type", ""),
    }


def _normalize_live_dpo(rec: dict) -> dict | None:
    """Convert live_dpo routing preference format to {prompt, chosen, rejected}.

    live_dpo format:  {user_message, chosen_agent, good_response, bad_response,
                       good_plan, bad_plan, why_good_is_better, category, ...}
    DPO format:       {prompt, chosen, rejected}

    Returns None if the record lacks enough signal for DPO training.
    """
    msg = rec.get("user_message") or rec.get("task")
    good = rec.get("good_response")
    bad = rec.get("bad_response")
    if not msg or not good or not bad:
        return None
    # Skip trivially identical chosen/rejected
    if good.strip() == bad.strip():
        return None
    return {
        "prompt": (
            "You are Lex, the Agentop router. "
            f"Route this user message to the correct agent: {msg}"
        ),
        "chosen": good,
        "rejected": bad,
        "_source": "live_dpo",
        "_category": rec.get("category", ""),
        "_chosen_agent": rec.get("chosen_agent", ""),
    }


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


LEX_SYSTEM_PROMPT = (
    "You are Lex, Damian's personal AI assistant and OpenClaw router agent "
    "for the Agentop multi-agent system. You route requests to the correct "
    "agent, select appropriate tools, and provide expert help on Agentop's "
    "architecture, Python, Rust, TypeScript, DevOps, and ML engineering. "
    "You follow docs-first governance and never hallucinate agent capabilities."
)


def _is_gemma_model(model_name: str) -> bool:
    return "gemma" in model_name.lower()


def sharegpt_to_chatml(record: dict) -> str:
    """Convert a ShareGPT record to the correct template for the configured base model.

    - Gemma 3 models  → <start_of_turn>user/model template
    - All others       → ChatML (<|im_start|>) template
    """
    if _is_gemma_model(HP.base_model):
        return _sharegpt_to_gemma3(record)
    return _sharegpt_to_chatml(record)


def _sharegpt_to_chatml(record: dict) -> str:
    """Convert a single ShareGPT record to ChatML format."""
    messages = []
    messages.append(
        "<|im_start|>system\n" + LEX_SYSTEM_PROMPT + "<|im_end|>\n"
    )
    for turn in record.get("conversations", []):
        role = "user" if turn["from"] == "human" else "assistant"
        messages.append(f"<|im_start|>{role}\n{turn['value']}<|im_end|>\n")
    return "".join(messages)


def _sharegpt_to_gemma3(record: dict) -> str:
    """Convert a single ShareGPT record to Gemma 3 turn format."""
    messages = []
    # Gemma 3 embeds the system prompt inside the first user turn
    first_user_injected = False
    for turn in record.get("conversations", []):
        if turn["from"] == "human":
            if not first_user_injected:
                content = LEX_SYSTEM_PROMPT + "\n\n" + turn["value"]
                first_user_injected = True
            else:
                content = turn["value"]
            messages.append(f"<start_of_turn>user\n{content}<end_of_turn>\n")
        else:
            messages.append(f"<start_of_turn>model\n{turn['value']}<end_of_turn>\n")
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
            info["vram_gb"] = torch.cuda.get_device_properties(0).total_memory / (1024**3)
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
    _use_unsloth = False
    try:
        from unsloth import FastLanguageModel  # type: ignore[import-untyped]
        _use_unsloth = True
    except ImportError:
        print("  [INFO] unsloth not installed — using transformers+peft fallback (fully supported).")
        print("  For ~2x faster training install unsloth:")
        print("    pip install 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'")

    from datasets import load_dataset  # type: ignore[import-untyped]
    from transformers import TrainerCallback, TrainingArguments
    from trl import SFTTrainer  # type: ignore[import-untyped]

    if _use_unsloth:
        # Load base model with 4-bit quantization via unsloth
        print(f"  Loading base model via unsloth: {HP.base_model}")
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
    else:
        # Standard transformers + peft fallback (no unsloth required)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training  # type: ignore[import-untyped]

        print(f"  Loading base model via transformers+peft: {HP.base_model}")
        _use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if _use_bf16 else torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        model = AutoModelForCausalLM.from_pretrained(
            HP.base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(HP.base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = prepare_model_for_kbit_training(model)
        model.gradient_checkpointing_enable()

        lora_config = LoraConfig(
            r=HP.lora_r,
            lora_alpha=HP.lora_alpha,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            lora_dropout=HP.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)

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
    trainer.add_callback(_build_metrics_callback(TrainerCallback))

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
        from unsloth import FastLanguageModel  # type: ignore[import-untyped]
    except ImportError:
        print("  [SKIP] Unsloth not installed. Skipping DPO.")
        return sft_model_path

    from datasets import load_dataset  # type: ignore[import-untyped]
    from transformers import TrainerCallback
    from trl import DPOConfig, DPOTrainer  # type: ignore[import-untyped]

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
    trainer.add_callback(_build_metrics_callback(TrainerCallback))

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
        from unsloth import FastLanguageModel  # type: ignore[import-untyped]
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

    base_short = HP.base_model.split("/")[-1]
    is_gemma = _is_gemma_model(HP.base_model)

    if is_gemma:
        template_block = (
            'TEMPLATE """<start_of_turn>user\n'
            "{{ .System }}\n\n{{ .Prompt }}<end_of_turn>\n"
            "<start_of_turn>model\n"
            '"""'
        )
        stop_params = 'PARAMETER stop "<end_of_turn>"'
    else:
        template_block = (
            'TEMPLATE """<|im_start|>system\n'
            "{{ .System }}<|im_end|>\n"
            "<|im_start|>user\n{{ .Prompt }}<|im_end|>\n"
            "<|im_start|>assistant\n"
            '"""'
        )
        stop_params = 'PARAMETER stop "<|im_end|>"\nPARAMETER stop "<|im_start|>"'

    content = f"""# Lex — Damian's OpenClaw Router Agent
# Fine-tuned on Agentop routing, tool selection, and personal preferences
# Base: {base_short} | Method: QLoRA (r={HP.lora_r}) + DPO
# Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}

FROM ./gguf/{gguf_ref}

{template_block}

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
{stop_params}
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


# ══════════════════════════════════════════════════════════════════════════
# Native Ollama mode: build lex-v3 from curated many-shot examples
# No GPU required — embeds examples directly into Modelfile.lex-v3
# ══════════════════════════════════════════════════════════════════════════

MODELFILE_PATH = Path(
    os.getenv("LEX_NATIVE_MODELFILE", str(ROOT / "backend" / "ml" / "models" / "Modelfile.lex-v3"))
)
GOLDEN_EVAL = Path(
    os.getenv(
        "LEX_GOLDEN_EVAL",
        str(ROOT / "data" / "training" / "golden_eval" / "lex_v2_golden.jsonl"),
    )
)

VALID_AGENTS = {
    "soul_core", "devops_agent", "monitor_agent", "self_healer_agent",
    "code_review_agent", "security_agent", "data_agent", "comms_agent",
    "cs_agent", "it_agent", "knowledge_agent", "ocr_agent", "BLOCKED",
}

AGENT_LANES: dict[str, str] = {
    "soul_core": "positioning", "devops_agent": "development",
    "monitor_agent": "evaluation", "self_healer_agent": "development",
    "code_review_agent": "evaluation", "security_agent": "evaluation",
    "data_agent": "evaluation", "comms_agent": "development",
    "cs_agent": "positioning", "it_agent": "evaluation",
    "knowledge_agent": "positioning", "ocr_agent": "development",
    "BLOCKED": "red_line",
}

WEAK_BOUNDARIES: list[tuple[str, str]] = [
    ("knowledge_agent", "soul_core"), ("monitor_agent", "it_agent"),
    ("code_review_agent", "security_agent"), ("devops_agent", "self_healer_agent"),
    ("cs_agent", "knowledge_agent"), ("it_agent", "self_healer_agent"),
    ("comms_agent", "monitor_agent"), ("data_agent", "knowledge_agent"),
]

_NATIVE_MARKER = "# --- Few-shot examples injected by scripts/finetune_lex.py ---"


def _load_native_examples() -> tuple[list[dict], list[dict]]:
    """Load labeled routing examples + golden eval cases."""
    raw: list[dict] = []
    for path in sorted(DATA_DIR.rglob("*.jsonl")):
        if "golden_eval" in str(path):
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                msg = rec.get("user_message") or rec.get("message") or rec.get("task")
                agent = rec.get("expected_agent") or rec.get("chosen_agent")
                diff = rec.get("difficulty") or rec.get("type")
                if msg and agent in VALID_AGENTS and diff not in (None, "?", "agent_response"):
                    rec["_msg"] = str(msg)
                    rec["_agent"] = agent
                    rec["_diff"] = diff
                    raw.append(rec)
        except Exception:
            continue

    golden: list[dict] = []
    if GOLDEN_EVAL.exists():
        for line in GOLDEN_EVAL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("message") and rec.get("expected_agent") in VALID_AGENTS:
                    rec["_msg"] = rec["message"]
                    rec["_agent"] = rec["expected_agent"]
                    rec["_diff"] = rec.get("category", "golden")
                    golden.append(rec)
            except Exception:
                continue
    return raw, golden


def _select_native_examples(
    raw: list[dict], golden: list[dict], max_per_cat: int = 20
) -> list[dict]:
    """Select coverage-balanced examples: golden → redline → boundary → easy."""
    selected: list[dict] = []
    seen: set[str] = set()

    def _add(rec: dict) -> bool:
        key = rec["_msg"].strip().lower()[:80]
        if key in seen:
            return False
        seen.add(key)
        selected.append(rec)
        return True

    for r in golden:
        _add(r)

    for r in raw:
        if r["_diff"] == "red_line" and r["_agent"] == "BLOCKED":
            _add(r)
        if len([x for x in selected if x["_agent"] == "BLOCKED"]) >= max_per_cat:
            break

    b_seen: dict[str, int] = {}
    for r in raw:
        if r["_diff"] not in ("hard", "ambiguous", "extreme"):
            continue
        if r["_agent"] == "BLOCKED":
            continue
        bkey = "_".join(sorted(r.get("boundary", [r["_agent"]])))
        if b_seen.get(bkey, 0) < max_per_cat:
            b_seen[bkey] = b_seen.get(bkey, 0) + 1
            _add(r)

    a_seen: dict[str, int] = {}
    for r in raw:
        if r["_diff"] != "easy":
            continue
        a = r["_agent"]
        if a_seen.get(a, 0) < max_per_cat // 2:
            a_seen[a] = a_seen.get(a, 0) + 1
            _add(r)

    return selected


def _format_native_response(rec: dict) -> str:
    agent = rec["_agent"]
    tools = (rec.get("expected_tools") or rec.get("good_tools") or [])[:3]
    reasoning = str(rec.get("reasoning") or rec.get("rationale") or f"Routing to {agent}")[:150]
    conf = float(rec.get("confidence") or rec.get("confidence_min") or 0.85)
    diff = rec["_diff"]
    inferred = diff in ("hard", "ambiguous", "tier1_ambiguous", "tier2_ambiguous")
    boundary = rec.get("boundary", [])
    assessment = (
        "Hard block — prohibited intent"
        if agent == "BLOCKED"
        else (
            f"Boundary: {agent} wins over {', '.join(b for b in boundary if b != agent)}"
            if boundary
            else f"Clear {agent} task"
        )
    )
    return json.dumps({
        "agent_id": agent,
        "reasoning": reasoning,
        "tools_needed": list(tools),
        "urgency": "high" if conf >= 0.9 and agent != "BLOCKED" else "medium",
        "confidence": round(conf, 2),
        "ordo_lane": AGENT_LANES.get(agent, "development"),
        "ordo_inferred": inferred,
        "ordo_assessment": assessment,
    }, ensure_ascii=False)


def build_lex_v3_native(max_per_cat: int = 20, skip_create: bool = False) -> None:
    """
    Ollama-native lex-v3 builder.
    Embeds curated few-shot MESSAGE pairs into Modelfile.lex-v3 and runs ollama create.
    """
    print("\n═══ Native Mode: Building lex-v3 from curated examples ═══")
    raw, golden = _load_native_examples()
    print(f"  Labeled examples:  {len(raw)}")
    print(f"  Golden eval cases: {len(golden)}")

    selected = _select_native_examples(raw, golden, max_per_cat=max_per_cat)

    by_agent: dict[str, int] = {}
    by_diff: dict[str, int] = {}
    for rec in selected:
        by_agent[rec["_agent"]] = by_agent.get(rec["_agent"], 0) + 1
        by_diff[rec["_diff"]] = by_diff.get(rec["_diff"], 0) + 1

    print(f"  Selected: {len(selected)} examples")
    print("  By agent: " + ", ".join(f"{a}:{c}" for a, c in sorted(by_agent.items())))
    print("  By diff:  " + ", ".join(f"{d}:{c}" for d, c in sorted(by_diff.items())))

    # Build MESSAGE block
    lines: list[str] = [
        "",
        _NATIVE_MARKER,
        f"# Total: {len(selected)} examples (golden + hard + redline + easy)",
        "# Each pair teaches: Ordo lane + grounded signal + confidence calibration",
        "",
    ]
    for rec in selected:
        msg = rec["_msg"].replace("\n", " ").strip()
        resp = _format_native_response(rec)
        lines.append(f"MESSAGE user {msg}")
        lines.append(f"MESSAGE assistant {resp}")
        lines.append("")
    message_block = "\n".join(lines)

    # Write Modelfile
    text = MODELFILE_PATH.read_text(encoding="utf-8")
    if _NATIVE_MARKER in text:
        text = text[: text.index(_NATIVE_MARKER)].rstrip() + "\n"
    if "PARAMETER num_predict" not in text:
        text += "\nPARAMETER num_predict 200\nPARAMETER temperature 0.1\n"
    MODELFILE_PATH.write_text(text.rstrip() + "\n" + message_block, encoding="utf-8")
    print(f"  Modelfile written: {MODELFILE_PATH}")

    if skip_create:
        print("  --skip-create: Modelfile written, skipping ollama create")
        return

    model_name = "lex-v3"
    print(f"\n  Running: ollama create {model_name} -f backend/ml/models/Modelfile.lex-v3")
    result = subprocess.run(
        ["ollama", "create", model_name, "-f", str(MODELFILE_PATH)],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  [ERROR] ollama create failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"\n  [OK] Native model '{model_name}' created.")
    run_native_routing_eval(model_name)
    print("\n  Test:")
    print(f'    ollama run {model_name} "The backend crashed, restart it"')
    print("    python scripts/eval_lex.py --model lex-v3")


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
    parser.add_argument("--native", action="store_true",
                        help="Ollama-native mode: embed curated examples into Modelfile.lex-v3 (no GPU needed)")
    parser.add_argument("--max-per-cat", type=int, default=20,
                        help="Max examples per category in native mode (default: 20)")
    parser.add_argument("--skip-create", action="store_true",
                        help="Native mode: write Modelfile but skip ollama create")
    parser.add_argument("--dry-run", action="store_true",
                        help="Native mode: print stats only, do not write Modelfile or create model")
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_METRICS_PATH.unlink(missing_ok=True)
    EVAL_ARTIFACT_PATH.unlink(missing_ok=True)

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

    # ── Native Ollama mode (no GPU required) ──
    if args.native:
        if args.dry_run:
            print("\n═══ Native Mode: Dry run ═══")
            raw, golden = _load_native_examples()
            print(f"  Labeled examples:  {len(raw)}")
            print(f"  Golden eval cases: {len(golden)}")
            selected = _select_native_examples(raw, golden, max_per_cat=args.max_per_cat)
            by_agent: dict[str, int] = {}
            by_diff: dict[str, int] = {}
            for rec in selected:
                by_agent[rec["_agent"]] = by_agent.get(rec["_agent"], 0) + 1
                by_diff[rec["_diff"]] = by_diff.get(rec["_diff"], 0) + 1
            print(f"  Would inject: {len(selected)} examples")
            print("  By agent: " + ", ".join(f"{a}:{c}" for a, c in sorted(by_agent.items())))
            print("  By diff:  " + ", ".join(f"{d}:{c}" for d, c in sorted(by_diff.items())))
            print("\n  --dry-run: skipping Modelfile write and ollama create")
            return
        build_lex_v3_native(max_per_cat=args.max_per_cat, skip_create=args.skip_create)
        return

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
