"""
Fine-tune Qwen2.5-Coder-3B-Instruct on webgen training data.

Usage:
    python scripts/finetune_webgen.py
    python scripts/finetune_webgen.py --epochs 2 --data data/training/webgen_sharegpt_*.jsonl

Hardware target: RTX 4070 Laptop GPU (8.6 GB VRAM)
Method: 4-bit QLoRA (bitsandbytes NF4)
Output: models/lex-webgen-v1/
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

# ── Imports ───────────────────────────────────────────────────────────────────

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTTrainer  # type: ignore[attr-defined]

# ── Config ────────────────────────────────────────────────────────────────────

BASE_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"
OUTPUT_DIR = "models/lex-webgen-v1"
DATA_GLOB = "data/training/webgen_sharegpt_*.jsonl"

LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]

MAX_SEQ_LENGTH = 3072
BATCH_SIZE = 1
GRAD_ACCUM = 8
LEARNING_RATE = 2e-4
NUM_EPOCHS = 3
WARMUP_RATIO = 0.03
SAVE_STEPS = 100

CHAT_TEMPLATE = (
    "<|im_start|>system\n{system}<|im_end|>\n"
    "<|im_start|>user\n{user}<|im_end|>\n"
    "<|im_start|>assistant\n{assistant}<|im_end|>"
)

SYSTEM_MSG = (
    "You are an expert frontend developer specializing in beautiful, "
    "conversion-focused websites. Generate clean, semantic, responsive HTML "
    "using Tailwind CSS utility classes. Output ONLY raw HTML code."
)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_sharegpt_files(pattern: str) -> list[dict]:
    """Load and flatten ShareGPT JSONL files."""
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"[ERROR] No data files found matching: {pattern}")
        sys.exit(1)

    records = []
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    print(f"Loaded {len(records)} examples from {len(files)} file(s)")
    return records


def format_record(record: dict) -> str:
    """Convert ShareGPT conversation to a single training text."""
    convs = record.get("conversations", [])
    if len(convs) < 2:
        return ""
    human_msg = next((c["value"] for c in convs if c["from"] == "human"), "")
    gpt_msg = next((c["value"] for c in convs if c["from"] == "gpt"), "")
    if not human_msg or not gpt_msg:
        return ""
    return CHAT_TEMPLATE.format(
        system=SYSTEM_MSG,
        user=human_msg,
        assistant=gpt_msg,
    )


def build_dataset(data_glob: str) -> Dataset:
    records = load_sharegpt_files(data_glob)
    texts = [format_record(r) for r in records]
    texts = [t for t in texts if len(t) > 200]
    print(f"Final dataset: {len(texts)} training examples")
    return Dataset.from_dict({"text": texts})


# ── Model loading ─────────────────────────────────────────────────────────────

def load_base_model(model_name: str):
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    print(f"Loading base model: {model_name}")
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        attn_implementation="flash_attention_2" if _has_flash_attn() else "eager",
    )
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    return model, tokenizer


def _has_flash_attn() -> bool:
    try:
        import flash_attn  # type: ignore[import-untyped]  # noqa: F401
        return True
    except ImportError:
        return False


# ── LoRA ──────────────────────────────────────────────────────────────────────

def apply_lora(model):
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGET_MODULES,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model


# ── Training ──────────────────────────────────────────────────────────────────

def train(
    data_glob: str,
    output_dir: str,
    epochs: int,
    resume: bool,
) -> None:
    dataset = build_dataset(data_glob)
    model, tokenizer = load_base_model(BASE_MODEL)
    model = apply_lora(model)

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        learning_rate=LEARNING_RATE,
        lr_scheduler_type="cosine",
        warmup_ratio=WARMUP_RATIO,
        bf16=True,
        fp16=False,
        max_grad_norm=0.3,
        logging_steps=10,
        save_strategy="steps",
        save_steps=SAVE_STEPS,
        save_total_limit=3,
        eval_strategy="no",
        report_to="none",
        dataloader_num_workers=0,
        remove_unused_columns=False,
    )

    trainer = SFTTrainer(  # type: ignore[call-arg]
        model=model,
        train_dataset=dataset,
        args=training_args,
        processing_class=tokenizer,
        max_seq_length=MAX_SEQ_LENGTH,  # type: ignore[call-arg]
        dataset_text_field="text",  # type: ignore[call-arg]
        packing=True,  # type: ignore[call-arg]
    )

    print(f"\n{'='*60}")
    print(f"Fine-tuning: {BASE_MODEL}")
    print(f"Examples:    {len(dataset)}")
    print(f"Epochs:      {epochs}")
    print(f"Output:      {output_dir}")
    print(f"GPU:         {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"VRAM:        {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB" if torch.cuda.is_available() else "")
    print(f"{'='*60}\n")

    trainer.train(resume_from_checkpoint=output_dir if resume else None)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"\nModel saved to: {output_dir}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)

    parser = argparse.ArgumentParser(description="Fine-tune lex-webgen-v1 on webgen training data")
    parser.add_argument("--epochs", type=int, default=NUM_EPOCHS, help=f"Training epochs (default: {NUM_EPOCHS})")
    parser.add_argument("--data", type=str, default=DATA_GLOB, help="Glob pattern for JSONL training files")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR, help="Output directory for LoRA adapter + tokenizer")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load data and model config only — do not train",
    )
    args = parser.parse_args()

    if args.dry_run:
        dataset = build_dataset(args.data)
        print(f"\nDry run complete. {len(dataset)} examples ready.")
        print(f"Sample text (first 300 chars):\n{dataset[0]['text'][:300]}")
        sys.exit(0)

    train(
        data_glob=args.data,
        output_dir=args.output,
        epochs=args.epochs,
        resume=args.resume,
    )
