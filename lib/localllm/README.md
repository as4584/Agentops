# LocalLLM — Portable Local LLM Client

A standalone Python library for talking to [Ollama](https://ollama.ai). Zero cloud dependency. One dependency (`httpx`).

## Install

```bash
# Option A: Copy the folder into your project
cp -r lib/localllm /path/to/your-project/localllm

# Option B: Install as editable package
cd lib/localllm && pip install -e .

# Option C: pip install from path
pip install ./lib/localllm
```

## Prerequisites

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.2
```

## Quick Start

```python
from localllm import LocalLLM

llm = LocalLLM()  # default: localhost:11434, llama3.2

# --- Async usage ---
response = await llm.chat("Explain Python generators in 2 sentences")

# With system prompt
response = await llm.chat(
    "Write a haiku about coding",
    system="You are a poet. Output only the haiku."
)

# --- Sync usage (no async needed) ---
response = llm.chat_sync("What is recursion?")

# --- Structured JSON ---
data = await llm.chat_json(
    "List 3 programming languages and their strengths",
    schema={"languages": [{"name": "string", "strength": "string"}]}
)
# Returns: {"languages": [{"name": "Python", "strength": "readability"}, ...]}

# --- Embeddings ---
vector = await llm.embed("machine learning is fascinating")

# --- Model management ---
models = await llm.list_models()       # what's installed
await llm.pull_model("mistral-nemo")   # download a model
info = await llm.model_info()          # model details

# --- Health check ---
health = await llm.health()
# {"status": "ready", "model": "llama3.2", "model_available": true, ...}
```

## Configuration

```python
# Custom Ollama server
llm = LocalLLM(base_url="http://gpu-server:11434")

# Different model
llm = LocalLLM(model="mistral-nemo")

# Environment variables (auto-loaded)
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2
# OLLAMA_TIMEOUT=120
```

## Model Recommendations

```python
from localllm.models import recommend_model, MODELS

# Best model for a task within VRAM budget
model = recommend_model("script_writing", max_vram_gb=8)
# → "mistral-nemo"

model = recommend_model("code_generation", max_vram_gb=5)
# → "qwen2.5-coder"

model = recommend_model("embeddings")
# → "nomic-embed-text"

# Browse all profiles
for name, profile in MODELS.items():
    print(f"{name}: {profile.parameters}, {profile.vram_gb}GB VRAM")
```

## Using in Other Projects

### Method 1: Copy the folder
```
your-project/
├── localllm/          ← copy lib/localllm/ here
│   ├── __init__.py
│   ├── client.py
│   └── models.py
├── your_code.py
```

```python
# your_code.py
from localllm import LocalLLM
llm = LocalLLM()
result = llm.chat_sync("Hello!")
```

### Method 2: Symlink (for shared development)
```bash
cd your-other-project
ln -s /path/to/Agentop/lib/localllm localllm
```

### Method 3: pip install
```bash
pip install /path/to/Agentop/lib/localllm
```

### Method 4: PYTHONPATH
```bash
export PYTHONPATH="/path/to/Agentop/lib:$PYTHONPATH"
```

```python
from localllm import LocalLLM
```

## Available Tasks for recommend_model()

| Task | Top Pick | Fallback |
|------|---------|----------|
| `script_writing` | mistral-nemo | llama3.2 |
| `creative_writing` | mistral-nemo | llama3.3 |
| `code_generation` | qwen2.5-coder | deepseek-r1:14b |
| `analysis` | deepseek-r1:14b | phi4 |
| `classification` | llama3.2:1b | gemma2:2b |
| `json_output` | phi4 | mistral-small |
| `embeddings` | nomic-embed-text | mxbai-embed-large |
| `hashtags` | llama3.2 | mistral |
| `content_strategy` | mistral-nemo | deepseek-r1:14b |
