"""
LocalLLM — Portable Local LLM Client Library
=============================================
A standalone, zero-cloud-dependency LLM client that talks to Ollama.

Drop this folder into ANY Python project to get local LLM inference.

Usage:
    from localllm import LocalLLM

    llm = LocalLLM()                            # defaults to localhost:11434
    llm = LocalLLM(model="mistral-nemo")         # pick a model
    llm = LocalLLM(base_url="http://gpu-box:11434")  # remote Ollama

    # Async
    response = await llm.chat("What is Python?")
    response = await llm.chat("Summarize this", system="You are a summarizer.")

    # Sync (blocking wrapper)
    response = llm.chat_sync("What is Python?")

    # Structured output
    data = await llm.chat_json("List 3 colors", schema={"colors": ["string"]})

    # Embeddings
    vector = await llm.embed("some text")

    # Model management
    models = await llm.list_models()
    await llm.pull_model("llama3.2")

Requirements:
    pip install httpx

That's it. One dependency.
"""

from lib.localllm.client import LocalLLM
from lib.localllm.models import ModelProfile, MODELS

__all__ = ["LocalLLM", "ModelProfile", "MODELS"]
__version__ = "1.0.0"
