# HAILUO PROMPT GUIDE — AGENT REFERENCE

Model: `fal-ai/minimax/video-01` | `fal-ai/minimax/video-01-live`

---

## REQUIRED: Always use a reference image
Pass a source image every call. Without it the model invents the subject from scratch each generation. Identity will drift across clips.

---

## PROMPT STRUCTURE
```
[SHOT TYPE], [SUBJECT + SIMPLE ACTION], [LIGHT SOURCE], [CAMERA MOVE], [STYLE TAG]
```

**Max length:** 30-40 words. Never exceed 50.

---

## SHOT TYPE — use exactly one, put it first
- `Extreme close up` `Close up` `Medium close up` `Medium shot` `Wide shot`

## CAMERA MOVES — use exactly one
- `slow push in` `slow pull back` `static` `slow pan left` `slow pan right` `tracking shot`

## LIGHT SOURCES — use one, be specific
- `soft natural window light` `golden hour rim light` `soft diffused overhead light` `motivated side lighting`

## STYLE TAGS — pick one max
- `photorealistic` `cinematic` `film grain` `shallow depth of field` `macro lens` `commercial photography style`

---

## HARD RULES

| Rule | Reason |
|------|--------|
| One subject per prompt | Multiple subjects cause tracking failure |
| Max 4 seconds per clip | Drift increases sharply past 4s |
| Lead with shot type | Sets the frame before anything else |
| Use film/photo terms | Hailuo reads cinematography language, not casual description |
| Never describe personality | "mysterious" "confident" "beautiful" mean nothing to this model |
| One camera move only | Two camera instructions causes undefined behavior |

---

## WHAT TO STRIP OUT BEFORE SENDING

Remove anything like:
- Physical descriptions of the subject beyond what the reference image already shows
- Personality or emotional adjectives (`mysterious`, `powerful`, `elegant`)
- Vague quality words (`nice lighting`, `looks great`, `dramatic atmosphere`)
- Repeated instructions (`slow zoom and also push in and get closer`)
- Background story or context

---

## GOOD PROMPT TEMPLATE
```
Close up, [subject] [single action verb + small motion], 
[light source], [camera move], photorealistic
```

Example:
```
Close up, woman slowly turns toward camera, 
soft natural window light, static, photorealistic
```

---

## BAD PROMPT PATTERN — never do this
```
A [adjective] [subject] with [physical description] who is [personality trait] 
doing [action described in prose] with [vague lighting] and the camera [passive description]
```

---

## COST
- ~$0.018 per second of output
- 3s clip ≈ $0.054 | 5s clip ≈ $0.09
- Always test at 3s before generating longer clips

---

## FAILURE MODES TO RECOGNIZE

| Output looks like | Cause | Fix |
|-------------------|-------|-----|
| Different face each clip | No reference image | Add reference image |
| Drift after 3s | Clip too long | Cut to 3s max |
| Wrong camera movement | Over-specified prompt | Use one camera move only |
| Ignoring action | Too much description before action | Move action earlier in prompt |
| Style inconsistency | No style tag or conflicting tags | Pick one style tag, place it last |
