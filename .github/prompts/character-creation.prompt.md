---
description: "Character Creation — register Higgsfield Soul ID characters from data/higgsfield/ and scripts/seed_higgsfield_characters.py."
---

# Character Creation Prompt — Higgsfield Soul ID

You are registering a character on **Higgsfield.ai** so it can be used in video generation.

## What is a Soul ID?

A Soul ID is Higgsfield's locked character identity — it stores your reference image
and creates a consistent character model for all future video generations.

**Critical rule: ONE Soul ID per character, ever.**
Creating duplicates wastes credits and creates drift. Always check the DB first.

## Pre-flight checklist before calling hf_create_soul_id

- [ ] `db_query` → confirm `soul_id_status = 'pending'` (not already 'active')
- [ ] `file_reader` → confirm the reference image file exists at the path
- [ ] Reference image must be: clear, front-facing, single subject, good lighting
- [ ] Character name must match exactly what's in the DB (`char_xpel` → "Xpel")
- [ ] `hf_login` → browser session must be authenticated first

## Character profiles

### Xpel (char_xpel)
```
type: product_character
image: clients/probodyforlife/VideoGenerator/characters/Xpel/diuretic/front.png
positive: Pixar 3D animated feature film render, The Incredibles art style,
          MHP XPEL Diuretic box character, navy blue and yellow packaging,
          MHP logo and XPEL text fully readable, big cartoon eyes,
          small cartoon mouth, tiny arms and legs
negatives: spinning, glowing, golden particles, light bursts, wrong colors,
           unreadable text, realistic box with no face, different product
```

### MrWilly (char_mrwilly)
```
type: human_character
image: clients/probodyforlife/VideoGenerator/characters/MrWilly/front.png
positive: Pixar 3D animated feature film render, The Incredibles art style,
          extremely muscular completely bald Latino male late 40s,
          light-medium warm skin tone, completely clean shaven no facial hair,
          strong jaw and high cheekbones, white MHP basketball jersey #97
          gold and navy trim, navy blue shorts, blue sneakers
negatives: realistic, photorealistic, live action, 2D flat, anime,
           hair on head, beard, stubble, facial hair, goatee, mustache,
           dark skin, different face, different person, wrong clothing,
           missing jersey number, face warp, face distortion
```

## After successful Soul ID creation

1. Confirm URL is stored in DB via `db_query` → `soul_id_url` field
2. Confirm `soul_id_status = 'active'`
3. Log evidence screenshot to `data/higgsfield/evidence/<character_id>/soul_id_created.png`
4. Only then proceed to video generation

## Adding a new character

1. Add profile JSON to `clients/<client>/VideoGenerator/characters/<Name>/profile.json`
2. Run `scripts/seed_higgsfield_characters.py --character <name>` to register in DB
3. Follow the Soul ID creation workflow above
