# Sorting Guide

Use this guide every time you make a review decision on an asset. Consistent bucket usage means the `05_analysis/` findings will actually be useful.

---

## Buckets

### `approved`
**Location:** `04_sorted_assets/approved/`

The asset is good enough to use. This means:
- Character identity is correct and stable
- Anatomy is clean (no extra limbs, no melting)
- Motion or composition serves the intended shot
- Could appear in a final cut or be used as a generation reference

Save the matching prompt in `approved/prompts/` with the same filename as the asset.

---

### `maybe`
**Location:** `04_sorted_assets/maybe/`

The asset has salvageable value but is not ready to use as-is. Use this when:
- Identity is close but not quite right (slight drift)
- One part of the frame works but another doesn't
- The motion or timing is interesting even if the character looks off
- The prompt structure seems promising but needs tuning

Add a note to `REVIEW_LOG.md` explaining what specifically is salvageable.

---

### `rejected`
**Location:** `04_sorted_assets/rejected/`

The asset is not usable, but keep it — failed assets are data. Use this when:
- Character identity is clearly wrong
- Anatomy is severely broken
- Motion is unusable
- The output looks nothing like the intent

Move the associated prompt to `rejected/prompts/` so you can analyze what went wrong.

---

### `identity_anchor`
**Location:** `02_character_locks/identity_anchor_images/`

A still image that will be used as the locked visual reference for this character in future generations. Criteria:
- Clean, clear depiction of the character
- Correct proportions and style
- Representative of how the character should look across all shots
- Only one per character (or one per distinct costume/look)

These images do not get deleted. They are the ground truth.

---

### `angle_reference`
**Location:** `02_character_locks/angle_reference_images/`

Images showing the character from specific angles to help the model maintain consistency. Use this bucket for:
- Front-facing reference
- Side/profile reference
- 3/4 view reference
- Back view reference

These are already created. Drop them in and label them clearly (e.g., `CHAR_NAME_front.png`).

---

### `failure_reference`
**Location:** `05_analysis/failure_patterns/`

An asset that clearly illustrates a recurring problem. Not filed by quality level — filed by failure type. Use this for:
- Classic identity drift examples
- Anatomy collapse examples
- Lighting or style bleed examples
- Motion artifacts

Name the file descriptively (e.g., `drift_example_wrong_hair.png`) and add a short `.txt` note alongside it.

---

### `prompt_useful`
**Location:** `05_analysis/useful_prompt_fragments/`

A prompt or prompt fragment that contributed to a good result. Extract it when:
- A specific phrase produced clean, consistent identity
- A structure or ordering worked better than others
- A modifier visibly improved motion or style

Save as a `.txt` file. Add a one-line comment at the top explaining what it did well.

---

### `prompt_confusing`
**Location:** `04_sorted_assets/rejected/prompts/` or `05_analysis/failure_patterns/`

A prompt that produced inconsistent, unexpected, or clearly wrong results. Log it when:
- The same prompt produced wildly different outputs across runs
- An instruction was clearly misunderstood by the model
- A modifier had the opposite of the intended effect

Note what you expected vs. what happened. This is how negative prompts and guardrails get built.

---

## Naming Convention

Consistent filenames make sorting and analysis faster.

```
[CHARACTER]_[SCENE/SHOT]_[VERSION].[ext]
```

Examples:
- `xpel_intro_v01.mp4`
- `xpel_front_anchor.png`
- `drift_wrong_face_v03.png`
- `prompt_clean_motion_fragment.txt`

Keep version numbers. Don't overwrite files — append `_v02`, `_v03`, etc.
