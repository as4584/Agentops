# Memory Source-of-Truth Boundary
_Last updated: 2026-04-04_

This document defines where each kind of data lives. There must be exactly one owner per data type.

---

## Two stores, two purposes

| Store | Class | Path | Access pattern |
|---|---|---|---|
| **MemoryStore** (JSON) | `backend/memory/__init__.py` | `data/agents/<namespace>.json` | Exact key → value lookup |
| **ContextAssembler** (Qdrant) | `backend/knowledge/context_assembler.py` | Qdrant collections, agent-namespaced | Semantic similarity search over embedded text |

---

## What goes in MemoryStore (JSON)

Anything that needs **deterministic, exact retrieval by key**:

- Conversation metadata: `total_actions`, `last_active`, `status`
- Structured agent state: flags, counters, config overrides
- Audit records: timestamps, tool call counts, risk levels
- Intermediate task state for GSD tasks
- Any value you would look up with `memory_store.read(namespace, "some_key")`

**Rule:** If you need `memory_store.read(ns, key)` — it belongs in JSON MemoryStore.

---

## What goes in Qdrant (ContextAssembler)

Anything where you need **"find me contextually related past data"**:

- Conversation summaries (written by `process_message_v2` observations)
- Document chunks from ingested governance docs, knowledge base
- Observation histories when an agent needs cross-session recall
- Semantic Q&A pairs seeded by the knowledge agent

**Rule:** If you need `assembler.retrieve(query, agent_id)` — it belongs in Qdrant.

---

## Dual-write in process_message_v2

`process_message_v2` writes to **both** at the end of each message:

```python
# 1. JSON — metadata record for key-value lookup
await memory_store.write_async(ns, conversation_key, {"response": ..., "total_actions": ...})

# 2. Qdrant — semantic embeddings for future RAG retrieval
#    Only when observations exist (tool-call turns have richer context to embed)
if observations:
    await assembler.ingest_memory(agent_id, conversation_text, metadata={"type": "conversation"})
```

---

## Boundary invariants

1. **Never put large blobs in JSON MemoryStore.** It is not a document store. Max value ≈ 10 KB.
2. **Never do exact key lookup against Qdrant.** It is not a KV store.
3. **MemoryStore is the authority for agent operational state.** Qdrant holds embeddings, not state.
4. **Qdrant content is lossy.** Scores fluctuate. Never use Qdrant hits to make policy decisions — only for assembling soft context hints.
5. **Fallback order:** Qdrant → JSON KnowledgeVectorStore (`_fallback_retrieve`) → empty string. Never raise into the agent loop.

---

## Operational notes

- **Qdrant down?** Server logs a WARNING at startup (`ContextAssembler.health_check()`). Agents degrade gracefully via `_fallback_retrieve`. No data is lost — JSON MemoryStore is always written.
- **Qdrant in-memory:** Set `QDRANT_IN_MEMORY=true` in `.env` for tests or ephemeral dev runs. Data is lost on restart.
- **Collection naming:** Each agent gets its own Qdrant collection named after its `agent_id`. Global collections `["docs", "knowledge_agent"]` are searched on every query.
- **Embedding dimension:** Must match `nomic-embed-text` output = 768. Controlled by `QDRANT_DEFAULT_DIM`. Changing it requires recreating all collections.
