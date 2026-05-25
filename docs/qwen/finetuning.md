# Qwen Fine-Tuning Guide

source: qwen_docs
topic: finetuning
tags: LoRA, QLoRA, full_finetuning, SFT, unsloth, llama_factory, RLHF, GRPO

## Fine-Tuning Methods

### Full Fine-Tuning
Updates all model parameters. Highest quality, highest VRAM cost.
Use when: sufficient GPU memory, maximum adaptation needed.

### LoRA (Low-Rank Adaptation)
Adds trainable low-rank matrices to attention layers. Only adapts a small fraction of parameters.
- Memory efficient
- Fast to train
- Composable (multiple LoRA adapters)

### QLoRA (Quantized LoRA)
Model loaded in 4-bit or 8-bit quantization + LoRA adapters trained in higher precision.
- 4× memory reduction vs full fine-tuning
- Qwen3-14B fits in free 16 GB Colab T4 GPU with QLoRA
- `load_in_4bit=True` reduces VRAM 4×

## Unsloth Fine-Tuning (Recommended for Low VRAM)

**Install**:
```bash
pip install unsloth
pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo  # update
```

### Dense models:
```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-4B",  # or 8B, 14B, 32B
    max_seq_length=2048,             # supports up to 40960
    load_in_4bit=True,               # QLoRA — reduces VRAM 4×
    load_in_8bit=False,
    full_finetuning=False,           # set True for full fine-tuning
)
```

### MoE models (30B-A3B, 235B-A22B):
```python
from unsloth import FastModel

model, tokenizer = FastModel.from_pretrained(
    model_name="unsloth/Qwen3-30B-A3B",
    max_seq_length=2048,
    load_in_4bit=True,
    load_in_8bit=False,
    full_finetuning=False,  # router-layer fine-tuning disabled by default
)
```

Qwen3-30B-A3B fine-tuning: **17.5 GB VRAM** with Unsloth.

### Add LoRA adapters:
```python
model = FastLanguageModel.get_peft_model(
    model,
    r=16,                    # LoRA rank
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=3407,
)
```

### Key settings:
- `max_seq_length`: Recommended 2048. Qwen3 supports up to 40960.
- `load_in_4bit=True`: 4× VRAM reduction (QLoRA)
- `load_in_8bit=True`: 8-bit training
- `full_finetuning=True`: full parameter update

## RL / GRPO with Unsloth

GRPO (Group Relative Policy Optimization) for reward-based training:

```python
from trl import GRPOTrainer, GRPOConfig

training_args = GRPOConfig(
    output_dir="./qwen3-grpo",
    num_train_epochs=1,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=5e-6,
)
```

Features:
- Proximity-based reward scoring
- Custom GRPO formatting and templates
- Enhanced evaluation with regex matching
- Compatible with Hugging Face Open-R1 math dataset

## LLaMA-Factory Fine-Tuning

```bash
# Install
pip install llamafactory

# SFT with LoRA
llamafactory-cli train \
  --model_name_or_path Qwen/Qwen3-4B \
  --stage sft \
  --do_train \
  --finetuning_type lora \
  --dataset alpaca_en \
  --output_dir ./output
```

## HuggingFace Trainer (Basic SFT)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer

model_name = "Qwen/Qwen3-4B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto")

training_args = TrainingArguments(
    output_dir="./results",
    num_train_epochs=3,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    save_strategy="epoch",
)
```

## Dataset Ratio for Preserving Reasoning

When fine-tuning Qwen3 models that have thinking capabilities:
- **75% reasoning data** (math, logic, STEM CoT examples)
- **25% non-reasoning data** (standard instruction following)

This ratio preserves the model's CoT reasoning while adding new capabilities.

## Colab Notebooks (Unsloth)

| Task | Notebook |
|---|---|
| Qwen3-14B Reasoning + Conversational | `unslothai/notebooks/Qwen3_(14B)-Reasoning-Conversational.ipynb` |
| Qwen3-4B GRPO RL | `unslothai/notebooks/Qwen3_(4B)-GRPO.ipynb` |
| Qwen3-14B Alpaca (base model) | `unslothai/notebooks/Qwen3_(14B)-Alpaca.ipynb` |

## ModelScope Alternative (China / Download Issues)

```python
import os
os.environ["UNSLOTH_USE_MODELSCOPE"] = "1"

from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-4B-Base",
    max_seq_length=2048,
)
```
