# Restart Plan

## Status

Character documentation is complete.
Angle reference images have been created.
These are the **locked identity sources** for all future generation work.

Do not regenerate character documentation. Do not replace the angle references unless a deliberate identity decision has been made and logged.

---

## What "Locked Identity" Means Here

The character docs and angle reference images in `02_character_locks/` define how each character looks, moves, and presents. Every new generation attempt starts from those files — not from memory, not from a fresh prompt, and not by eyeballing previous outputs.

If the model drifts from the locked identity, that is a failure to be logged — not a design decision to accept.

---

## Next Step: 3-Second Identity Tests

Before running any full shot or sequence, run short 3-second clips using only the locked source images as visual input.

The purpose of these tests is to confirm that:
1. The model can hold the character's identity across the full 3 seconds
2. No drift occurs in the face, proportions, or style
3. The motion is clean and plausible (no anatomy collapse, no flickering)

If a 3-second test fails, do not scale up. Fix the prompt, adjust the negative prompts, or change the source image before trying again.

---

## Test Case Structure

Each test case lives in `06_restart_package/test_cases/` and contains:

```
test_cases/
  [CHARACTER]_[SHOT_DESCRIPTION]_[VERSION]/
    source_image.png       ← copied from identity_anchor_images
    prompt.txt             ← exact prompt used
    negative_prompt.txt    ← negative prompt used
    result.mp4             ← output clip
    verdict.txt            ← PASS / FAIL / MAYBE + one-line reason
```

Keep every test case, including failures. They are the difference between repeating mistakes and building on what works.

---

## Generation Inputs Checklist

Before submitting any generation job, confirm:

- [ ] Source image comes from `02_character_locks/identity_anchor_images/` or `06_restart_package/source_images/`
- [ ] Prompt was built from a template in `06_restart_package/final_prompt_templates/`
- [ ] Negative prompt is loaded from `06_restart_package/negative_prompts/`
- [ ] Shot duration is 3 seconds for test cases (scale up only after passing)
- [ ] Test case folder has been created before the job is submitted
- [ ] Verdict will be logged in `REVIEW_LOG.md` after review

---

## Escalation Path

```
3s test → PASS → run full shot
3s test → MAYBE → adjust prompt, retest before scaling
3s test → FAIL → log failure pattern, fix source or prompt, retest
```

Do not move to full shots until at least two consecutive 3-second PASS results with the same inputs.

---

## Known Failure Modes (from Salvage Analysis)

_Fill this in as patterns emerge from `05_analysis/failure_patterns/`._

| Failure Type | Trigger (if known) | Current Fix |
|---|---|---|
| Identity drift | | |
| Anatomy collapse | | |
| Style bleed | | |
| Motion artifact | | |

---

## Restart Package Completion Criteria

The restart package in `06_restart_package/` is ready when:

- [ ] At least one locked identity anchor exists per character
- [ ] At least one working prompt template has passed a 3-second test
- [ ] Negative prompt list covers all known failure modes from `05_analysis/`
- [ ] At least two passing test cases are documented

Once these criteria are met, full shot production can begin.
