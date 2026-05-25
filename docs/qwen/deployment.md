# Qwen Deployment Guide

source: qwen_docs
topic: deployment
tags: ollama, vllm, sglang, transformers, openai_api, inference

## Local Inference with Ollama (Recommended for Agentop)

```bash
# Run Qwen3 models locally
ollama run qwen3:4b
ollama run qwen3:8b
ollama run qwen3:30b-a3b     # MoE, efficient
ollama run qwen3:14b
ollama run qwen3:32b

# List available models
ollama list
```

**Agentop note**: Default `OLLAMA_MODEL=qwen3:4b` in `.env`. Ollama serializes requests — only one inference at a time per model. Multiple concurrent agent tasks will queue behind each other.

## vLLM Deployment (Production / GPU Server)

Requires `vllm>=0.8.4`.

```bash
# Deploy with thinking/reasoning support
vllm serve Qwen/Qwen3-4B \
  --enable-reasoning \
  --reasoning-parser deepseek_r1

# Without thinking
vllm serve Qwen/Qwen3-4B
```

Creates OpenAI-compatible API at `http://localhost:8000/v1`.

## SGLang Deployment (Production)

Requires `sglang>=0.4.6.post1`.

```bash
python -m sglang.launch_server \
  --model-path Qwen/Qwen3-30B-A3B \
  --reasoning-parser qwen3
```

## Transformers (Local Python)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "Qwen/Qwen3-4B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype="auto",
    device_map="auto",
)

messages = [{"role": "user", "content": "Explain neural networks."}]
text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=True,
)

model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
generated_ids = model.generate(**model_inputs, max_new_tokens=32768)

# Extract output (exclude prompt)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()

# Parse thinking vs final answer
try:
    index = len(output_ids) - output_ids[::-1].index(151668)  # 151668 = </think> token
except ValueError:
    index = 0

thinking = tokenizer.decode(output_ids[:index], skip_special_tokens=True).strip()
answer = tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip()
```

## OpenAI-Compatible API Usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",  # vLLM / SGLang endpoint
    api_key="EMPTY",
)

response = client.chat.completions.create(
    model="Qwen/Qwen3-4B",
    messages=[{"role": "user", "content": "What is quantum entanglement?"}],
    temperature=0.7,
    max_tokens=16384,
)
print(response.choices[0].message.content)
```

## Other Local Options

- **LM Studio**: GUI app, supports GGUF quantized Qwen3
- **llama.cpp**: GGUF inference. `llama-cli --hf-repo Qwen/Qwen3-4B-GGUF`
- **MLX**: Apple Silicon optimized. `mlx_lm.generate --model Qwen/Qwen3-4B`
- **KTransformers**: CPU+GPU hybrid, optimized for MoE models

## Deployment Decision Matrix

| Use Case | Recommended |
|---|---|
| Local dev / Agentop | Ollama |
| Production GPU server | vLLM or SGLang |
| Apple Silicon | MLX |
| Very low VRAM / quantized | llama.cpp + GGUF |
| Agentic framework integration | Qwen-Agent + vLLM |

## Cloud / API Services

- **Alibaba Cloud Model Studio (DashScope)**: Official API, model type `qwen_dashscope`
- **OpenRouter**: Compatible, use `openai` client with OpenRouter base URL
- **Hugging Face Inference**: Available for smaller Qwen3 models
