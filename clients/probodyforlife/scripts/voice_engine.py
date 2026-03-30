#!/usr/bin/env python3
"""
voice_engine.py
================
Layer 6 — Voice Engine (3-Layer Audio Pipeline)

WHAT IT DOES:
  LAYER 1 — GENERATION:
    - Reads dialogue from scene blueprint
    - Reads locked voice settings from VideoGenerator/voices/[character]/voice.json
    - Calls ElevenLabs API with exact locked parameters
    - Saves raw output to audio/[campaign]/raw/scene_XX_[character].mp3

  LAYER 2 — ENHANCEMENT:
    - Noise reduction on raw audio
    - EQ boost at voice clarity frequencies (2-4kHz for MrWilly, 3-5kHz for Xpel)
    - Light compression to even volume
    - Normalize to -3db
    - Saves to audio/[campaign]/enhanced/scene_XX_[character].mp3

  LAYER 3 — MIX:
    - Blend voice (-3db) + background music (-18db) + sfx (-12db)
    - Saves final mix to audio/[campaign]/mixed/scene_XX_final.mp3
    - This is the ONLY audio file passed to lipsync and assembly

USAGE:
  python scripts/voice_engine.py --scene scenes/xpel_ad/scene_01.json
  python scripts/voice_engine.py --campaign xpel_ad --all
  python scripts/voice_engine.py --campaign xpel_ad --all --skip-mix

SYSTEM RULES (see SYSTEM_POLICY.md):
  - ALWAYS read voice_id from voice.json — NEVER hardcode voice IDs
  - NEVER pass raw Layer 1 audio to lipsync — always use Layer 2+ output
  - NEVER pass raw or enhanced audio to assembly — always use Layer 3 mix
  - Voice settings are LOCKED — do not adjust per-video
"""

from __future__ import annotations
# TODO: implement
