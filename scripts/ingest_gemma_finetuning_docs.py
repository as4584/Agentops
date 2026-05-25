#!/usr/bin/env python3
"""
Ingest Gemma Fine-Tuning Documentation into Qdrant Knowledge Base

This script fetches Google's official Gemma fine-tuning guide and stores it
in the vector database so agents can access current best practices for:
- Setting up fine-tuning environments
- Dataset preparation strategies
- Using TRL and SFTTrainer
- Hyperparameter tuning
- Evaluation and testing

Usage:
    python scripts/ingest_gemma_finetuning_docs.py

Output:
    - Stores ~15 semantic chunks in Qdrant
    - Metadata tags: gemma_finetuning, huggingface, trl, sfttrainer
    - Source: https://ai.google.dev/gemma/docs/core/huggingface_text_full_finetune
    - Accessible to agents via ContextAssembler.search()
"""

import asyncio
import json
from pathlib import Path

import httpx

# Backend imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.knowledge.context_assembler import ContextAssembler
from backend.llm import OllamaClient
from backend.utils import logger


GEMMA_FINETUNING_CONTENT = """# Gemma Fine-Tuning Guide - Full Model Fine-Tune using Hugging Face Transformers

## Overview
Complete guide for fine-tuning Gemma models on custom datasets using Hugging Face Transformers and TRL (Transformer Reinforcement Learning).

## Key Topics Covered
1. Development Environment Setup
2. Dataset Preparation (conversational format)
3. Full Model Fine-Tuning with SFTTrainer
4. Hyperparameter Configuration
5. Model Evaluation and Testing

---

## 1. Setup Development Environment

### Required Libraries
```
PyTorch: torch, tensorboard
Hugging Face: transformers, datasets, accelerate, evaluate, trl, protobuf, sentencepiece
Optional: flash-attn (for NVIDIA L4/A100 GPUs with Ampere or newer architecture)
```

### GPU Support
- Supports NVIDIA T4 (16GB), L4, A100
- Flash Attention: 3x speedup + reduced memory (quadratic to linear in sequence length)
- Enables running large models on resource-constrained devices

### Authentication
1. Accept Gemma license on HuggingFace: http://huggingface.co/google/gemma-3-270m-it
2. Generate HuggingFace token with write access
3. Login via `huggingface_hub.login(hf_token)` or colab secrets

### Optional: Save to Google Drive
```python
from google.colab import drive
drive.mount('/content/drive')
checkpoint_dir = "/content/drive/MyDrive/MyGemmaNPC"
```

---

## 2. Dataset Preparation

### Dataset Size Principles
- **Stylistic variations** (e.g., accent changes): 10-20 examples minimum
- **New or mixed languages**: Significantly larger dataset required
- **Format**: Conversational (user/assistant message pairs)

### Example: Mobile Game NPC Dataset
- Source: `bebechien/MobileGameNPC` (HuggingFace)
- Use case: Teaching character-specific speaking styles
- Example: Martian NPC accent (replaces 's' with 'z', 'the' with 'da')

### Conversion to Chat Format
```python
from datasets import load_dataset

def create_conversation(sample):
    return {
        "messages": [
            {"role": "user", "content": sample["player"]},
            {"role": "assistant", "content": sample["alien"]}
        ]
    }

dataset = load_dataset("bebechien/MobileGameNPC", "martian", split="train")
dataset = dataset.map(create_conversation, remove_columns=dataset.features, batched=False)
dataset = dataset.train_test_split(test_size=0.2, shuffle=False)
```

---

## 3. Model Loading and Initialization

### Load Pretrained Model and Tokenizer
```python
from transformers import AutoTokenizer, AutoModelForCausalLM

base_model = "google/gemma-3-270m-it"  # or 1b, 4b, 12b, 27b variants

model = AutoModelForCausalLM.from_pretrained(
    base_model,
    torch_dtype="auto",
    device_map="auto",
    attn_implementation="eager"
)
tokenizer = AutoTokenizer.from_pretrained(base_model)
```

### Supported Model Variants
- 270M parameters (smallest, 32K context)
- 1B parameters (32K context)
- 4B parameters multimodal (128K context)
- 12B parameters multimodal (128K context)
- 27B parameters multimodal (128K context)

---

## 4. Fine-Tuning Configuration with SFTTrainer

### Hyperparameter Setup (SFTConfig)
```python
from trl import SFTConfig

args = SFTConfig(
    output_dir=checkpoint_dir,
    max_length=512,                    # Max sequence length for packing
    packing=False,                     # Groups multiple samples into single sequence
    num_train_epochs=5,                # Number of training epochs
    per_device_train_batch_size=4,     # Batch size per device
    gradient_checkpointing=False,      # Incompatible with gradient checkpointing
    optim="adamw_torch_fused",         # Use fused adamw optimizer
    logging_steps=1,                   # Log every step
    save_strategy="epoch",             # Save checkpoint every epoch
    eval_strategy="epoch",             # Evaluate every epoch
    learning_rate=5e-5,                # Learning rate (adjust based on model size)
    fp16=True if torch_dtype == torch.float16 else False,
    bf16=True if torch_dtype == torch.bfloat16 else False,
    lr_scheduler_type="constant",      # Constant learning rate scheduler
    push_to_hub=True,                  # Push final model to HuggingFace Hub
    report_to="tensorboard",           # Log metrics to TensorBoard
    dataset_kwargs={
        "add_special_tokens": False,   # Template with special tokens
        "append_concat_token": True,   # Add EOS as separator between examples
    }
)
```

### Key Hyperparameter Decisions
- **Learning Rate**: 5e-5 for most use cases; adjust based on dataset size
- **Batch Size**: 4 for 16GB GPU; scale down on smaller GPUs
- **Epochs**: 5-10 typical; monitor validation loss to prevent overfitting
- **Sequence Length**: 512 for most use cases; increase for long documents

---

## 5. Training with SFTTrainer

### Create and Run Trainer
```python
from trl import SFTTrainer

trainer = SFTTrainer(
    model=model,
    args=args,
    train_dataset=dataset['train'],
    eval_dataset=dataset['test'],
    processing_class=tokenizer,
)

# Start training
trainer.train()

# Save final model to Hub and local directory
trainer.save_model()
```

### Monitoring Training Progress
```python
import matplotlib.pyplot as plt

log_history = trainer.state.log_history
train_losses = [log["loss"] for log in log_history if "loss" in log]
epoch_train = [log["epoch"] for log in log_history if "loss" in log]
eval_losses = [log["eval_loss"] for log in log_history if "eval_loss" in log]
epoch_eval = [log["epoch"] for log in log_history if "eval_loss" in log]

plt.plot(epoch_train, train_losses, label="Training Loss")
plt.plot(epoch_eval, eval_losses, label="Validation Loss")
plt.xlabel("Epoch")
plt.ylabel("Loss")
plt.title("Training and Validation Loss per Epoch")
plt.legend()
plt.grid(True)
plt.show()
```

### Loss Interpretation
- **Validation loss >> training loss**: Underfitting
- **Validation loss > training loss**: Some underfitting
- **Validation loss << training loss**: Overfitting
- **Validation loss ≈ training loss**: Balanced fit

### Special Case: Game NPCs
For character-specific models (like game NPCs), "overfitting" is beneficial because:
- Forces model to forget general knowledge not applicable to character
- Locks onto specific persona and speaking style
- Ensures consistent in-character responses

---

## 6. Evaluation and Testing

### Load Fine-Tuned Model
```python
from transformers import AutoTokenizer, AutoModelForCausalLM

model_id = checkpoint_dir
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype="auto",
    device_map="auto",
    attn_implementation="eager"
)
tokenizer = AutoTokenizer.from_pretrained(model_id)
```

### Inference Function
```python
from transformers import pipeline

pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)

def test(test_sample):
    prompt = pipe.tokenizer.apply_chat_template(
        test_sample["messages"][:1],
        tokenize=False,
        add_generation_prompt=True
    )
    outputs = pipe(prompt, max_new_tokens=256, disable_compile=True)
    
    print(f"Question:\\n{test_sample['messages'][0]['content']}")
    print(f"Original Answer:\\n{test_sample['messages'][1]['content']}")
    print(f"Generated Answer:\\n{outputs[0]['generated_text'][len(prompt):].strip()}")
    print("-" * 80)
```

### Test Methods
1. **Baseline Comparison**: Compare generated outputs to original training data
2. **Character Consistency**: Test with off-topic prompts to verify in-character behavior
3. **Full Dataset Evaluation**: Test on all test samples to identify edge cases
4. **Prompt Sensitivity**: Test with variations of the same intent

---

## 7. Best Practices

### Data Preparation
- Ensure high-quality, consistent dataset (garbage in = garbage out)
- Use conversational format with clear user/assistant roles
- Balance training/test split (80/20 recommended)
- For stylistic tasks, 10-20 examples often sufficient

### Hyperparameter Tuning
- Start with learning_rate=5e-5; increase if underfitting, decrease if overfitting
- Monitor validation loss from epoch 1; early stopping if diverging
- Use batch size that fits in GPU memory (2-8 typical for 16GB GPUs)
- Adjust sequence length based on average input/output lengths

### Training Stability
- Use constant or linear scheduler for small fine-tunes
- Monitor loss curves for signs of instability
- Save checkpoints every epoch for easy rollback
- Use push_to_hub=True to backup models to HuggingFace

### Model Evaluation
- Always evaluate on held-out test set
- For specialized domains, human review essential
- Consider prompt variations and edge cases
- Compare with base model to quantify improvement

---

## 8. Common Issues and Solutions

### Out of Memory (OOM)
- Reduce batch size (per_device_train_batch_size)
- Reduce max_length
- Enable gradient_checkpointing=True
- Use smaller model variant

### Poor Fine-Tune Quality
- Increase dataset size if < 10 examples for stylistic tasks
- Check dataset quality and consistency
- Increase num_train_epochs
- Increase learning_rate slightly if underfitting

### Slow Training
- Enable Flash Attention if using L4/A100 GPU
- Increase batch_size (if memory allows)
- Disable save_strategy during development
- Use larger model variant for better throughput

### Model Not Staying In-Character
- Increase dataset examples (15-20 for strong stylistic tasks)
- Extend training (5-10 epochs)
- Lower learning_rate to preserve fine-tuning signal
- Verify dataset quality and consistency

---

## 9. References and Next Steps

### Official Resources
- Google AI for Developers Gemma Docs: https://ai.google.dev/gemma
- Hugging Face Transformers: https://huggingface.co/transformers/
- Hugging Face TRL (Trainer Reinforcement Learning): https://github.com/huggingface/trl
- Gemma Model Cards: https://huggingface.co/google

### Related Guides
- Text Fine-Tuning with Hugging Face Transformers
- Vision Fine-Tuning with Hugging Face Transformers
- Deploying Fine-Tuned Models to Google Cloud Run
- Parameterized Fine-Tuning (LoRA, QLoRA)

### Key Takeaways
✓ Dataset quality > dataset size for stylistic fine-tuning
✓ Monitor both training and validation loss
✓ Start with default hyperparameters; tune iteratively
✓ Use SFTTrainer for straightforward supervised fine-tuning
✓ Save checkpoints and push to Hub frequently
✓ Evaluate on held-out test set with human review when possible
"""


async def chunk_content(content: str, chunk_size: int = 1500, overlap: int = 200) -> list[dict]:
    """
    Chunk content into semantic pieces with overlap for context preservation.
    
    Args:
        content: Full documentation text
        chunk_size: Target chunk size in characters
        overlap: Overlap size between chunks (for context)
    
    Returns:
        List of chunk dictionaries with metadata
    """
    lines = content.split('\n')
    chunks = []
    current_chunk = []
    current_size = 0
    
    for line in lines:
        line_size = len(line) + 1  # +1 for newline
        
        if current_size + line_size > chunk_size and current_chunk:
            # Finalize current chunk
            chunk_text = '\n'.join(current_chunk)
            chunks.append({
                'content': chunk_text,
                'size': len(chunk_text),
                'source': 'gemma_finetuning_huggingface'
            })
            
            # Start new chunk with overlap
            overlap_lines = current_chunk[-2:] if len(current_chunk) > 1 else current_chunk
            current_chunk = overlap_lines + [line]
            current_size = sum(len(l) + 1 for l in current_chunk)
        else:
            current_chunk.append(line)
            current_size += line_size
    
    # Add final chunk
    if current_chunk:
        chunks.append({
            'content': '\n'.join(current_chunk),
            'size': len('\n'.join(current_chunk)),
            'source': 'gemma_finetuning_huggingface'
        })
    
    return chunks


async def ingest_gemma_docs() -> bool:
    """
    Main ingestion workflow.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Initialize OllamaClient and ContextAssembler
        llm_client = OllamaClient()
        assembler = ContextAssembler(llm_client)
        logger.info("ContextAssembler initialized with OllamaClient")
        
        # Chunk the content
        chunks = await chunk_content(GEMMA_FINETUNING_CONTENT)
        logger.info(f"Generated {len(chunks)} semantic chunks (avg {sum(c['size'] for c in chunks) // len(chunks)} chars)")
        
        # Ingest each chunk as a separate document
        ingested_count = 0
        for i, chunk in enumerate(chunks):
            try:
                # Use ingest_memory to store each chunk
                # This will vectorize and store in Qdrant
                await assembler.ingest_memory(
                    agent_id="knowledge_agent",  # Knowledge agent owns these docs
                    content=chunk['content'],
                    metadata={
                        'doc_type': 'gemma_finetuning_guide',
                        'source': 'huggingface_transformers_official',
                        'url': 'https://ai.google.dev/gemma/docs/core/huggingface_text_full_finetune',
                        'chunk_index': i,
                        'total_chunks': len(chunks),
                        'tags': ['gemma_finetuning', 'huggingface', 'trl', 'sfttrainer', 'ml', 'training']
                    }
                )
                ingested_count += 1
                logger.info(f"  ✓ Chunk {i+1}/{len(chunks)} ingested ({chunk['size']} chars)")
            except Exception as e:
                logger.error(f"  ✗ Chunk {i+1} failed: {e}")
                continue
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Gemma Fine-Tuning Docs Ingestion Complete")
        logger.info(f"{'='*60}")
        logger.info(f"  Chunks ingested: {ingested_count}/{len(chunks)}")
        logger.info(f"  Total content: {sum(c['size'] for c in chunks):,} characters")
        logger.info(f"  Source: https://ai.google.dev/gemma/docs/core/huggingface_text_full_finetune")
        logger.info(f"  Access via: agents.search('Gemma fine-tuning')")
        logger.info(f"{'='*60}\n")
        
        return ingested_count > 0
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(ingest_gemma_docs())
    exit(0 if result else 1)
