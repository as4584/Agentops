#!/usr/bin/env python3
"""
lipsync_engine.py
==================
Layer 7 — Lipsync Engine

WHAT IT DOES:
  - Takes animated clip from clips/[campaign]/animated/scene_XX.mp4
  - Takes enhanced voice from audio/[campaign]/enhanced/scene_XX_[character].mp3
  - Converts MP3 to 16kHz mono WAV (required by sync-lipsync)
  - Uploads both to FAL
  - Runs fal-ai/sync-lipsync with lipsync-1.9.0-beta
  - Saves result to clips/[campaign]/lipsynced/scene_XX.mp4

NOTE: Only runs on scenes where characters have mouths (MrWilly and Xpel both qualify).
For product-only scenes with no character face, this layer is skipped and
audio is muxed directly in assembly_engine.py.

USAGE:
  python scripts/lipsync_engine.py --scene scenes/xpel_ad/scene_01.json
  python scripts/lipsync_engine.py --campaign xpel_ad --all

SYSTEM RULES (see SYSTEM_POLICY.md):
  - Input video MUST be an animated clip from animation_engine — not a static image loop
  - ALWAYS use enhanced audio (Layer 2) for lipsync — not raw, not mixed
  - Mixed audio (Layer 3) is added in assembly_engine AFTER lipsync
  - Lipsync outputs go to clips/[campaign]/lipsynced/ ONLY
"""

from __future__ import annotations
# TODO: implement
