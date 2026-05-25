# epistemic_principles.md
# SOURCE_OF_TRUTH: GOVERNANCE
# Owner: soul_core
# Changes require CHANGE_LOG entry + governance review
# Last reviewed: 2025-01-01

## 1. Purpose

Defines epistemic rules for every Agentop agent.
BaseAgent.initialize() retrieves this document before any action.

If this document is unretrievable, agents MUST return:
  status: BLOCKED
  reason: epistemic_principles_unavailable
  agent_should_proceed: false

## 2. Claim Source Types

| source_type      | Description                                   | Max confidence |
|------------------|-----------------------------------------------|----------------|
| TOOL_OUTPUT      | Direct return from a verified tool call       | 1.0            |
| CORPUS_RETRIEVED | RAG chunk, non-stale                          | 0.85           |
| INSPECTED_FILE   | File read from filesystem at runtime          | 0.95           |
| INFERRED         | Reasoning over 2+ verified claims             | 0.70           |
| PARAMETRIC       | Model weights only — no retrieval or tool     | 0.50 (hard cap)|

Rules:
- PARAMETRIC hard cap: 0.50 enforced in register_claim()
- INFERRED: max 2 inference steps from CORPUS_RETRIEVED
  before re-retrieval is required
- Stale CORPUS_RETRIEVED degrades to INFERRED at 0.60

## 3. Staleness Thresholds

Staleness = source_last_modified > chunk_last_indexed
Read at runtime. Never hardcode in source files.

| scope          | Stale after      |
|----------------|------------------|
| security       | 24 hours         |
| network        | 7 days           |
| code_standards | any commit       |
| governance     | any CHANGE_LOG   |
| cicd           | any pipeline mod |
| remediation    | 14 days          |
| schemas        | any commit       |
| agents         | 7 days           |

Behaviour:
- Stale chunks: flagged in stale_chunks: [chunk_id, ...]
- Stale chunks: NEVER served silently
- Stale chunks: MAY be included with is_stale: true +
  stale_since: <timestamp>
- >50% stale chunks in response:
    majority_stale: true
    agent_should_proceed: false

## 4. Confidence Scoring

confidence = reranker_score_normalised
           × recency_factor
           × scope_match_bonus

reranker_score_normalised = sigmoid(raw_reranker_score)

recency_factor:
  1.0   chunk_age < 50% of threshold
  0.75  chunk_age 50–99% of threshold
  0.0   chunk is stale → triggers staleness flag

scope_match_bonus:
  1.0   exact scope match
  0.85  adjacent scope (see adjacency map)
  0.70  unmatched scope

Scope adjacency map:
  security    ↔ network
  cicd        ↔ code_standards
  remediation ↔ cicd
  agents      ↔ governance

Final confidence clamped to [0.0, 1.0].

## 5. Corpus Gap Protocol

| requesting_agent  | gap_threshold | agent_should_proceed |
|-------------------|---------------|----------------------|
| soul_core         | 0.70          | false                |
| security_agent    | 0.60          | false                |
| devops_agent      | 0.55          | false                |
| self_healer_agent | 0.55          | false                |
| monitor_agent     | 0.50          | false                |
| code_review_agent | 0.50          | false                |
| knowledge_agent   | 0.45          | false                |
| data_agent        | 0.45          | false                |
| it_agent          | 0.45          | false                |
| cs_agent          | 0.40          | false                |
| comms_agent       | 0.40          | false                |

Gap record (written to corpus_gaps.md):
  gap_id:           GAP-<8 char hex>
  timestamp:        ISO-8601 UTC
  requesting_agent: <agent_id>
  query:            <string>
  top_confidence:   <float>
  threshold:        <float>
  delta:            threshold - top_confidence
  resolution:       UNRESOLVED | INDEXED | REJECTED
  reviewed_by:      null until resolved

Immediate soul_core alert: security_agent, devops_agent,
self_healer_agent gaps only.
Agents MUST NOT synthesize when gap fires.

## 6. Session Audit States

CLEAN
  All claims: TOOL_OUTPUT, CORPUS_RETRIEVED (non-stale),
  or INSPECTED_FILE. No PARAMETRIC > 0.30. No gaps.
  No rollbacks.

NEEDS_REVIEW
  Any of:
  - PARAMETRIC claim 0.30–0.50
  - INFERRED chain depth > 1
  - Gap fired, agent_should_proceed was true
    (cs_agent / comms_agent only)
  - verify failed but rollback succeeded

FLAGGED
  Any of:
  - PARAMETRIC claim bypassed 0.50 cap
  - verify failure with no rollback
  - High-stakes agent proceeded through a gap
  - end_session_audit called with missing claim records

FLAGGED → soul_core.flag_agent() immediately
        → session_audit.jsonl entry
        → agent suspended pending human review

## 7. Invariants

INV-01  Every agent retrieves epistemic_principles before
        first action. No exceptions.

INV-02  PARAMETRIC claims capped at 0.50. Raising this cap
        is a FLAGGED violation.

INV-03  Stale chunks never served silently.

INV-04  Corpus gaps block high-stakes agents
        unconditionally. No retry logic bypasses a gap.

INV-05  FLAGGED session audit suspends the agent.
        soul_core cannot auto-resume without a
        human-reviewed resolution entry in corpus_gaps.md.

INV-06  No agent calls an external API for retrieval.
        All retrieval goes through knowledge_agent only.

## CHANGE_LOG

| date       | change                        | reviewed_by |
|------------|-------------------------------|-------------|
| 2025-01-01 | Initial seed — Sprint 4 prep  | soul_core   |
