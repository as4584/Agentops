# Qwen Architecture Reference

source: qwen_docs
topic: architecture
tags: transformer, MoE, attention, architecture, model_size, layers

## Dense Model Architecture

All Qwen3 dense models use the same transformer decoder architecture:

| Model | Layers | Heads (Q/KV) | Tie Embedding |
|---|---|---|---|
| Qwen3-0.6B | 28 | 16 / 8 | Yes |
| Qwen3-1.7B | 28 | 16 / 8 | Yes |
| Qwen3-4B | 36 | 32 / 8 | Yes |
| Qwen3-8B | 36 | 32 / 8 | No |
| Qwen3-14B | 40 | 40 / 8 | No |
| Qwen3-32B | 64 | 64 / 8 | No |

**Architecture components**:
- Grouped Query Attention (GQA): Q heads >> KV heads (e.g., 32 Q / 8 KV for 4B)
- Rotary Position Embedding (RoPE)
- SwiGLU activation
- RMSNorm (pre-normalization)
- Causal (unidirectional) self-attention
- No bias in attention and FFN layers

## MoE Architecture (Mixture of Experts)

| Model | Layers | Heads (Q/KV) | Experts (total/active) |
|---|---|---|---|
| Qwen3-30B-A3B | 48 | 32 / 4 | 128 / 8 |
| Qwen3-235B-A22B | 94 | 64 / 4 | 128 / 8 |

**MoE routing**: Each token activates 8 of 128 experts per FFN layer.
- 30B-A3B: 30B total parameters, only 3B activated per token
- 235B-A22B: 235B total parameters, only 22B activated per token
- Result: MoE has same inference cost as a ~3B or ~22B dense model

## Tokenizer Architecture

- Type: Byte-level BPE (tiktoken-compatible)
- Vocabulary: 151,646 tokens
- No unknown token (all bytes covered)
- Multilingual: 119 languages natively supported

### Language family coverage:
- Indo-European: 60+ languages (English, French, German, Hindi, Russian, Persian, etc.)
- Sino-Tibetan: Simplified Chinese, Traditional Chinese, Cantonese, Burmese
- Afro-Asiatic: 8 Arabic variants, Hebrew, Maltese
- Austronesian: Indonesian, Malay, Tagalog, Javanese, etc.
- Dravidian: Tamil, Telugu, Kannada, Malayalam
- Turkic: Turkish, Kazakh, Uzbek, etc.
- Austroasiatic: Vietnamese, Khmer
- Japanese, Korean, Georgian, Swahili, and more

## Qwen Model Family Overview

### Qwen3 (2025)
- Pre-training: 36T tokens
- Architecture: Transformer decoder, GQA, RoPE, SwiGLU, RMSNorm
- Key innovation: Hybrid thinking mode (same model, two inference modes)
- Open-weight: Apache 2.0

### Qwen2.5 (predecessor)
- Pre-training: 18T tokens
- Context: 128K (instruct), 1M (special variants)
- No hybrid thinking — separate Instruct / Thinking model variants

### Qwen2.5-Coder
- Specialized for code generation
- Available as 0.5B, 1.5B, 3B, 7B, 14B, 32B
- Agentop: `qwen2.5-coder:7b` available locally

## Position Encoding (RoPE) and Long Context

Qwen3 uses **YaRN** (Yet another RoPE eXtension) for extending context beyond pre-trained length.

Context length by model size:
- 0.6B, 1.7B, 4B: 32K tokens (32,768)
- 8B, 14B, 32B, MoE: 128K tokens (131,072)
- Future (Qwen3-2507): 256K+ tokens

## Attention Pattern Details

**GQA (Grouped Query Attention)**:
- Shares KV heads across multiple Q heads
- Example: 32B model = 64 Q heads, 8 KV heads → 8× KV cache compression
- Reduces memory bandwidth for long contexts

**Head dimensions**:
- Qwen3-4B: 36 layers × (32 Q + 8 KV) heads × 128 dim = ~4B parameters
- Optimal for single RTX 3090 inference at Q4 quantization

## Causal Language Model (CLM) Training

Qwen3 trained as a **causal LM** (next-token prediction, left-to-right).

Implications:
- During fine-tuning: compute loss only on response tokens (mask prompt/system tokens)
- Packing multiple examples: use `<|endoftext|>` as separator between packed docs
- No bidirectional attention — do NOT use for embeddings with the generation model

## HuggingFace Model IDs

```
Qwen/Qwen3-0.6B           Qwen/Qwen3-0.6B-Base
Qwen/Qwen3-1.7B           Qwen/Qwen3-1.7B-Base
Qwen/Qwen3-4B             Qwen/Qwen3-4B-Base
Qwen/Qwen3-8B             Qwen/Qwen3-8B-Base
Qwen/Qwen3-14B            Qwen/Qwen3-14B-Base
Qwen/Qwen3-32B            Qwen/Qwen3-32B-Base
Qwen/Qwen3-30B-A3B        Qwen/Qwen3-30B-A3B-Base
Qwen/Qwen3-235B-A22B      Qwen/Qwen3-235B-A22B-Base
```

Ollama identifiers:
```
qwen3:0.6b   qwen3:1.7b   qwen3:4b   qwen3:8b
qwen3:14b    qwen3:32b    qwen3:30b-a3b
```
