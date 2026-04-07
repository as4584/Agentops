"""
Design Advisor Agent — Selects a visual design system from UI/UX Pro Max data.
===============================================================================
No LLM calls — pure CSV lookup based on business type and tone.
Returns a DesignContext that enriches every webgen agent prompt.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

from backend.utils import logger
from backend.webgen.models import ClientBrief

# Path to UI/UX Pro Max CSV data
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "sandbox/ui-ux-pro-max-skill/src/ui-ux-pro-max/data"


@dataclasses.dataclass
class DesignContext:
    """Visual design tokens chosen for a site."""

    style_name: str = "Modern Flat Design"
    style_keywords: str = "clean, modern, professional"
    primary_color: str = "#2563EB"
    secondary_color: str = "#3B82F6"
    accent_color: str = "#EA580C"
    background_color: str = "#F8FAFC"
    foreground_color: str = "#1E293B"
    card_color: str = "#FFFFFF"
    heading_font: str = "Poppins"
    body_font: str = "Open Sans"
    google_fonts_css_import: str = (
        "@import url('https://fonts.googleapis.com/css2?family=Open+Sans:"
        "wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');"
    )
    effects_hint: str = ""
    use_pretext: bool = True


# Business type → substrings to match in "Product Type" column of colors.csv
_BT_COLOR_KEYWORDS: dict[str, list[str]] = {
    "restaurant": ["Restaurant", "Food", "Cafe", "Hospitality"],
    "ecommerce": ["E-commerce", "ecommerce", "Retail", "Shop"],
    "saas": ["SaaS", "B2B SaaS", "Software", "Tech"],
    "agency": ["Agency", "Creative", "Marketing"],
    "portfolio": ["Portfolio", "Creative", "Freelance"],
    "medical": ["Healthcare", "Medical", "Health"],
    "legal": ["Legal", "Law", "Professional"],
    "realestate": ["Real Estate", "Property"],
    "fitness": ["Health", "Wellness", "Fitness", "Gym"],
    "education": ["Education", "EdTech", "Learning"],
    "nonprofit": ["Non-Profit", "Nonprofit", "Charity", "Community"],
    "construction": ["Construction", "Building", "Contractor"],
    "salon": ["Beauty", "Salon", "Spa"],
    "automotive": ["Automotive", "Auto", "Car"],
}

# Tone → keywords to look for in typography "Mood/Style Keywords" + "Best For"
_TONE_TYPO_KEYWORDS: dict[str, list[str]] = {
    "professional": ["Professional", "Corporate", "Business", "Clean"],
    "friendly": ["Friendly", "Approachable", "Casual", "Warm"],
    "bold": ["Bold", "Impact", "Startup", "Tech", "Modern"],
    "minimal": ["Minimal", "Clean", "Swiss", "Simple"],
    "luxury": ["Luxury", "Elegant", "Premium", "Sophisticated"],
    "elegant": ["Elegant", "Luxury", "Classic", "Premium"],
    "playful": ["Playful", "Fun", "Creative", "Friendly"],
}

# Tone → keywords for style selection from styles.csv "Best For"
_STYLE_KEYWORDS: dict[str, list[str]] = {
    "professional": ["Professional", "Corporate", "Business", "SaaS", "Enterprise"],
    "friendly": ["Lifestyle", "Wellness", "Community", "Small Business"],
    "bold": ["Startup", "Tech", "Bold", "Modern"],
    "minimal": ["Minimalist", "Agency", "Portfolio", "Clean"],
    "luxury": ["Luxury", "Premium", "High-end", "Fashion"],
    "elegant": ["Editorial", "Luxury", "Premium", "Elegant"],
}


def _load_csv(filename: str) -> list[dict[str, str]]:
    path = _DATA_DIR / filename
    if not path.exists():
        logger.warning(f"[DesignAdvisor] CSV not found: {path}")
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _score_row(row_text: str, keywords: list[str]) -> int:
    lower = row_text.lower()
    return sum(1 for k in keywords if k.lower() in lower)


class DesignAdvisorAgent:
    """
    Picks a design system (colors, fonts, style) from UI/UX Pro Max CSV data
    based on business type and tone. Zero LLM calls — pure deterministic lookup.
    """

    name = "DesignAdvisorAgent"

    def __init__(self) -> None:
        self._colors = _load_csv("colors.csv")
        self._typography = _load_csv("typography.csv")
        self._styles = _load_csv("styles.csv")

    def advise(self, brief: ClientBrief) -> DesignContext:
        """Return a DesignContext matched to the brief's business type and tone."""
        ctx = DesignContext()
        bt = brief.business_type.value if hasattr(brief.business_type, "value") else str(brief.business_type)
        tone = (brief.tone or "professional").lower()

        # ── Color palette ──────────────────────────────────────────────────
        bt_kws = _BT_COLOR_KEYWORDS.get(bt, [bt.replace("_", " ").title()])
        best: dict[str, str] | None = None
        best_score = -1
        for row in self._colors:
            score = _score_row(row.get("Product Type", ""), bt_kws)
            if score > best_score:
                best_score = score
                best = row
        if best:
            ctx.primary_color = best.get("Primary", ctx.primary_color)
            ctx.secondary_color = best.get("Secondary", ctx.secondary_color)
            ctx.accent_color = best.get("Accent", ctx.accent_color)
            ctx.background_color = best.get("Background", ctx.background_color)
            ctx.foreground_color = best.get("Foreground", ctx.foreground_color)
            ctx.card_color = best.get("Card", ctx.card_color)

        # ── Typography pairing ─────────────────────────────────────────────
        typo_kws = _TONE_TYPO_KEYWORDS.get(tone, ["Professional", "Clean"])
        best = None
        best_score = -1
        for row in self._typography:
            combined = " ".join(
                [
                    row.get("Font Pairing Name", ""),
                    row.get("Mood/Style Keywords", ""),
                    row.get("Best For", ""),
                ]
            )
            score = _score_row(combined, typo_kws)
            if score > best_score:
                best_score = score
                best = row
        if best:
            ctx.heading_font = best.get("Heading Font", ctx.heading_font)
            ctx.body_font = best.get("Body Font", ctx.body_font)
            ctx.google_fonts_css_import = best.get("CSS Import", ctx.google_fonts_css_import)

        # ── Visual style ───────────────────────────────────────────────────
        style_kws = _STYLE_KEYWORDS.get(tone, ["Professional", "Clean"]) + _BT_COLOR_KEYWORDS.get(
            bt, [bt.replace("_", " ").title()]
        )
        best = None
        best_score = -1
        for row in self._styles:
            combined = " ".join(
                [
                    row.get("Style Category", ""),
                    row.get("Best For", ""),
                    row.get("Keywords", ""),
                ]
            )
            score = _score_row(combined, style_kws)
            if score > best_score:
                best_score = score
                best = row
        if best:
            ctx.style_name = best.get("Style Category", ctx.style_name)
            ctx.style_keywords = best.get("Keywords", ctx.style_keywords)
            ctx.effects_hint = best.get("Effects & Animation", "")

        logger.info(
            f"[{self.name}] bt={bt} tone={tone} → "
            f"style={ctx.style_name!r} fonts={ctx.heading_font}/{ctx.body_font} "
            f"primary={ctx.primary_color}"
        )
        return ctx
