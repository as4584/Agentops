# ML WebGen Learning Bible

> Agentop WebGen ML — findings, scoring rubrics, training decisions, and open questions.
> Last updated: 2026-04-06

---

## 1. Mission Statement

We are fine-tuning `Qwen2.5-Coder-3B-Instruct` (QLoRA, RTX 4070 12GB) to generate production-quality HTML/CSS website sections. "Quality" is defined not by length or fluency, but by adherence to five foundational UX laws applied programmatically — no LLM judge needed.

---

## 2. UX Law Scoring Rubric

All generated HTML is scored 0–100 across five axes. These weights were chosen to reflect real user-facing impact.

| Law | Points | What We Measure |
|---|---|---|
| **Jakob's Law** | 20 | Semantic elements: `<nav>`, `<header>`, `<main>`, `<footer>`, `<section>`, `<article>` |
| **Hick's Law** | 20 | CTA count ≤ 3, nav links ≤ 7, form fields ≤ 5 |
| **Law of Proximity** | 15 | Structural grouping via `<section>`, `<article>`, `<div>` with semantic class names |
| **Miller's Law** | 25 | Hierarchy: at least one `<h1>`, supporting `<h2>/<h3>`, body text present |
| **Von Restorff Effect** | 20 | Visual differentiation: `<strong>/<em>`, explicit CTA button or link, highlight elements |

### Score Thresholds

| Score | Grade | Action |
|---|---|---|
| 80–100 | Excellent | Keep in SFT training set |
| 65–79 | Good | Keep, flag for review |
| 50–64 | Acceptable | Keep (current majority — target for improvement) |
| < 50 | Poor | Discard pair from training set |

### Quality Gate for DPO Pairs

A DPO pair is only valid if `abs(chosen_score - rejected_score) >= 10`. Pairs where both outputs are roughly equal quality are noise, not signal.

---

## 3. Training Data Inventory

### 3.1 SFT Dataset: `data/training/webgen_pairs_v1.jsonl`

- **Format**: ShareGPT JSONL — `{conversations: [{from: human, value: ...}, {from: gpt, value: ...}]}`
- **Size**: 100 examples, 329KB
- **Generation model**: `qwen2.5-coder:7b` via Ollama
- **Score distribution (baseline run, 2026-04-05)**:
  - 50-59: 61 examples
  - 60-69: 27 examples
  - 70-79: 12 examples
  - 80+: 0 examples ← target: majority here

### 3.2 DPO Dataset: `data/dpo/webgen_dpo_v1.jsonl`

- **Format**: `{prompt, chosen, rejected, ux_scores, why_chosen_is_better, metadata}`
- **Size**: 40 pairs, 113KB
- **Generator**: `scripts/generate_webgen_dpo.py` (UX scorer gating live as of v1)
- **Gating**: pairs with margin < 10 are skipped

### 3.3 Root Cause Analysis — Why Scores Are Low

**Primary culprit: Jakob's Law (233 violations in 100-example run)**

The model writes `<div role="navigation">` instead of `<nav>`, and `<div class="header-container">` instead of `<header>`. This is a **system prompt problem**, not a model capability problem. The model knows semantic HTML — it just needs to be told to use it.

**Fix**: Explicitly mandate semantic elements in the generation system prompt. See Section 5.

---

## 4. Scoring Implementation

scorer lives at `backend/webgen/agents/ux_scorer.py`.

**Usage:**
```python
from backend.webgen.agents.ux_scorer import score_html, passes_quality_gate, grade_pair

result = score_html(html_string)
# result.total → int (0-100)
# result.jakob → int (0-20)
# result.violations → list[str]

ok = passes_quality_gate(html_string, min_score=55)  # bool

stats = grade_pair(chosen_html, rejected_html)
# stats["chosen_score"], stats["rejected_score"], stats["margin"], stats["is_valid_pair"]
```

**Smoke test baseline:**
- Well-structured hero section with `<nav>`, `<header>`, `<h1>`, `<section>`: **86/100**
- Bad inline-style div dump with no semantics: **48/100**
- Pair margin: **38** — valid DPO pair

---

## 5. System Prompt Engineering

### Current System Prompt (flawed)

Produces valid HTML but uses `<div>` extensively for navigation and layout regions.

### Fixed System Prompt Mandate (to implement)

Add to ALL generation prompts for WebGen:

```
STRUCTURE RULES (mandatory, not optional):
- Use <nav> for ALL navigation menus. NEVER use <div> as a navigation container.
- Use <header> for the page/section header. NEVER use <div class="header-*"> as a substitute.
- Use <main> to wrap primary content.
- Use <footer> for footer regions.
- Use <section> for distinct content areas. Each section MUST have an accessible heading.
- Use <article> for self-contained content blocks.
- Use <h1> exactly once per page. Use <h2>/<h3> for subsections.
```

Files to update:
- `scripts/generate_webgen_dpo.py` → `SYSTEM_GOOD` constant
- `backend/webgen/agents/page_generator.py` → agent system prompt

### Expected Impact

Moving from 61% at 50-59 → majority at 65-75. The semantic structure alone is worth 20 Jakob points.

---

## 6. Orchestrator Retry Pattern

When a section fails the UX quality gate, the orchestrator retries with explicit violation feedback rather than hoping the model self-corrects.

```python
# backend/webgen/pipeline.py → generate_section_with_retry()
attempt 1: temperature=0.6
    → score < min_ux_score?
attempt 2: temperature=0.4 + feedback prompt:
    "PREVIOUS ATTEMPT SCORED {n}/100. FIX THESE VIOLATIONS:
    - jakob: no <nav> found — wrap navigation in <nav>
    - miller: missing h1 — add a primary heading"
    → keep whichever attempt scored higher
```

**Why this works**: Named violations are actionable. "Score too low" is not.

---

## 7. Data Quality Principles

### The Length Trap

Do not use response length as a quality proxy. A DPO pair where:
- chosen = 1,369 chars
- rejected = 403 chars

…teaches the model "longer = better", not "structured = better." The UX scorer breaks this by grading structure independently of length.

### Synthetic vs. Real Data

All current training data is synthetic (same Qwen architecture generates both teacher and student). This is fine for phase 1 but introduces a ceiling. Phase 2 should include:

1. **Real Tailwind HTML** from GitHub (landing pages, component libraries)
2. **Human-written examples** from the `clients/` directory if available
3. **Filtered open-source HTML** from Common Crawl (semantic elements present, no inline scripts)

**Target ratio**: 70% synthetic / 30% real-world by the time we run fine-tune.

### DPO Pair Validity Checklist

Before a pair enters `data/dpo/`, it must:
- [ ] Pass `grade_pair()` with `is_valid_pair: True` (margin ≥ 10)
- [ ] Chosen score ≥ 50
- [ ] Rejected score < chosen score (obvious but worth stating)
- [ ] Neither file is empty or < 200 chars
- [ ] `why_chosen_is_better` cites actual UX scores, not vague prose

---

## 8. Tone Vector System (Planned)

Current `ClientBrief.tone` is a single string (e.g., "professional"). This is insufficient for nuanced output.

**Proposed 5-axis tone vector:**

| Axis | Range | Description |
|---|---|---|
| `energy` | 0–1 | 0 = calm/zen, 1 = urgent/electric |
| `formality` | 0–1 | 0 = casual/conversational, 1 = enterprise/legal |
| `trust` | 0–1 | 0 = edgy/disruptive, 1 = authority/established |
| `era` | 0–1 | 0 = timeless/minimal, 1 = cutting-edge/futuristic |
| `density` | 0–1 | 0 = airy/whitespace, 1 = information-dense |

**Example mappings:**
- Startup SaaS: `{energy: 0.8, formality: 0.3, trust: 0.5, era: 0.9, density: 0.4}`
- Law firm: `{energy: 0.2, formality: 0.9, trust: 0.9, era: 0.2, density: 0.6}`
- Portfolio: `{energy: 0.6, formality: 0.4, trust: 0.7, era: 0.7, density: 0.3}`

**Implementation path**: extend `ClientBrief` in `backend/webgen/`, update generation prompts to translate tone vector to descriptive instructions, include tone vector in DPO pairs so the model learns tone-to-HTML mapping.

---

## 9. Fine-Tuning Plan

### Hardware

- GPU: RTX 4070 (12GB VRAM)
- Training framework: HuggingFace `trl` + `peft` (QLoRA)
- Base model: `Qwen2.5-Coder-3B-Instruct`
- Precision: `bfloat16`, `qlora_4bit=True`

### Phase 1 Targets (before running fine-tune)

| Metric | Current | Target |
|---|---|---|
| SFT avg UX score | ~58 | ≥ 65 |
| DPO pair margin (avg) | ? | ≥ 20 |
| SFT examples | 100 | 500 |
| DPO pairs | 40 | 200 |
| 80+ scoring SFT examples | 0% | ≥ 20% |

### Training Config (planned)

```python
# lora_config
r=16, lora_alpha=32, lora_dropout=0.05,
target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]

# sft_config
num_train_epochs=3, per_device_train_batch_size=4,
gradient_accumulation_steps=4, lr=2e-4,
warmup_ratio=0.05, lr_scheduler_type="cosine"
```

### Evaluation

After each checkpoint, run `scripts/filter_sft_by_ux.py` on held-out 20 examples and track score distribution shift. If 80+ examples are not increasing, the system prompt needs adjustment.

---

## 10. Knowledge Base

All documentation in `docs/` is indexed into Qdrant (collection: `knowledge_agent`) via `scripts/seed_knowledge_base.py`. The `knowledge_agent` can answer natural language questions against this corpus.

**To reseed after adding docs:**
```bash
.venv/bin/python3.12 scripts/seed_knowledge_base.py \
  --query "UX law scoring weights for DPO"
```

**Embedding model**: `nomic-embed-text` (768-dim, via Ollama)
**Vector store**: Qdrant at `localhost:6333`

---

## 11. Open Questions

- [ ] **Tone conditioning**: Can a 3B model reliably follow a 5-axis tone vector? Needs ablation.
- [ ] **Alpine.js**: Should SFT data include reactive components or stay pure HTML? Alpine.js is 4KB, adds interactivity without a build step — worth exploring for hero sections.
- [ ] **Multi-section coherence**: Current pipeline generates sections independently. Does the fine-tuned model lose visual coherence across sections? Add a coherence score to QA.
- [ ] **Rejected pair construction**: Currently rejected = low-UX alternate generation. Should we also include "wrong tone" responses as rejected pairs?
- [ ] **VoiceAgent + AvatarVideoAgent**: Both are stubs. If we want the content pipeline to run end-to-end, these need real providers.

---

## 12. Changelog

| Date | Change |
|---|---|
| 2026-04-05 | `ux_scorer.py` built and smoke-tested |
| 2026-04-05 | DPO generator wired to UX scorer (margin gate) |
| 2026-04-05 | QA agent wired to UX scorer (per-page scoring) |
| 2026-04-05 | Pipeline `generate_section_with_retry()` added |
| 2026-04-05 | `filter_sft_by_ux.py` run on 100 examples — 0% at 80+ |
| 2026-04-06 | `seed_knowledge_base.py` written |
| 2026-04-06 | This document created |
