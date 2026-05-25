# Qwen Optimization and Performance Guide

source: qwen_docs
topic: optimization
tags: quantization, thinking_budget, inference_params, memory, VRAM, performance

## Thinking Budget Control

Qwen3 supports **scalable thinking** — allocate more compute to harder problems.

### Per-turn soft switch:
```
User: Solve this integral. /think
Assistant: <think>...</think> {detailed solution}

User: What's 2+2? /no_think
Assistant: 4
```

### Hard budget limit:
```python
# In transformers — limit thinking tokens
text = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True,
    enable_thinking=True,
)
# Set max_new_tokens to control total budget including thinking
output = model.generate(**inputs, max_new_tokens=4096)  # budget = 4096 tokens
```

### Agentop integration note:
`chat_with_schema` in `backend/llm/__init__.py` strips `<think>...</think>` blocks before JSON parsing. Thinking budget still consumed — set `max_new_tokens` appropriately for task complexity.

## Quantization

### 4-bit (QLoRA / load_in_4bit):
- **4× VRAM reduction** vs full precision
- Qwen3-14B: ~8 GB VRAM (down from ~28 GB)
- Minimal accuracy loss for instruction following

### 8-bit (load_in_8bit):
- ~2× VRAM reduction
- Better accuracy than 4-bit for math/reasoning

### GGUF (llama.cpp / Ollama):
- Various quantization levels: Q4_K_M, Q5_K_M, Q8_0, F16
- Q4_K_M: good balance (used by `llama3.2:3b-instruct-q8_0` in Agentop)
- Higher K-quant variants (Q5_K_M) better for reasoning tasks

## Recommended Inference Parameters

### For thinking-enabled models:
```python
{
    "temperature": 0.6,       # Lower temp stabilizes reasoning chains
    "top_p": 0.9,
    "top_k": 20,
    "min_p": 0,
    "max_new_tokens": 32768,  # Allow full thinking budget
}
```

### For non-thinking (fast response):
```python
{
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "min_p": 0,
    "presence_penalty": 1.0,  # Reduce repetition; >2 may cause language mixing
    "max_new_tokens": 16384,
}
```

### For JSON-structured output (Agentop ReAct schema):
```python
{
    "temperature": 0.2,   # Low temperature for reliable JSON formatting
    "top_p": 0.9,
    "max_new_tokens": 2048,
}
```

## VRAM Requirements (Approximate)

| Model | 4-bit (Unsloth) | 8-bit | FP16/BF16 |
|---|---|---|---|
| Qwen3-0.6B | ~0.5 GB | ~0.8 GB | ~1.2 GB |
| Qwen3-1.7B | ~1.5 GB | ~2.5 GB | ~3.5 GB |
| Qwen3-4B | ~3 GB | ~5 GB | ~8 GB |
| Qwen3-8B | ~6 GB | ~10 GB | ~16 GB |
| Qwen3-14B | ~8 GB | ~14 GB | ~28 GB |
| Qwen3-32B | ~20 GB | ~32 GB | ~64 GB |
| Qwen3-30B-A3B | ~17.5 GB | ~26 GB | ~60 GB |
| Qwen3-235B-A22B | ~120 GB | — | ~470 GB |

## Performance Benchmarks

### Qwen3-4B vs larger models:
- Qwen3-4B ≈ Qwen2.5-72B-Instruct (general tasks)
- Qwen3-4B > Qwen2.5-7B on STEM/coding with thinking enabled
- Qwen3-30B-A3B > QwQ-32B (10× fewer active parameters)

### Throughput (approximate, single GPU):
- Ollama (Qwen3-4B, Q4): ~30-50 tokens/s on RTX 3090
- vLLM (Qwen3-4B, BF16): ~80-120 tokens/s on A100
- SGLang: similar to vLLM, better for long-context

## Context Length Optimization

```python
# Sliding window attention for very long contexts
# Qwen3 natively supports:
# - 32K tokens (standard models)
# - 128K tokens (Qwen3-8B, 14B, 32B, MoE models)
# - 262K tokens (Qwen3-2507 series)

# For Ollama — extend context window:
# In Modelfile:
# PARAMETER num_ctx 32768
```

## Presence Penalty Warning

Qwen3 docs warn: presence_penalty values >2.0 may cause **language mixing** (model switches languages mid-output). Keep ≤1.5 for multilingual safety.

## Ollama Concurrency Notes (Agentop-specific)

- Ollama processes one request at a time per model (serialized)
- Multiple agents queuing = cascading timeout risk
- Mitigation: separate embed model (`nomic-embed-text`) from generation model
- Agentop fix: `embed()` in `llm/__init__.py` uses 10s hard timeout to avoid blocking scheduled tasks
