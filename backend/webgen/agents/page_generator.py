"""
Page Generator Agent — Generates HTML pages from specs.
========================================================
Uses learned component templates + LLM to produce full pages.
Tailwind CSS, semantic HTML5, mobile-first responsive.
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


class PageGeneratorAgent(WebAgentBase):
    """
    Generates complete HTML pages using component templates + LLM.

    For each page:
    1. Find matching component templates for each section
    2. Fill templates with business-specific content via LLM
    3. Assemble sections into a full page
    4. Add proper head, meta, responsive viewport
    """

    name = "PageGeneratorAgent"

    def __init__(
        self,
        llm: OllamaClient | None = None,
        store: TemplateStore | None = None,
    ) -> None:
        super().__init__(llm)
        self.store = store or TemplateStore()

    async def run(self, project: SiteProject) -> SiteProject:
        """Generate HTML for all pages in the project."""
        brief = project.brief
        project.advance(SiteStatus.GENERATING)
        logger.info(f"[{self.name}] Generating {len(project.pages)} pages")

        # Generate shared CSS
        project.global_css = await self._generate_global_css(brief)

        # Generate each page
        nav_items = [
            {"label": p.nav_label, "href": f"{p.slug}.html"} for p in sorted(project.pages, key=lambda p: p.nav_order)
        ]

        for page in project.pages:
            logger.info(f"[{self.name}] Generating page: {page.slug}")
            try:
                page.html = await self._generate_page(page, brief, nav_items, project.global_css)
            except Exception as e:
                logger.error(f"[{self.name}] Error generating {page.slug}: {e}")
                project.errors.append(f"Page {page.slug}: {e}")

        project.advance(SiteStatus.GENERATED)
        logger.info(f"[{self.name}] All pages generated")
        return project

    async def _generate_page(
        self,
        page: PageSpec,
        brief: ClientBrief,
        nav_items: list[dict],
        global_css: str,
    ) -> str:
        """Generate a complete HTML page."""
        # Generate each section
        sections_html = []
        for section in sorted(page.sections, key=lambda s: s.order):
            html = await self._generate_section(section, brief, nav_items)
            section.html = html
            sections_html.append(html)

        # Assemble full page
        body = "\n\n".join(sections_html)

        return self._wrap_page(
            title=page.title or f"{brief.business_name}",
            body=body,
            global_css=global_css,
            brief=brief,
        )

    async def _generate_section(
        self,
        section: SectionSpec,
        brief: ClientBrief,
        nav_items: list[dict],
    ) -> str:
        """Generate HTML for a single section."""
        # Try to find a matching component template
        components = self.store.find_components(
            categories=[section.name, section.component_type],
            business_type=brief.business_type.value,
        )

        template_html = ""
        template_vars = []
        if components:
            comp = components[0]
            template_html = comp.html_template
            template_vars = comp.variables

        # Build context for LLM
        nav_context = "\n".join(f'  <a href="{n["href"]}">{n["label"]}</a>' for n in nav_items)

        content_hints = ""
        if section.content:
            content_hints = f"\nContent hints: {section.content}"

        template_context = ""
        if template_html:
            template_context = (
                f"\n\nUse this component template as a base (fill in the placeholders):\n"
                f"```html\n{template_html}\n```\n"
                f"Variables to fill: {template_vars}"
            )

        prompt = f"""Generate HTML for a '{section.name}' section of a website.

Business: {brief.business_name}
Type: {brief.business_type.value}
Tagline: {brief.tagline}
Services: {", ".join(brief.services) if brief.services else "Various services"}
Tone: {brief.tone}
Phone: {brief.phone}
Email: {brief.email}
{content_hints}

Navigation items:
{nav_context}
{template_context}

Requirements:
- Use Tailwind CSS utility classes
- Semantic HTML5 elements
- Mobile-first responsive design
- Component type: {section.component_type}
- Include aria labels for accessibility

Return ONLY the HTML for this section, no explanation."""

        system = (
            "You are a frontend developer. Generate clean, semantic, "
            "responsive HTML with Tailwind CSS. Output only HTML code, "
            "no markdown fences, no explanation."
        )

        html = await self.ask_llm(prompt, system=system, temperature=0.6, max_tokens=3000)

        # Clean any markdown artifacts
        html = html.strip()
        if html.startswith("```"):
            lines = html.split("\n")
            html = "\n".join(lines[1:])
        if html.endswith("```"):
            html = html[:-3].strip()

        return html

    async def _generate_global_css(self, brief: ClientBrief) -> str:
        """Generate global CSS custom properties based on brand."""
        colors = brief.colors or {}
        primary = colors.get("primary", "#2563eb")  # blue-600
        secondary = colors.get("secondary", "#1e40af")  # blue-800
        accent = colors.get("accent", "#f59e0b")  # amber-500

        return f"""/* WebGen Global Styles */
:root {{
  --color-primary: {primary};
  --color-secondary: {secondary};
  --color-accent: {accent};
  --font-heading: system-ui, -apple-system, sans-serif;
  --font-body: system-ui, -apple-system, sans-serif;
}}

body {{
  font-family: var(--font-body);
  color: #1f2937;
  line-height: 1.6;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: var(--font-heading);
  line-height: 1.2;
}}

a {{
  color: var(--color-primary);
  text-decoration: none;
}}

a:hover {{
  text-decoration: underline;
}}

.btn-primary {{
  background-color: var(--color-primary);
  color: white;
  padding: 0.75rem 1.5rem;
  border-radius: 0.5rem;
  font-weight: 600;
  transition: background-color 0.2s;
}}

.btn-primary:hover {{
  background-color: var(--color-secondary);
}}
"""

    @staticmethod
    def _wrap_page(title: str, body: str, global_css: str, brief: ClientBrief) -> str:
        """Wrap section HTML in a full page document."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{brief.tagline}">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
{global_css}
  </style>
</head>
<body class="min-h-screen bg-white">

{body}

</body>
</html>"""
