#!/usr/bin/env python3
"""
product_research.py
====================
Layer 0 — Product Research Engine

WHAT IT DOES:
  - Accepts a product image path
  - Uses Claude vision to extract all visible packaging claims, ingredients, colors
  - Uses OpenRouter/Claude to research ingredients and generate truthful talking points
  - Outputs a research.json file to ProductResearch/research/
  - Script engine reads research.json — NOTHING in the script is invented

USAGE:
  python scripts/product_research.py --image ProductResearch/raw/xpel_product_photo.png
  python scripts/product_research.py --image ProductResearch/raw/xpel_product_photo.png --output ProductResearch/research/xpel_research.json

RULES (see SYSTEM_POLICY.md):
  - Never fabricate claims not visible on packaging
  - Always include risks and disclaimers
  - Research.json must be approved before script generation
"""

from __future__ import annotations
# TODO: implement
