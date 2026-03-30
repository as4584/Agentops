# Animation Salvage Lab

A structured workspace for reviewing, sorting, and recycling assets from an AI animation project before a clean restart.

Character documentation and angle reference images already exist and are treated as **locked identity sources** — do not recreate them here, just drop them into the appropriate folders.

---

## Folder Reference

### `01_inbox/`
**Landing zone for everything raw and unsorted.**

| Subfolder | Purpose |
|-----------|---------|
| `raw_videos/` | Drop raw AI-generated clips here before review. |
| `raw_images/` | Drop raw AI-generated stills and frames here before review. |
| `raw_prompts/` | Paste or save any prompts you used, even failed ones. One `.txt` file per prompt or batch. |
| `raw_notes/` | Freeform session notes, observations, timestamps, anything written during generation. |

---

### `02_character_locks/`
**Identity source of truth. Do not modify these files without deliberate intent.**

| Subfolder | Purpose |
|-----------|---------|
| `existing_character_docs/` | Drop in your existing character documentation (bios, descriptions, style guides). |
| `angle_reference_images/` | Drop in your pre-made angle reference images (front, side, 3/4, back). |
| `identity_anchor_images/` | The single "hero" image per character that locks their appearance for new generations. |

---

### `03_review_pipeline/`
**Staging area for assets waiting to be reviewed and sorted.**

| Subfolder | Purpose |
|-----------|---------|
| `videos_to_review/` | Clips pulled from inbox that need a pass/fail/maybe decision. |
| `images_to_review/` | Stills pulled from inbox waiting for the same decision. |
| `prompts_to_extract/` | Prompts that produced interesting results and need to be dissected before sorting. |

---

### `04_sorted_assets/`
**Final sorted output. Assets only land here after a review decision.**

Each bucket (`approved/`, `maybe/`, `rejected/`) contains:
- `stills/` — individual frames or images
- `clips/` — video segments
- `prompts/` — the prompt that generated the asset, saved alongside it

| Bucket | Meaning |
|--------|---------|
| `approved/` | Good enough to use in final output or as generation references. |
| `maybe/` | Useful in part — wrong identity or minor drift but something is salvageable. |
| `rejected/` | Clearly unusable. Kept for failure-pattern analysis, not production. |

---

### `05_analysis/`
**Pattern recognition from what went wrong and what worked.**

| Subfolder | Purpose |
|-----------|---------|
| `failure_patterns/` | Notes and examples of recurring generation failures (identity drift, anatomy issues, etc.). |
| `useful_prompt_fragments/` | Phrases or structures pulled from prompts that produced good results. |
| `motion_notes/` | Observations specific to motion, timing, and clip pacing. |
| `restart_findings/` | Consolidated lessons learned that will feed directly into the restart package. |

---

### `06_restart_package/`
**Clean, curated inputs ready for a new generation run.**

| Subfolder | Purpose |
|-----------|---------|
| `source_images/` | The locked images that will be used as visual input for new generations. |
| `final_prompt_templates/` | Polished, tested prompt templates built from salvage analysis. |
| `negative_prompts/` | Negative prompt lists for suppressing known failure modes. |
| `test_cases/` | Small, defined 3-second test scenarios to validate identity lock before full runs. |

---

### `07_docs/`
**Project documentation for this salvage workspace.**

| File | Purpose |
|------|---------|
| `README.md` | This file. Folder map and purpose guide. |
| `SORTING_GUIDE.md` | Bucket definitions for consistent review decisions. |
| `REVIEW_LOG.md` | Running log of every asset reviewed with decision and reasoning. |
| `RESTART_PLAN.md` | The plan for the next generation run, using locked identity sources. |

---

## Workflow Summary

```
01_inbox → 03_review_pipeline → 04_sorted_assets
                                      ↓
                               05_analysis → 06_restart_package
```

1. Drop raw assets into `01_inbox/`.
2. Move to `03_review_pipeline/` when ready to evaluate.
3. Sort into `04_sorted_assets/` buckets with a log entry in `REVIEW_LOG.md`.
4. Extract learnings into `05_analysis/`.
5. Build `06_restart_package/` from the best-surviving materials.
6. Use the restart package to run clean, anchored 3-second test generations.
