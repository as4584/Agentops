# Repo Clean Plan — April 2026

> Working doc. Update it as decisions get made. Delete sections once work ships.

---

## Baseline (measured April 9 2026)

| Metric | Current | Target |
|---|---|---|
| mypy errors (`--ignore-missing-imports`) | **0** | 0 |
| Static-analysis (Pylance/editor) errors | **0** (fixed this session) | 0 |
| Test coverage | **72.71 %** | Keep ≥ 58 % |
| Tests passing | **2012 passed, 5 skipped** | All green |
| Orphaned routes | **0** | 0 |
| Skill manifests present | **23** | TBD |
| Invalid agent IDs in live training data | **2** (`ocr_agent`, `nonexistent_agent`) | 0 |
| process_restart cooldown | **none** | confirm payload required |

---

## Decisions Log

| Date | Area | Decision |
|---|---|---|
| 2026-04-09 | 1 — mypy strict | Skip. Already at 0 errors with current config. Strict not worth annotation overhead. |
| 2026-04-09 | 2 — skill manifests | Add `check_orphaned_skills()` warn-only to `pre_push_audit.py`. No deletions. |
| 2026-04-09 | 3 — training drift | `ocr_agent` is real 12th agent (keep). `nonexistent_agent` → `devops_agent`. Live files are throw-away (gitignored). Add `VALID_AGENT_IDS` guard at write time. Add `ocr_agent` to canonical docs. |
| 2026-04-09 | 4 — test coverage | Deferred. 72 % is fine. No CI split changes this sprint. |
| 2026-04-09 | 5 — process_restart | Option C: require `{"confirm": true, "reason": "..."}` payload or tool no-ops with logged rejection. |

---

## Area 1 — mypy strict mode

**Decision: Skip.** Already at 0 errors. `--strict` would require extensive `type: ignore`
stubs for GPU-only third-party imports (`flash_attn`, `trl`) and add annotation overhead
across the full test suite with no runtime safety gain.

Current config (`strict = false`, `check_untyped_defs = true`) covers the real safety surface.

**Status: ✅ No action needed.**

---

## Area 2 — Orphaned routes and stale skill manifests

**Decision: Add `check_orphaned_skills()` warn-only to `pre_push_audit.py`.**
Verifies every `skill.json` references only valid agent IDs from the 12-agent canonical set.
Emits warnings, does NOT block push. No skill deletions — keep all 23 manifests.

**Implementation:** New `check_orphaned_skills()` function in `scripts/pre_push_audit.py`
after `check_orphaned_routes()`. Reads all `backend/skills/*/skill.json`, checks
`allowed_agents` entries against `VALID_AGENT_IDS`.

**Status: 🔲 Pending — `check_orphaned_skills()` in `scripts/pre_push_audit.py`.**

---

## Area 3 — Training data drift

**Decision:**
- `ocr_agent` **is the real 12th agent** (`backend/agents/__init__.py` lines 1631–1769).
  PDF/image extraction via GLM-OCR sidecar (port 5002). Keep it. Add to canonical docs.
- `nonexistent_agent` → replace with `devops_agent` in `_generate_easy_routing()`.
- Existing `live_*.jsonl` files are throw-away (already gitignored). Delete and regenerate
  after the fix.
- Add `VALID_AGENT_IDS` set check in the routing logger at write time — invalid IDs silently
  dropped with a warning log.

**Files to update:**
1. `backend/ml/training_generator.py` — `nonexistent_agent` → `devops_agent`
2. `.github/copilot-instructions.md` — add `ocr_agent`, update tools count 12→13, add `document_ocr`
3. `CLAUDE.md` — add `ocr_agent` row to agent table

**Status: 🔲 Pending — training_generator.py fix + 2 doc updates.**

---

**Status: 🔲 Pending — training_generator.py fix + 2 doc updates.**

---

## Area 4 — Test coverage

**Decision: Deferred.** 72.71 % is well above the 58 % CI floor. No CI tier split or
pytest-xdist changes this sprint.

**Status: ⏸ Deferred.**

---

## Area 5 — process_restart gating (self_healer_agent)

**Decision: Option C — require explicit confirmation payload.**
`process_restart` must receive `{"confirm": true, "reason": "..."}` in kwargs or the tool
no-ops and logs `"process_restart blocked: no confirm payload"`.

- `self_healer_agent` already computes reason strings, so zero friction for legitimate use.
- Stops runaway burst patterns during dev sessions (VS Code reload loop).
- Works in both dev and production — the self-healer simply always provides the payload.

**Implementation:** In `backend/tools/__init__.py` `process_restart()`, add at the top:
```python
if not kwargs.get("confirm") or not kwargs.get("reason"):
    logger.warning("process_restart blocked: no confirm payload")
    return {"success": False, "error": "confirm payload required"}
```

**Status: 🔲 Pending — `backend/tools/__init__.py`.**

---

## Bonus — Ollama model seeding (containerization)

**Decision:** Add `ollama-init` service to `docker-compose.yml` that waits for Ollama to
be ready then pulls `llama3.2` and attempts `lex-v2` (best-effort, logs skip if not in
registry). Enables clean first-run on a new device.

**Note on lex-v2:** Custom model. Not in Ollama public registry. Must be exported from the
training machine (`ollama show lex-v2 --modelfile`) and imported on the target machine
(`ollama create lex-v2 -f Modelfile`). The init sidecar skips it gracefully if absent.

**Status: 🔲 Pending — `docker-compose.yml`.**

---

## Decisions log

| Date | Decision | Who |
|---|---|---|
| 2026-04-09 | Drop frontend-checks CI job (unreliable) | session |
| 2026-04-09 | Fix pre-push audit to follow auth delegation to backend/auth.py | session |
| 2026-04-09 | Remove pixel-agents submodule | session |
| 2026-04-09 | Untrack and gitignore live_*.jsonl, metrics.jsonl, docs/gsd/, soul_core/store.json | session |
| 2026-04-09 | Fix Pylance errors 13 → 0 across 7 files | session |
| 2026-04-09 | Area 1: Skip mypy strict | session |
| 2026-04-09 | Area 2: Add check_orphaned_skills() warn-only | session |
| 2026-04-09 | Area 3: ocr_agent is real 12th agent; nonexistent_agent → devops_agent; add to docs | session |
| 2026-04-09 | Area 4: Deferred | session |
| 2026-04-09 | Area 5: Option C confirm payload for process_restart | session |
