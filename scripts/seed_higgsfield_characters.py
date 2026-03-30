#!/usr/bin/env python3
"""
Seed Higgsfield character registry with existing Xpel and MrWilly characters.

Run from project root:
    python scripts/seed_higgsfield_characters.py

This script is safe to re-run — it uses upsert semantics (no duplicate records).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.higgsfield_store import higgsfield_store

# ---------------------------------------------------------------------------
# Character definitions
# ---------------------------------------------------------------------------

XPEL_PROFILE_PATH = (
    "clients/probodyforlife/VideoGenerator/characters/Xpel/diuretic/profile.json"
)
XPEL_ANCHOR_PATH = (
    "clients/probodyforlife/VideoGenerator/characters/Xpel/diuretic/front.png"
)

MRWILLY_PROFILE_PATH = (
    "clients/probodyforlife/VideoGenerator/characters/MrWilly/profile.json"
)
MRWILLY_ANCHOR_PATH = (
    "clients/probodyforlife/VideoGenerator/characters/MrWilly/front.png"
)


def _load_profile(path: str) -> dict:
    full = Path(path)
    if not full.exists():
        print(f"  ⚠  Profile not found: {path}")
        return {}
    with full.open() as f:
        return json.load(f)


def seed() -> None:
    print("Seeding Higgsfield character registry…\n")

    # ── Xpel ──────────────────────────────────────────────────────────────
    xpel_profile = _load_profile(XPEL_PROFILE_PATH)
    xpel_gen = xpel_profile.get("generation", {})

    xpel_id = higgsfield_store.upsert_character(
        name="Xpel",
        character_type="product_character",
        anchor_image_path=XPEL_ANCHOR_PATH,
        positive_prefix=xpel_gen.get("positive_prefix", ""),
        negative_prefix=xpel_gen.get("negative", ""),
        profile_json=xpel_profile,
        soul_id_status="pending",
    )
    print(f"  ✓  Xpel   → id={xpel_id}  soul_id_status=pending")

    # ── MrWilly ───────────────────────────────────────────────────────────
    mrwilly_profile = _load_profile(MRWILLY_PROFILE_PATH)
    mrwilly_gen = mrwilly_profile.get("generation", {})

    mrwilly_id = higgsfield_store.upsert_character(
        name="MrWilly",
        character_type="human_character",
        anchor_image_path=MRWILLY_ANCHOR_PATH,
        positive_prefix=mrwilly_gen.get("positive_prefix", ""),
        negative_prefix=mrwilly_gen.get("negative", ""),
        profile_json=mrwilly_profile,
        soul_id_status="pending",
    )
    print(f"  ✓  MrWilly → id={mrwilly_id}  soul_id_status=pending")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    chars = higgsfield_store.list_characters()
    print(f"Registry now contains {len(chars)} character(s):")
    for c in chars:
        print(f"  • {c['name']} ({c['character_type']})  soul_id={c['soul_id_status']}")

    print()
    print("Next step: run hf_create_soul_id for each character before generating video.")
    print("  Xpel anchor:   ", XPEL_ANCHOR_PATH)
    print("  MrWilly anchor:", MRWILLY_ANCHOR_PATH)


if __name__ == "__main__":
    seed()
