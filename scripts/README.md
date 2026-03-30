# scripts/

Platform infrastructure scripts and git hooks. Run all scripts from the
**project root**.

## Platform Infrastructure

| Script | Purpose |
|---|---|
| `port-check.sh` | Diagnoses port conflicts before starting services |
| `install-hooks.sh` | Installs the git pre-commit hook from `hooks/` |
| `hooks/pre-commit` | Git pre-commit hook (runs ruff + pytest smoke) |

## Video Production Tools (ProBodyForLife campaign)

These scripts support the XPEL ad campaign for the ProBodyForLife client.
Client assets live in `clients/probodyforlife/`.

| Script | Purpose |
|---|---|
| `frame_gen.py` | Generates individual scene frames |
| `make_kling_video.py` | Submits frames to Kling for AI video generation |
| `make_minecraft_video.py` | Minecraft-style scene video generator |
| `make_minecraft_ai_video.py` | AI-enhanced Minecraft video variant |
| `make_video_v2.py` / `v3.py` | Iterative video assembly pipelines |
| `compose_final.sh` | Composites audio + video into a final cut |

## Ad Generator Tools

| Script | Purpose |
|---|---|
| `mhp_ad_generator.py` | MHP ad generation (v1) |
| `mhp_ad_generator_v2.py` | MHP ad generation (v2 — current) |
| `pixel_agent_bridge.py` | Bridge between this repo and the pixel-agents submodule |
