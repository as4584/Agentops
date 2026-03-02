"""
AEO Agent — Answer Engine Optimization for generated pages.
============================================================
Optimizes for AI-powered search and voice assistants.
Adds FAQ schema, speakable content, entity markup, topic clusters.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.base_agent import WebAgentBase
from backend.webgen.models import (
    AEOProfile,
    PageSpec,
    SiteProject,
    SiteStatus,
)


class AEOAgent(WebAgentBase):
    """
    Optimizes pages for answer engines (AI search, voice assistants).

    Process:
    1. Generate FAQ pairs for each page
    2. Add FAQ schema markup
    3. Mark speakable content sections
    4. Add entity descriptions
    5. Build topic cluster links
    """

    name = "AEOAgent"

    async def run(self, project: SiteProject) -> SiteProject:
        """Run AEO optimization on all pages."""
        brief = project.brief
        logger.info(f"[{self.name}] Running AEO optimization for {len(project.pages)} pages")

        for page in project.pages:
            logger.info(f"[{self.name}] AEO for: {page.slug}")
            aeo = await self._generate_aeo_profile(page, brief)
            page.aeo = aeo
            page.html = self._inject_aeo(page.html, aeo, brief)

        project.advance(SiteStatus.AEO_PASS)
        logger.info(f"[{self.name}] AEO optimization complete")
        return project

    async def _generate_aeo_profile(self, page: PageSpec, brief) -> AEOProfile:
        """Generate AEO metadata for a page via LLM."""
        prompt = f"""Generate Answer Engine Optimization (AEO) content for this page:

Page: {page.slug} — {page.title}
Purpose: {page.purpose}
Business: {brief.business_name}
Type: {brief.business_type.value}
Services: {', '.join(brief.services) if brief.services else 'Various services'}
Description: {brief.description}

Generate:
1. 3-5 FAQ pairs (questions people would ask AI assistants about this business/page)
2. Entity name, type, and description (who/what is this business)
3. Topic cluster (main topic) and 5 related topics
4. CSS selectors for sections that should be "speakable" (voice-readable)

Return JSON:
{{
  "faq_pairs": [
    {{"q": "Question?", "a": "Concise answer (2-3 sentences max)."}}
  ],
  "entity_name": "{brief.business_name}",
  "entity_type": "LocalBusiness",
  "entity_description": "One-paragraph description",
  "topic_cluster": "Main topic",
  "related_topics": ["topic1", "topic2"],
  "speakable_selectors": ["#hero h1", "#hero p", ".faq-answer"]
}}"""

        system = (
            "You are an AEO specialist. Optimize content for AI search engines "
            "(ChatGPT, Perplexity, Google AI Overview) and voice assistants."
        )
        result = await self.ask_llm_json(prompt, system=system, temperature=0.4)

        if "error" in result:
            logger.warning(f"[{self.name}] AEO parse failed for {page.slug}")
            return AEOProfile(entity_name=brief.business_name)

        return AEOProfile(
            faq_pairs=result.get("faq_pairs", []),
            speakable_selectors=result.get("speakable_selectors", []),
            entity_name=result.get("entity_name", brief.business_name),
            entity_type=result.get("entity_type", "LocalBusiness"),
            entity_description=result.get("entity_description", ""),
            topic_cluster=result.get("topic_cluster", ""),
            related_topics=result.get("related_topics", []),
        )

    def _inject_aeo(self, html: str, aeo: AEOProfile, brief) -> str:
        """Inject AEO markup into the page HTML."""
        if not html:
            return html

        aeo_tags = []

        # FAQ Schema (FAQPage JSON-LD)
        if aeo.faq_pairs:
            faq_schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["q"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["a"],
                        },
                    }
                    for faq in aeo.faq_pairs
                ],
            }
            aeo_tags.append(
                f'  <script type="application/ld+json">\n'
                f'{json.dumps(faq_schema, indent=2)}\n'
                f'  </script>'
            )

        # Speakable Schema
        if aeo.speakable_selectors:
            speakable_schema = {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "speakable": {
                    "@type": "SpeakableSpecification",
                    "cssSelector": aeo.speakable_selectors,
                },
            }
            aeo_tags.append(
                f'  <script type="application/ld+json">\n'
                f'{json.dumps(speakable_schema, indent=2)}\n'
                f'  </script>'
            )

        # Inject before </head>
        if aeo_tags:
            injection = "\n" + "\n".join(aeo_tags) + "\n"
            html = html.replace("</head>", f"{injection}</head>")

        # Inject FAQ section into body (before </body>)
        if aeo.faq_pairs:
            faq_html = self._build_faq_section(aeo.faq_pairs)
            html = html.replace("</body>", f"\n{faq_html}\n</body>")

        return html

    @staticmethod
    def _build_faq_section(faq_pairs: list[dict]) -> str:
        """Build a visible FAQ section with semantic HTML."""
        items = []
        for faq in faq_pairs:
            items.append(
                f'    <details class="border-b border-gray-200 py-4">\n'
                f'      <summary class="cursor-pointer font-semibold text-lg text-gray-800">'
                f'{faq.get("q", "")}</summary>\n'
                f'      <p class="faq-answer mt-2 text-gray-600">{faq.get("a", "")}</p>\n'
                f'    </details>'
            )

        return (
            '  <section id="faq" class="max-w-3xl mx-auto px-4 py-16">\n'
            '    <h2 class="text-3xl font-bold text-center mb-8">Frequently Asked Questions</h2>\n'
            + "\n".join(items) + "\n"
            "  </section>"
        )
