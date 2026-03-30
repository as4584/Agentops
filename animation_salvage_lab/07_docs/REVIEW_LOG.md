# Review Log

Running record of every asset reviewed during the salvage process.

Add a row each time you make a sorting decision. One row per asset.

---

## Log

| Asset Name | Type | Bucket | Reason | Next Action |
|------------|------|--------|--------|-------------|
| _example_xpel_intro_v01.mp4_ | clip | maybe | Motion timing works but face drifts at 1.8s | Extract prompt fragment, note drift trigger |
| _example_xpel_front_v02.png_ | still | approved | Clean identity, correct proportions | Copy to identity_anchor_images |
| _example_run3_wide_shot.mp4_ | clip | rejected | Wrong character entirely, anatomy broken | File in failure_patterns with note |
| | | | | |

---

## Bucket Key

| Bucket | Meaning |
|--------|---------|
| `approved` | Ready to use or reference |
| `maybe` | Partially useful — needs note |
| `rejected` | Unusable — keep for analysis |
| `identity_anchor` | Locked character reference image |
| `angle_reference` | Directional reference for generation |
| `failure_reference` | Sent to failure_patterns for study |
| `prompt_useful` | Fragment sent to useful_prompt_fragments |
| `prompt_confusing` | Filed for negative prompt building |

---

## Type Key

| Code | Meaning |
|------|---------|
| `clip` | Video segment |
| `still` | Single image or frame |
| `prompt` | Text prompt or fragment |
| `doc` | Written note or reference document |

---

## Session Summaries

Use this section to log per-session observations after a review pass.

### Session — [DATE]

- Total assets reviewed:
- Approved:
- Maybe:
- Rejected:
- Key observations:
- Recurring problems:
- Follow-up actions:

---
