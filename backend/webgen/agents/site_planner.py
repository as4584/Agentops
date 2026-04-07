"""
Site Planner Agent — Plans site structure from client brief.
=============================================================
Creates the sitemap, page specs, and section layout.
Uses matching templates when available.
"""

from __future__ import annotations

from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.base_agent import WebAgentBase
from backend.webgen.models import (
    ClientBrief,
    PageSpec,
    SectionSpec,
    SiteProject,
    SiteStatus,
)
from backend.webgen.template_store import TemplateStore


class SitePlannerAgent(WebAgentBase):
    """
    Plans a website's structure from a client brief.

    Uses learned templates as a starting point (90% system),
    then customizes the plan based on the specific brief.
    """

    name = "SitePlannerAgent"

    def __init__(
        self,
        llm: OllamaClient | None = None,
        store: TemplateStore | None = None,
    ) -> None:
        super().__init__(llm)
        self.store = store or TemplateStore()
        self.design_ctx = None  # injected by pipeline

    async def run(self, project: SiteProject) -> SiteProject:
        """
        Generate a site plan from the project brief.

        1. Find matching templates for the business type
        2. Ask LLM to plan pages and sections
        3. Populate project.pages with PageSpec objects
        4. Advance status to PLANNED
        """
        brief = project.brief
        logger.info(f"[{self.name}] Planning site for: {brief.business_name} ({brief.business_type.value})")

        # Find matching templates
        templates = self.store.list_templates(business_type=brief.business_type.value)
        template_context = ""
        if templates:
            best = templates[0]
            project.template_ids = [best.id]
            template_context = self._format_template_context(best)
            logger.info(f"[{self.name}] Using template: {best.name}")

        # Ask LLM to plan
        plan = await self._generate_plan(brief, template_context)

        # Parse plan into PageSpec objects
        pages = self._parse_plan(plan, brief)
        project.pages = pages

        project.advance(SiteStatus.PLANNED)
        logger.info(f"[{self.name}] Planned {len(pages)} pages")
        return project

    async def _generate_plan(self, brief: ClientBrief, template_context: str) -> dict:
        """Ask LLM to create the site plan."""
        pages_hint = ""
        if brief.pages_requested:
            pages_hint = f"\nClient requested pages: {', '.join(brief.pages_requested)}"

        design_hint = ""
        if self.design_ctx:
            design_hint = (
                f"\nDesign system: {self.design_ctx.style_name}\n"
                f"Style keywords: {self.design_ctx.style_keywords}\n"
                f"Effects: {self.design_ctx.effects_hint}\n"
                f"Primary color: {self.design_ctx.primary_color}\n"
            )

        template_hint = ""
        if template_context:
            template_hint = f"\n\nExisting template to base the plan on:\n{template_context}"

        prompt = f"""Plan a website for this business:

Business: {brief.business_name}
Type: {brief.business_type.value}
Tagline: {brief.tagline}
Description: {brief.description}
Services: {", ".join(brief.services) if brief.services else "Not specified"}
Target Audience: {brief.target_audience}
Tone: {brief.tone}
{pages_hint}
{design_hint}
{template_hint}

Create a detailed site plan with:
1. A list of pages (typically 5-8 pages)
2. For each page: slug, title, purpose, navigation label, and list of sections
3. Sections should use standard component types

Return JSON:
{{
  "pages": [
    {{
      "slug": "index",
      "title": "Home - {{business_name}}",
      "purpose": "Main landing page",
      "nav_label": "Home",
      "nav_order": 1,
      "sections": [
        {{
          "name": "hero",
          "component_type": "hero-centered",
          "content_hints": {{
            "headline": "Suggested headline text",
            "subtitle": "Suggested subtitle"
          }}
        }}
      ]
    }}
  ]
}}"""

        system = (
            "You are a web strategist. Plan website structures that are "
            "SEO-friendly, conversion-focused, and appropriate for the business type."
        )
        return await self.ask_llm_json(prompt, system=system, temperature=0.5, max_tokens=6000)

    def _parse_plan(self, plan: dict | list, brief: ClientBrief) -> list[PageSpec]:
        """Convert the LLM plan into PageSpec objects."""
        pages: list[PageSpec] = []

        # Handle case where LLM returns a list directly
        if isinstance(plan, list):
            raw_pages = plan
        else:
            raw_pages = plan.get("pages", [])

        if not raw_pages:
            # Fallback: generate a minimal plan
            logger.warning(f"[{self.name}] LLM plan was empty, using fallback")
            return self._fallback_plan(brief)

        for i, rp in enumerate(raw_pages):
            sections = []
            for j, rs in enumerate(rp.get("sections", [])):
                sections.append(
                    SectionSpec(
                        name=rs.get("name", f"section-{j}"),
                        component_type=rs.get("component_type", "generic"),
                        content=rs.get("content_hints", {}),
                        order=j,
                    )
                )

            pages.append(
                PageSpec(
                    slug=rp.get("slug", f"page-{i}"),
                    title=rp.get("title", ""),
                    purpose=rp.get("purpose", ""),
                    sections=sections,
                    nav_label=rp.get("nav_label", rp.get("title", "")),
                    nav_order=rp.get("nav_order", i + 1),
                )
            )

        return pages

    def _fallback_plan(self, brief: ClientBrief) -> list[PageSpec]:
        """Generate a sensible default plan if LLM fails."""
        default_pages = [
            ("index", "Home", "Main landing page", ["nav", "hero", "features", "testimonials", "cta", "footer"]),
            ("about", "About Us", "Company story and team", ["nav", "hero-small", "story", "team", "footer"]),
            ("services", "Services", "Service offerings", ["nav", "hero-small", "services-grid", "cta", "footer"]),
            ("contact", "Contact", "Contact form and info", ["nav", "hero-small", "contact-form", "map", "footer"]),
        ]

        pages = []
        for i, (slug, title, purpose, section_names) in enumerate(default_pages):
            sections = [SectionSpec(name=s, component_type=s, order=j) for j, s in enumerate(section_names)]
            pages.append(
                PageSpec(
                    slug=slug,
                    title=f"{title} - {brief.business_name}",
                    purpose=purpose,
                    sections=sections,
                    nav_label=title,
                    nav_order=i + 1,
                )
            )
        return pages

    def _format_template_context(self, template) -> str:
        """Format a template record as context for the LLM."""
        return (
            f"Template: {template.name}\n"
            f"Type: {template.business_type}\n"
            f"Section order: {', '.join(template.section_order)}\n"
            f"Nav: {template.nav_pattern}\n"
            f"Pages: {len(template.page_structure)}\n"
            f"Description: {template.description}"
        )
