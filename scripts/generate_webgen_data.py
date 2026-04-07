"""
Generate WebGen Training Data — ShareGPT format
================================================
Produces N (brief + design_context + section → HTML) examples
using qwen2.5-coder:7b via local Ollama (no rate limits).

Output: data/training/webgen_sharegpt_<timestamp>.jsonl

Usage:
    python scripts/generate_webgen_data.py
    python scripts/generate_webgen_data.py --count 100 --output data/training/custom.jsonl
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
from backend.webgen.models import BusinessType, ClientBrief

# ── Business profiles ────────────────────────────────────────────────────────

BUSINESSES = [
    # (business_type, business_name, tagline, services, tone)
    (BusinessType.RESTAURANT, "La Bella Cucina", "Authentic Italian flavors since 1987", ["Dine-in", "Takeout", "Private events", "Catering"], "elegant"),
    (BusinessType.RESTAURANT, "Smoky Barrel BBQ", "Low and slow since 2010", ["BBQ platters", "Family meals", "Beer garden", "Catering"], "friendly"),
    (BusinessType.RESTAURANT, "Zen Garden Sushi", "Mindful Japanese cuisine", ["Omakase", "Sushi rolls", "Hot pot", "Sake bar"], "minimal"),
    (BusinessType.SAAS, "FlowDesk", "Project management that gets out of your way", ["Task boards", "Time tracking", "Integrations", "Reports"], "professional"),
    (BusinessType.SAAS, "BrightMetrics", "Analytics built for growth teams", ["Real-time dashboards", "Custom reports", "A/B testing", "API"], "bold"),
    (BusinessType.SAAS, "SecureVault Pro", "Enterprise password & secrets management", ["Zero-knowledge encryption", "SSO", "Audit logs", "SCIM"], "professional"),
    (BusinessType.ECOMMERCE, "Velvet & Stone", "Handcrafted jewelry for modern souls", ["Necklaces", "Rings", "Custom orders", "Gift sets"], "luxury"),
    (BusinessType.ECOMMERCE, "GearUp Sports", "Performance gear for serious athletes", ["Running shoes", "Training apparel", "Equipment", "Recovery"], "bold"),
    (BusinessType.ECOMMERCE, "TidyHome Co", "Sustainable home essentials", ["Storage solutions", "Cleaning supplies", "Organizers", "Gift boxes"], "friendly"),
    (BusinessType.FITNESS, "Iron Phoenix Gym", "Where legends are forged", ["Personal training", "Group classes", "Nutrition coaching", "Online programs"], "bold"),
    (BusinessType.FITNESS, "Serenity Yoga Studio", "Find your center", ["Yoga classes", "Meditation", "Workshops", "Retreats"], "minimal"),
    (BusinessType.FITNESS, "Peak Performance PT", "Science-backed physio & rehab", ["Physiotherapy", "Sports massage", "Injury prevention", "Pilates"], "professional"),
    (BusinessType.AGENCY, "Blaze Creative", "We build brands that lead", ["Brand strategy", "Web design", "Content creation", "Social media"], "bold"),
    (BusinessType.AGENCY, "Steadfast Digital", "Reliable growth through data", ["SEO", "PPC campaigns", "Analytics", "CRO"], "professional"),
    (BusinessType.MEDICAL, "ClearSkin Dermatology", "Expert skin care you can trust", ["Acne treatment", "Anti-aging", "Cosmetic procedures", "Skin cancer screening"], "professional"),
    (BusinessType.MEDICAL, "HealWell Clinic", "Holistic family healthcare", ["General medicine", "Preventive care", "Telehealth", "Mental health"], "friendly"),
    (BusinessType.EDUCATION, "CodePath Academy", "Launch your tech career", ["Web development", "Data science", "UX design", "Career coaching"], "bold"),
    (BusinessType.EDUCATION, "LinguaFlow School", "Languages open doors", ["Spanish", "French", "Mandarin", "Business English", "Online classes"], "friendly"),
    (BusinessType.PORTFOLIO, "Mia Chen Photography", "Light, emotion, memory", ["Weddings", "Portraits", "Events", "Commercial"], "elegant"),
    (BusinessType.CONSTRUCTION, "BuildRight Contractors", "Solid work, honest pricing", ["Home renovation", "Extensions", "Roofing", "Commercial fitouts"], "professional"),
]

SECTION_TYPES = [
    ("hero", "hero-centered"),
    ("nav", "navigation-bar"),
    ("about", "about-section"),
    ("services", "services-grid"),
    ("features", "features-list"),
    ("testimonials", "testimonials-carousel"),
    ("pricing", "pricing-cards"),
    ("cta", "call-to-action"),
    ("contact", "contact-form"),
    ("footer", "site-footer"),
    ("team", "team-grid"),
    ("gallery", "image-gallery"),
    ("stats", "stats-counter"),
    ("faq", "faq-accordion"),
]

SYSTEM_PROMPT = (
    "You are an expert frontend developer specializing in beautiful, conversion-focused websites. "
    "Generate clean, semantic, responsive HTML using Tailwind CSS utility classes. "
    "Output ONLY raw HTML code — no markdown fences, no explanations, no comments outside the HTML. "
    "Make it visually stunning and production-ready."
)

# ── Generator ────────────────────────────────────────────────────────────────

async def generate_section(
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

    human_prompt = f"""Generate a '{section_name}' section for a website.

BUSINESS BRIEF:
- Name: {business_name}
- Type: {business_type.value}
- Tagline: {tagline}
- Services: {", ".join(services)}
- Tone: {tone}

DESIGN SYSTEM:
- Style: {ctx.style_name} — {ctx.style_keywords}
- Primary color: {ctx.primary_color}
- Secondary color: {ctx.secondary_color}
- Accent color: {ctx.accent_color}
- Background: {ctx.background_color}
- Heading font: {ctx.heading_font}
- Body font: {ctx.body_font}
- Effects: {ctx.effects_hint or "subtle hover transitions"}

CSS VARIABLES AVAILABLE:
  --color-primary: {ctx.primary_color}
  --color-secondary: {ctx.secondary_color}
  --color-accent: {ctx.accent_color}
  --font-heading: '{ctx.heading_font}', sans-serif
  --font-body: '{ctx.body_font}', sans-serif

REQUIREMENTS:
- Component type: {component_type}
- Use Tailwind CSS classes for all styling
- Semantic HTML5 elements
- Mobile-first responsive design (sm: md: lg: breakpoints)
- Include aria labels for accessibility
- Use the specified colors and fonts
- Output ONLY the HTML for this section"""

    for attempt in range(4):
        try:
            html = await client.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": human_prompt},
                ],
                temperature=0.7,
                max_tokens=2500,
            )
            if not html or len(html.strip()) < 100:
                print(f"  [SKIP] Empty response for {business_name}/{section_name}")
                return None

            # Clean markdown artifacts
            html = html.strip()
            if html.startswith("```"):
                lines = html.split("\n")
                html = "\n".join(lines[1:])
            if html.endswith("```"):
                html = html[:-3].strip()

            return {
                "conversations": [
                    {"from": "human", "value": human_prompt},
                    {"from": "gpt", "value": html},
                ]
            }
        except Exception as e:
            err = str(e)
            if "rate limit" in err.lower() and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"  [RATE LIMIT] {business_name}/{section_name}: waiting {wait}s (attempt {attempt+1}/4)")
                await asyncio.sleep(wait)
                continue
            print(f"  [ERROR] {business_name}/{section_name}: {e}")
            return None
    return None


async def main(count: int, output_path: Path, concurrency: int = 3) -> None:
    client = OllamaClient(model="qwen2.5-coder:7b")
    advisor = DesignAdvisorAgent()

    # Build task list: cycle through businesses × sections
    tasks = []
    sections_cycle = SECTION_TYPES * (count // len(SECTION_TYPES) + 1)
    biz_cycle = BUSINESSES * (count // len(BUSINESSES) + 1)

    random.shuffle(sections_cycle)
    random.shuffle(biz_cycle)

    for i in range(count):
        biz = biz_cycle[i]
        section_name, component_type = sections_cycle[i]
        tasks.append((biz, section_name, component_type))

    print(f"Generating {count} webgen training examples with qwen2.5-coder:7b (local Ollama)...")
    print(f"Output: {output_path}\n")

    results = []
    sem = asyncio.Semaphore(concurrency)

    async def bounded(biz, sn, ct, idx):
        async with sem:
            print(f"[{idx+1}/{count}] {biz[1]} / {sn}")
            result = await generate_section(client, advisor, biz, sn, ct)
            return result

    coros = [bounded(biz, sn, ct, i) for i, (biz, sn, ct) in enumerate(tasks)]
    raw = await asyncio.gather(*coros)
    results = [r for r in raw if r is not None]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for entry in results:
            f.write(json.dumps(entry) + "\n")

    print(f"\nDone: {len(results)}/{count} examples saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument(
        "--output",
        type=str,
        default=f"data/training/webgen_sharegpt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    asyncio.run(main(int(args.count), Path(args.output), int(args.concurrency)))
