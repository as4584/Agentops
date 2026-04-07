"""
Generate WebGen DPO Pairs — preference pairs for RLHF fine-tuning
==================================================================
Produces 50 (prompt, chosen_html, rejected_html) pairs.
"Chosen": design-system-aware Tailwind HTML (from qwen3-coder-free).
"Rejected": generic placeholder HTML with inline styles and no design tokens.

Output: data/dpo/webgen_dpo_<timestamp>.jsonl

Usage:
    python scripts/generate_webgen_dpo.py
    python scripts/generate_webgen_dpo.py --count 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.llm import OllamaClient
from backend.webgen.agents.design_advisor import DesignAdvisorAgent
from backend.webgen.agents.ux_scorer import grade_pair
from backend.webgen.models import BusinessType, ClientBrief

BUSINESSES = [
    (BusinessType.SAAS, "NexusMetrics", "Data insights at the speed of thought", ["Dashboards", "Alerts", "API", "Integrations"], "professional"),
    (BusinessType.RESTAURANT, "Harbor Fish & Grill", "Fresh catches from sea to table", ["Seafood", "Raw bar", "Private dining", "Wine list"], "elegant"),
    (BusinessType.ECOMMERCE, "UrbanThread", "Streetwear for the culture", ["Hoodies", "Joggers", "Caps", "Limited drops"], "bold"),
    (BusinessType.FITNESS, "CoreForce Studio", "Build strength. Build resilience.", ["Classes", "Personal training", "Nutrition", "Online coaching"], "bold"),
    (BusinessType.MEDICAL, "VitalMind Therapy", "Your mental health matters", ["Individual therapy", "Group sessions", "Teletherapy", "Crisis support"], "friendly"),
    (BusinessType.EDUCATION, "Beacon Learning", "Bright futures start here", ["K-12 tutoring", "SAT prep", "College applications", "Online classes"], "friendly"),
    (BusinessType.AGENCY, "Pixel & Pine Design", "Thoughtful design for good brands", ["Branding", "Web design", "Print", "Motion"], "minimal"),
    (BusinessType.FITNESS, "RogueMMA", "Train like a fighter", ["MMA classes", "Boxing", "BJJ", "Conditioning"], "bold"),
    (BusinessType.SAAS, "InvoiceFlow", "Billing that never sleeps", ["Invoicing", "Subscriptions", "Tax compliance", "Reporting"], "professional"),
    (BusinessType.ECOMMERCE, "CedarGrove Candles", "Hand-poured, small batch, all-natural", ["Soy candles", "Diffusers", "Gift sets", "Custom scents"], "elegant"),
]

SECTIONS = [
    ("hero", "hero-centered"),
    ("features", "features-grid"),
    ("pricing", "pricing-cards"),
    ("testimonials", "testimonials"),
    ("cta", "call-to-action"),
]

SYSTEM_GOOD = (
    "You are an expert frontend developer. Generate beautiful, conversion-focused website sections "
    "using Tailwind CSS. Use the provided design system (colors, fonts, style). "
    "Output ONLY raw HTML code — no markdown, no explanation.\n"
    "STRUCTURE RULES (mandatory):\n"
    "- Use <nav> for ALL navigation menus. NEVER use <div> as a navigation container.\n"
    "- Use <header> for page/section headers. NEVER use <div class='header-*'> as a substitute.\n"
    "- Use <main> to wrap primary content.\n"
    "- Use <footer> for footer regions.\n"
    "- Use <section> for distinct content areas. Each section MUST have an accessible heading.\n"
    "- Use <article> for self-contained content blocks.\n"
    "- Use <h1> exactly once per page. Use <h2>/<h3> for subsections.\n"
    "- Include at most 3 CTAs per section and at most 7 nav links."
)

SYSTEM_BAD = (
    "You are a basic HTML developer. Generate a simple HTML section with inline styles. "
    "Use generic blue colors and Times New Roman font. Output only HTML."
)


def build_prompt(biz: tuple, section_name: str, component_type: str, ctx) -> str:
    business_type, business_name, tagline, services, tone = biz
    return f"""Generate a '{section_name}' section for a website.

Business: {business_name} ({business_type.value})
Tagline: {tagline}
Services: {", ".join(services)}
Tone: {tone}

Design system:
- Style: {ctx.style_name}
- Primary: {ctx.primary_color}  Accent: {ctx.accent_color}
- Heading font: {ctx.heading_font}  Body font: {ctx.body_font}

Component type: {component_type}
Use Tailwind CSS, semantic HTML5, mobile-first responsive design."""


def build_generic_prompt(biz: tuple, section_name: str, component_type: str) -> str:
    business_type, business_name, tagline, services, _ = biz
    return f"""Make a basic HTML {section_name} section for {business_name}.
Services: {", ".join(services[:2])}.
Use inline styles, blue color #0000FF, Times New Roman font."""


async def generate_pair(
    client: OllamaClient,
    advisor: DesignAdvisorAgent,
    biz: tuple,
    section_name: str,
    component_type: str,
) -> dict | None:
    business_type, business_name, tagline, services, tone = biz
    brief = ClientBrief(
        business_name=business_name,
        business_type=business_type,
        tagline=tagline,
        services=services,
        tone=tone,
        target_audience="", phone="", email="",
    )
    ctx = advisor.advise(brief)

    good_prompt = build_prompt(biz, section_name, component_type, ctx)
    bad_prompt = build_generic_prompt(biz, section_name, component_type)

    chosen_html = None
    rejected_html = None
    for attempt in range(4):
        try:
            chosen_html, rejected_html = await asyncio.gather(
                client.chat(
                    messages=[{"role": "system", "content": SYSTEM_GOOD}, {"role": "user", "content": good_prompt}],
                    temperature=0.7,
                    max_tokens=2000,
                ),
                client.chat(
                    messages=[{"role": "system", "content": SYSTEM_BAD}, {"role": "user", "content": bad_prompt}],
                    temperature=0.4,
                    max_tokens=800,
                ),
            )
            break
        except Exception as e:
            err = str(e)
            if "rate limit" in err.lower() and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"  [RATE LIMIT] {business_name}/{section_name}: waiting {wait}s (attempt {attempt+1}/4)")
                await asyncio.sleep(wait)
                continue
            print(f"  [ERROR] {business_name}/{section_name}: {e}")
            return None

    if not chosen_html or len(chosen_html.strip()) < 100:
        return None

    def clean(html: str) -> str:
        html = html.strip()
        if html.startswith("```"):
            html = "\n".join(html.split("\n")[1:])
        if html.endswith("```"):
            html = html[:-3].strip()
        return html

    c_html = clean(chosen_html)
    r_html = clean(rejected_html) if rejected_html else "<section><p>Services</p></section>"

    # Score with UX laws — skip pairs where chosen isn't meaningfully better
    grading = grade_pair(c_html, r_html)
    if not grading["is_valid_pair"]:
        print(f"  [SKIP] {business_name}/{section_name}: margin={grading['margin']} (chosen={grading['chosen_score']}, rejected={grading['rejected_score']})")
        return None

    return {
        "prompt": good_prompt,
        "chosen": c_html,
        "rejected": r_html,
        "category": "webgen_section",
        "business_type": business_type.value,
        "section": section_name,
        "style": ctx.style_name,
        "primary_color": ctx.primary_color,
        "heading_font": ctx.heading_font,
        "ux_scores": grading,
        "why_chosen_is_better": (
            f"UX score: chosen={grading['chosen_score']}/100 vs rejected={grading['rejected_score']}/100 "
            f"(margin={grading['margin']}). Uses design system ({ctx.style_name} style, "
            f"{ctx.primary_color} primary, {ctx.heading_font}/{ctx.body_font} fonts), "
            f"Tailwind CSS, semantic HTML5, mobile-first, conversion-focused. "
            f"Violations in rejected: {'; '.join(grading['rejected_breakdown']['violations'][:3]) or 'none'}"
        ),
        "why_rejected_is_worse": (
            f"UX score {grading['rejected_score']}/100. "
            + ('; '.join(grading['rejected_breakdown']['violations']) or
               "Generic inline styles, no design tokens, non-responsive.")
        ),
    }


async def main(count: int, output_path: Path, concurrency: int = 2) -> None:
    client = OllamaClient(model="qwen2.5-coder:7b")
    advisor = DesignAdvisorAgent()

    product = [(biz, sn, ct) for biz in BUSINESSES for sn, ct in SECTIONS]
    random.shuffle(product)
    tasks = (product * (count // len(product) + 1))[:count]

    print(f"Generating {count} DPO pairs with qwen2.5-coder:7b (local Ollama)...")
    print(f"Output: {output_path}\n")

    sem = asyncio.Semaphore(concurrency)

    async def bounded(biz, sn, ct, idx):
        async with sem:
            print(f"[{idx+1}/{count}] {biz[1]} / {sn}")
            result = await generate_pair(client, advisor, biz, sn, ct)

            return result

    coros = [bounded(biz, sn, ct, i) for i, (biz, sn, ct) in enumerate(tasks)]
    raw = await asyncio.gather(*coros)
    results = [r for r in raw if r is not None]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for entry in results:
            f.write(json.dumps(entry) + "\n")

    if results:
        scores = [r["ux_scores"]["chosen_score"] for r in results]
        margins = [r["ux_scores"]["margin"] for r in results]
        print(f"\nDone: {len(results)}/{count} pairs saved to {output_path}")
        print(f"UX scores  — chosen avg: {sum(scores)//len(scores)}  margins avg: {sum(margins)//len(margins)}  min margin: {min(margins)}")
    else:
        print(f"\nDone: 0 pairs saved (all filtered out)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument(
        "--output",
        type=str,
        default=f"data/dpo/webgen_dpo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    asyncio.run(main(args.count, Path(args.output), args.concurrency))
