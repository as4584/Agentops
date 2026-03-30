# ProBodyForLife — VideoGenerator System Policy

> **This document is law. Every script, every generation, every edit must comply.
> If you are an AI assistant working in this codebase, read this before touching anything.**

---

## What This System Is

A complete video ad generation pipeline for ProBodyForLife. It takes a product image,
researches the product, locks character identities, generates consistent frames, animates
them with cinematic direction, adds voice, syncs lips, and assembles a final video.

Every layer is independent. Every layer reads from locked config. Nothing is hardcoded.
Nothing is improvised. Nothing is invented.

---

## The Non-Negotiable Rules

### Rule 1 — The Vault Is Read-Only To Everyone Except vault_manager.py

`VideoGenerator/` is the single source of truth. It contains locked character definitions,
style definitions, background definitions, and voice settings.

**You may NOT:**
- Edit any `.json` file in `VideoGenerator/` directly
- Change a voice ID anywhere except `VideoGenerator/voices/[character]/voice.json`
- Change a character description anywhere except `VideoGenerator/characters/[name]/profile.json`
- Hardcode any prompt text in any script

**You MUST:**
- Use `vault_manager.py` to make any changes to `VideoGenerator/`
- Read all prompts, styles, voices from their respective JSON files at runtime

---

### Rule 2 — Characters Are Named, Not Described

Our characters have names. Use them.

| Internal Name | Who They Are |
|---|---|
| `MrWilly` | The bald muscular Latino guy in the white MHP jersey #97 |
| `Xpel` | The XPEL Diuretic box character with cartoon eyes and arms |

When referencing a character in code, scene blueprints, or prompts, always use the name.
The description is loaded from `VideoGenerator/characters/[name]/profile.json` automatically.

---

### Rule 3 — Multi-Anchor Frame Generation Only

Every frame generation MUST use multiple anchor images to prevent character drift.

**Minimum anchors required:**
1. `VideoGenerator/characters/[name]/front.png`
2. `VideoGenerator/characters/[name]/side_left.png`
3. Closest approved pose from `VideoGenerator/characters/[name]/approved_poses/`

**Single image generation is banned.** If you only have one anchor, add more images to the
vault before generating.

The drift score check is not optional. Every generated frame is automatically compared
to `front.png` using image similarity. Frames scoring below `drift_threshold` (0.85) are
auto-rejected before human review.

---

### Rule 4 — Approval Gates Are Mandatory

Nothing moves to the next layer without approval.

| Layer | Gate |
|---|---|
| Frame Generator output | Must be approved in `frames/[campaign]/approved/` before animation runs |
| Animation Engine output | Review animated clips before lipsync runs |
| Final Assembly output | Final video reviewed before delivery |

The approval gate is not a formality. It is the quality control checkpoint for each layer.
Unapproved files stay in `pending/`. The word `approved` in a file path means a human
signed off.

---

### Rule 5 — Scripts Are Built From Research Truth

No dialogue line in any scene blueprint may contain a claim that is not supported by
`ProductResearch/research/[product]_research.json`.

**Before writing any script:**
1. Run `product_research.py` on the product image
2. Approve the research JSON
3. Write scene blueprints using only `talking_points` from the research JSON

This means no invented ingredient claims, no made-up statistics, no fabricated benefits.
Everything said in the ad is grounded in what the product actually contains and does.

---

### Rule 6 — Kling Gets Director-Level Instructions

Kling prompts are built in this exact order, every time:

```
1. Style prefix        (from VideoGenerator/styles/[style]/style.json)
2. Character           (from VideoGenerator/characters/[name]/profile.json)
3. Background          (from VideoGenerator/backgrounds/[bg]/background.json)
4. CAMERA: [exact camera movement — start, movement, end, speed]
5. CHARACTER MOTION: [exactly what body parts move and how]
6. DO NOT MOVE: [explicit list of what stays static]
7. Kling settings     (from scenes/[campaign]/scene_XX.json kling_settings)
```

Vague prompts like "animate this character" are banned. Every motion is described with
the precision of a camera operator briefing.

---

### Rule 7 — Seeds Are Locked Per Scene

Every scene blueprint contains a `kling_settings.seed` value. This seed must be used
for every generation of that scene. This makes animations reproducible — if you need to
regenerate scene 3, you get the same motion every time, not a random result.

Seeds follow this convention: `1001` = scene 01, `1002` = scene 02, etc.

---

### Rule 8 — Audio Flows Through Three Layers

Voice audio is never used raw. It must pass through all three layers before assembly.

| Layer | Input | Output | Where it goes |
|---|---|---|---|
| 1 — Generation | ElevenLabs API | raw MP3 | `audio/[campaign]/raw/` |
| 2 — Enhancement | raw MP3 | cleaned MP3 | `audio/[campaign]/enhanced/` |
| 3 — Mix | enhanced MP3 + music + sfx | final mix | `audio/[campaign]/mixed/` |

- **Lipsync uses Layer 2 (enhanced)** — clean voice signal, no music bleed
- **Assembly uses Layer 3 (mixed)** — full final mix with music and sfx

---

### Rule 9 — Folder Structure Is Enforced

Files go in their designated folders. No exceptions.

```
VideoGenerator/          ← vault, read-only except via vault_manager.py
ProductResearch/raw/     ← product photos dropped here
ProductResearch/research/ ← generated research JSON, approved before use
scenes/[campaign]/       ← scene blueprints, locked before generation starts
frames/[campaign]/pending/  ← frame generator output, awaiting approval
frames/[campaign]/approved/ ← human-approved frames only
clips/[campaign]/animated/  ← kling output
clips/[campaign]/lipsynced/ ← lipsync output
audio/[campaign]/raw/       ← elevenlabs raw output
audio/[campaign]/enhanced/  ← cleaned audio
audio/[campaign]/mixed/     ← final mix with music
output/                  ← final delivered videos only
scripts/                 ← all engine scripts
```

**Nothing is ever generated directly into `output/`.** Output is the final step only.

---

### Rule 10 — New Products Follow The Same Flow

When adding a new product (e.g., MHP Secretagogue, Animal Pak, etc.):

1. Drop product photo in `ProductResearch/raw/`
2. Run `product_research.py` → approve research JSON
3. Write scene blueprints in `scenes/[campaign_name]/`
4. Run `frame_generator.py` → approve frames
5. Run `animation_engine.py` → review animated clips
6. Run `voice_engine.py` → review audio
7. Run `lipsync_engine.py`
8. Run `assembly_engine.py`

The existing `MrWilly` and `Xpel` characters are **reused as-is** from the vault.
No re-generation. No re-prompting. The vault already has them locked.

---

## Style Guide — What Pixar Means Here

When we say "Pixar style" we mean specifically:

- **Rendering:** 3D CGI with physically based shading and subsurface scattering on skin
- **Physique reference:** The Incredibles — exaggerated musculature, simplified anatomy
- **Skin rendering reference:** Soul — warm, rich skin tones with realistic subsurface
- **Lighting:** Warm soft studio lighting from upper left, no harsh shadows
- **Color:** Rich saturated palette — deep navy blues, warm whites, vibrant accents
- **Motion:** 24fps, smooth, intentional — every movement has a beginning, middle, and end
- **Camera:** Motivated camera moves only — the camera moves for a reason

Style parameters are locked in `VideoGenerator/styles/Pixar/style.json`.
The ffmpeg color grade in that file is applied to every clip in assembly.

---

## Anti-Drift Protocol

Character drift is the enemy. These measures prevent it:

1. **Multi-anchor generation** — 3+ reference images per generation
2. **Drift score auto-rejection** — similarity score checked before human review
3. **Approved poses library** — grows with every video, gives future generations better anchors
4. **profile.json negative prompt** — explicit list of what the character is NOT
5. **Seed locking** — reproducible results, not random variations

If drift is detected after human review:
1. Add rejection note to the pending file
2. Re-run `frame_generator.py` with the rejection note added to the prompt
3. Add more anchor poses to the character vault if needed

---

## Adding New Characters

New characters get their own folder in `VideoGenerator/characters/[NewName]/`.

Required files before any generation:
- `profile.json` — locked description, generation prefix, negative, drift threshold
- `front.png` — facing camera directly
- `back.png` — facing away from camera
- `side_left.png` — facing left
- `side_right.png` — facing right
- `approved_poses/` — empty folder, populates as videos are made

Optional but recommended:
- `real_reference.jpg` — real photo if character is based on a real person

---

## Adding New Styles

New styles get their own folder in `VideoGenerator/styles/[StyleName]/`.

Required files:
- `style.json` — generation prefix, negative, lighting, color profile, ffmpeg_color_grade
- `reference.png` — example image representing the style

---

## What "Locked" Means

When a JSON file says `"_locked": true`, it means:

- The values in this file are final for this character/style/voice
- Changes require going through `vault_manager.py`
- Changes are logged with timestamp and reason
- A change to a locked file may require regenerating frames that used the old values

If you are unsure whether to change a locked value — don't. Ask first.

---

## Enforcement

This policy applies to:
- All human contributors to this codebase
- All AI assistants (Claude, GPT, Gemini, etc.) working in this codebase
- All automated scripts run against this codebase

When a new AI assistant session starts in this codebase, this file must be read first.
The first instruction to any AI working here is: **read SYSTEM_POLICY.md before touching anything.**
