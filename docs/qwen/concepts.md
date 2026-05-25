# Qwen Model Concepts

source: qwen_docs
topic: concepts
tags: architecture, model_types, tokenization, chat_template, thinking_mode

## What is Qwen

Qwen (通义千问) is Alibaba's series of large language models and multimodal models. Pre-trained on large-scale multilingual and multimodal data, then post-trained to align with human preferences. Includes both proprietary and open-weight versions. Open-weight models are released under Apache 2.0.

## Model Types

**Dense models**: Standard transformer architecture. Total parameters = activated parameters.
- Qwen3-0.6B, 1.7B, 4B, 8B, 14B, 32B

**MoE (Mixture-of-Experts)**: Only a fraction of parameters activated per token. Notation: `30B-A3B` = 30B total, 3B activated.
- Qwen3-30B-A3B: 17.5 GB VRAM for fine-tuning with Unsloth
- Qwen3-235B-A22B: 235B total, 22B activated

## Naming Scheme (Qwen3+)

Format: `Qwen3[-size][-type][-date]`

- `-Instruct`: instruction-following, chat template aware, used for tasks and fine-tuning
- `-Thinking`: chain-of-thought (CoT) reasoning model
- `-Base`: pre-trained only, no chat template, used for further fine-tuning
- No type suffix: hybrid thinking model (both modes)

## Tokenization

- Method: Byte-level BPE (Byte Pair Encoding)
- Vocabulary size: 151,646 tokens (no unknown tokens)
- ~1 token = 3-4 English characters, ~1.5-1.8 Chinese characters

### Control Tokens

| Token | ID | Purpose |
|---|---|---|
| `<\|endoftext\|>` | eod | End of document (between packed docs in training) |
| `<\|im_start\|>` | bot | Start of each conversation turn |
| `<\|im_end\|>` | eot | End of each conversation turn |
| 151668 | </think> | End of thinking block |
| 151645 | <\|im_end\|> | End of message |

**Important**: Do NOT set bos_token to `<|im_start|>` — causes double bot tokens in fine-tuning.

## Chat Template (ChatML)

```
<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_message}<|im_end|>
<|im_start|>assistant
{response}<|im_end|>
```

Qwen3 does NOT use a default system message (unlike Qwen2.5). Must be added explicitly.

## Thinking Mode (Qwen3)

Qwen3 supports hybrid thinking — same model, two modes controlled at inference time.

### Enable thinking (default):
```python
text = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True,
    enable_thinking=True
)
```

### Disable thinking:
```python
text = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True,
    enable_thinking=False
)
```

### Soft switch (per-turn):
- Append `/think` to user message to enable thinking for that turn
- Append `/no_think` to disable for that turn

### Output format when thinking:
```
<|im_start|>assistant
<think>
{chain-of-thought reasoning}
</think>

{final answer}
```

**Parsing thinking content** (token IDs):
```python
index = len(output_ids) - output_ids[::-1].index(151668)  # 151668 = </think>
thinking_content = tokenizer.decode(output_ids[:index], skip_special_tokens=True)
content = tokenizer.decode(output_ids[index:], skip_special_tokens=True)
```

## Context Length

| Model | Pre-training length | Max assistant output |
|---|---|---|
| Qwen3 (base) | 32,768 tokens | 38,912 (thinking) / 16,384 (non-thinking) |
| Qwen3-2507 | 262,144 tokens | 81,920 (thinking) / 16,384 (instruct) |

## Tool Calling Template

```
<|im_start|>system
{tools JSON schema in <tools></tools> tags}<|im_end|>
<|im_start|>user
{user_message}<|im_end|>
<|im_start|>assistant
<tool_call>
{"name": "function_name", "arguments": {...}}
</tool_call><|im_end|>
<|im_start|>user
<tool_response>
{result}
</tool_response><|im_end|>
<|im_start|>assistant
{final answer}<|im_end|>
```

Arguments field must be type `object`, not `string`. Parallel and multi-turn tool calling supported.

## Recommended Inference Parameters (Qwen3-Instruct-2507)

- temperature: 0.7
- top_p: 0.8
- top_k: 20
- min_p: 0
- presence_penalty: 0–2 (reduces repetition; higher may cause language mixing)
- max_tokens: 16,384
