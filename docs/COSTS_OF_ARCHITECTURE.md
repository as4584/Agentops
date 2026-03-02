# Costs of Architecture

> Token economics, model routing, and per-site cost analysis for the Agentop hybrid LLM system.

**Last updated:** 2025-07-14  
**Version:** 1.0.0

---

## 1. Architecture Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **local_only** | All inference via Ollama (llama3.2) | Development, zero-cost iteration |
| **hybrid** | Local for copy/simple tasks, cloud for design/architecture | Production — best cost/quality ratio |
| **cloud_only** | All inference via OpenRouter | Maximum quality, higher cost |

---

## 2. Model Registry & Pricing

### Cloud Models (via OpenRouter)

| Model | Provider | Input $/1M tokens | Output $/1M tokens | Best For |
|-------|----------|-------------------|---------------------|----------|
| **moonshotai/kimi-k2** | Moonshot | $0.60 | $0.60 | Design systems, architecture, complex reasoning |
| **moonshotai/kimi-k2:thinking** | Moonshot | $0.60 | $2.00 | Deep architecture analysis, multi-step planning |
| **openai/gpt-4o** | OpenAI | $2.50 | $10.00 | Benchmark comparison, fallback |
| **anthropic/claude-sonnet-4** | Anthropic | $3.00 | $15.00 | Code generation, nuanced writing |
| **deepseek/deepseek-chat-v3-0324** | DeepSeek | $0.27 | $1.10 | Budget reasoning, bulk copy |
| **google/gemini-2.5-flash** | Google | $0.15 | $0.60 | Fast iteration, SEO metadata |

### Local Models (via Ollama — $0.00)

| Model | Parameters | VRAM | Best For |
|-------|-----------|------|----------|
| **llama3.2** | 3B | ~2GB | Copy writing, quick iteration |
| **llama3.2:1b** | 1B | ~1GB | Ultra-fast drafts |
| **codellama:13b** | 13B | ~8GB | Code-heavy generation |
| **mistral:7b** | 7B | ~4GB | General purpose |

---

## 3. Per-Site Cost Breakdown (WebGen V2)

A typical 6-page premium website consumes approximately:

| Pipeline Stage | Input Tokens | Output Tokens | Kimi K2 Cost | GPT-4o Cost |
|----------------|-------------|---------------|--------------|-------------|
| Design System Generation | ~2,000 | ~3,000 | $0.003 | $0.035 |
| Site Architecture | ~1,500 | ~2,000 | $0.002 | $0.024 |
| Copy (6 pages × ~800 tok) | ~3,000 | ~4,800 | $0.005 | $0.056 |
| SEO/AEO Schemas | ~1,000 | ~2,000 | $0.002 | $0.023 |
| QA Review | ~4,000 | ~1,000 | $0.003 | $0.020 |
| **TOTAL** | **~11,500** | **~12,800** | **$0.015** | **$0.158** |

### Hybrid Mode (Recommended)

In hybrid mode, local handles copy and SEO; cloud handles design and architecture:

| Stage | Model | Cost |
|-------|-------|------|
| Design System | Kimi K2 (cloud) | $0.003 |
| Site Architecture | Kimi K2 (cloud) | $0.002 |
| Copy Writing | llama3.2 (local) | $0.000 |
| SEO/AEO | llama3.2 (local) | $0.000 |
| QA Review | Kimi K2 (cloud) | $0.003 |
| **TOTAL** | **hybrid** | **~$0.008** |

---

## 4. Volume Projections

| Volume | local_only | hybrid (Kimi K2) | cloud_only (Kimi K2) | cloud_only (GPT-4o) |
|--------|-----------|-------------------|----------------------|---------------------|
| 1 site | $0.00 | $0.008 | $0.015 | $0.158 |
| 10 sites | $0.00 | $0.08 | $0.15 | $1.58 |
| 100 sites | $0.00 | $0.80 | $1.50 | $15.80 |
| 1,000 sites | $0.00 | $8.00 | $15.00 | $158.00 |
| 10,000 sites | $0.00 | $80.00 | $150.00 | $1,580.00 |

---

## 5. Cost Comparison: Kimi K2 vs GPT-4o

| Metric | Kimi K2 | GPT-4o | Savings |
|--------|---------|--------|---------|
| Input price/1M | $0.60 | $2.50 | **76% cheaper** |
| Output price/1M | $0.60 | $10.00 | **94% cheaper** |
| Per-site (cloud) | $0.015 | $0.158 | **10.5x cheaper** |
| Per-site (hybrid) | $0.008 | n/a | **20x cheaper vs GPT-4o cloud** |
| 1K sites | $15 | $158 | **$143 saved** |

Kimi K2 is a 1-trillion parameter Mixture-of-Experts model with 32B active parameters per token. It benchmarks competitively with GPT-4o on code, math, and reasoning at a fraction of the cost.

---

## 6. Token Efficiency Strategy

### The 80/20 Rule
- **80% of tokens** are copy, metadata, and boilerplate → handled locally for $0
- **20% of tokens** are design decisions and architecture → routed to cloud for quality

### Compression Techniques
1. **System prompt caching** — OpenRouter supports prompt caching; reuse design system context across pages
2. **Named concepts** — "Bainbridge-tier design" activates more knowledge in 3 tokens than describing it in 30
3. **Template injection** — Don't generate CSS from scratch; inject the design system as context, generate variations
4. **Batch operations** — Generate all 6 page copies in one call with structured JSON output

### Context Window Budget

```
┌─────────────────────────────────────────────────┐
│ Context Window (128K for Kimi K2)               │
├─────────────────────────────────────────────────┤
│ System Prompt     │  ~500 tokens  │  0.4%       │
│ Design System     │  ~2,000 tokens │  1.6%      │
│ Template Context  │  ~1,500 tokens │  1.2%      │
│ User Brief        │  ~500 tokens  │  0.4%       │
│ ─────────────────────────────────────────────── │
│ Available for     │  ~123,500 tok │  96.4%      │
│ output + history  │               │             │
└─────────────────────────────────────────────────┘
```

---

## 7. Break-Even Analysis

### Cloud vs Self-Hosted GPU

| Setup | Monthly Fixed Cost | Per-Site Marginal | Break-Even vs Hybrid |
|-------|--------------------|-------------------|----------------------|
| Hybrid (Ollama + OpenRouter) | $0 (electricity only) | $0.008 | — |
| A100 80GB rental (RunPod) | ~$250/month | $0.00 | 31,250 sites/month |
| RTX 4090 local | ~$2,000 one-time | $0.00 | 250,000 sites cumulative |

**Verdict:** Hybrid mode is optimal until you exceed ~30K sites/month. Below that volume, paying per-token via OpenRouter is cheaper than renting GPU compute.

---

## 8. Cost Monitoring

The `LLMRouter` tracks costs automatically:

```python
from lib.localllm.router import LLMRouter

router = LLMRouter()
stats = router.get_stats()

# Returns:
# {
#     "total_requests": 142,
#     "local_requests": 98,
#     "cloud_requests": 44,
#     "estimated_cost_usd": 0.34,
#     "tokens_in": 48200,
#     "tokens_out": 71500,
#     "cost_per_request_avg": 0.0024,
# }
```

---

## 9. Governance

- **INV-13**: All cloud LLM calls MUST route through `LLMRouter` — no direct OpenRouter calls from agents.
- **INV-14**: API keys MUST live in `.env` with `chmod 600` — never committed to git.
- Cost tracking data persists in `backend/memory/shared/llm_costs.json`.
- Monthly cost alerts trigger at $10, $50, $100 thresholds via the Monitor Agent.

---

*This document is maintained by the Agentop governance framework. See [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md) for the canonical architecture reference.*
