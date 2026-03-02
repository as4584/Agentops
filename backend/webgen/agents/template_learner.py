"""
Template Learner Agent — Learns website patterns from existing sites.
=====================================================================
Analyzes HTML files from a directory or URL, extracts structure,
components, styles, and stores them as reusable templates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.base_agent import WebAgentBase
from backend.webgen.template_store import (
    ComponentRecord,
    StylePattern,
    TemplateRecord,
    TemplateStore,
)


class TemplateLearnerAgent(WebAgentBase):
    """
    Learns website templates by analyzing HTML source.

    Process:
    1. Read HTML from directory or URL
    2. Ask LLM to extract page structure (sections, components)
    3. Ask LLM to extract style patterns (colors, fonts, spacing)
    4. Store reusable components with {{placeholders}}
    5. Store full template metadata
    """

    name = "TemplateLearnerAgent"

    def __init__(
        self,
        llm: Optional[OllamaClient] = None,
        store: Optional[TemplateStore] = None,
    ) -> None:
        super().__init__(llm)
        self.store = store or TemplateStore()

    async def run(self, source: str, business_type: str = "custom", name: str = "") -> TemplateRecord:
        """
        Learn a template from a source (directory path or URL).

        Args:
            source: Path to an HTML file/directory, or a URL.
            business_type: Business vertical this template belongs to.
            name: Human-friendly name for the template.

        Returns:
            The created TemplateRecord.
        """
        logger.info(f"[{self.name}] Learning from: {source}")

        # Collect HTML content
        html_pages = self._collect_html(source)
        if not html_pages:
            raise ValueError(f"No HTML content found at: {source}")

        logger.info(f"[{self.name}] Found {len(html_pages)} HTML pages")

        # Analyze structure via LLM
        structure = await self._analyze_structure(html_pages)
        components = await self._extract_components(html_pages, structure)
        style = await self._extract_style(html_pages)

        # Store components
        component_ids = []
        for comp_data in components:
            comp = ComponentRecord(
                name=comp_data.get("name", "unnamed"),
                category=comp_data.get("category", "general"),
                description=comp_data.get("description", ""),
                html_template=comp_data.get("html_template", ""),
                variables=comp_data.get("variables", []),
                business_types=[business_type],
                tags=comp_data.get("tags", []),
                source_url=source if source.startswith("http") else "",
            )
            cid = self.store.add_component(comp)
            component_ids.append(cid)
            logger.info(f"[{self.name}] Stored component: {comp.name} ({comp.category})")

        # Build template record
        template = TemplateRecord(
            name=name or f"template-{business_type}",
            source_url=source if source.startswith("http") else "",
            source_path=source if not source.startswith("http") else "",
            business_type=business_type,
            description=structure.get("description", ""),
            page_structure=structure.get("pages", []),
            component_ids=component_ids,
            style=StylePattern(**style) if isinstance(style, dict) else StylePattern(),
            nav_pattern=structure.get("nav_pattern", "top-bar"),
            footer_pattern=structure.get("footer_pattern", "standard"),
            section_order=structure.get("section_order", []),
        )

        self.store.add_template(template)
        logger.info(
            f"[{self.name}] Template '{template.name}' stored with "
            f"{len(component_ids)} components"
        )
        return template

    # ── HTML collection ──────────────────────────────────

    def _collect_html(self, source: str) -> dict[str, str]:
        """
        Collect HTML from a local path.
        Returns {filename: html_content}.
        """
        pages: dict[str, str] = {}

        if source.startswith("http"):
            # URL fetching handled separately via learn_url
            return pages

        path = Path(source)
        if path.is_file() and path.suffix in (".html", ".htm"):
            pages[path.name] = path.read_text(errors="ignore")
        elif path.is_dir():
            for f in sorted(path.rglob("*.html")):
                rel = str(f.relative_to(path))
                pages[rel] = f.read_text(errors="ignore")
            for f in sorted(path.rglob("*.htm")):
                rel = str(f.relative_to(path))
                pages[rel] = f.read_text(errors="ignore")
        return pages

    async def learn_from_html(self, html: str, source_name: str = "pasted",
                               business_type: str = "custom", name: str = "") -> TemplateRecord:
        """Learn from raw HTML string (e.g., fetched from a URL)."""
        html_pages = {source_name: html}

        structure = await self._analyze_structure(html_pages)
        components = await self._extract_components(html_pages, structure)
        style = await self._extract_style(html_pages)

        component_ids = []
        for comp_data in components:
            comp = ComponentRecord(
                name=comp_data.get("name", "unnamed"),
                category=comp_data.get("category", "general"),
                description=comp_data.get("description", ""),
                html_template=comp_data.get("html_template", ""),
                variables=comp_data.get("variables", []),
                business_types=[business_type],
                tags=comp_data.get("tags", []),
                source_url=source_name if source_name.startswith("http") else "",
            )
            cid = self.store.add_component(comp)
            component_ids.append(cid)

        template = TemplateRecord(
            name=name or f"template-{business_type}",
            source_url=source_name if source_name.startswith("http") else "",
            business_type=business_type,
            description=structure.get("description", ""),
            page_structure=structure.get("pages", []),
            component_ids=component_ids,
            style=StylePattern(**style) if isinstance(style, dict) else StylePattern(),
            nav_pattern=structure.get("nav_pattern", "top-bar"),
            footer_pattern=structure.get("footer_pattern", "standard"),
            section_order=structure.get("section_order", []),
        )

        self.store.add_template(template)
        logger.info(f"[{self.name}] Template '{template.name}' stored from HTML")
        return template

    # ── LLM analysis ─────────────────────────────────────

    async def _analyze_structure(self, html_pages: dict[str, str]) -> dict:
        """Ask LLM to analyze the overall site structure."""
        # Truncate HTML to fit context window
        combined = ""
        for name, html in html_pages.items():
            truncated = self._truncate_html(html, max_chars=6000)
            combined += f"\n\n=== FILE: {name} ===\n{truncated}"

        prompt = f"""Analyze this website's HTML structure.

{combined}

Extract:
1. Overall description of the site
2. Navigation pattern (top-bar, sidebar, hamburger)
3. Footer pattern (standard, minimal, mega-footer)
4. List of pages with their sections in order
5. Common section order across pages

Return JSON with this structure:
{{
  "description": "Brief description of the site layout",
  "nav_pattern": "top-bar",
  "footer_pattern": "standard",
  "section_order": ["nav", "hero", "features", "testimonials", "cta", "footer"],
  "pages": [
    {{
      "slug": "index",
      "title": "Home",
      "sections": ["nav", "hero", "features", "cta", "footer"]
    }}
  ]
}}"""

        system = "You are a web design analyst. Extract structural patterns from HTML."
        return await self.ask_llm_json(prompt, system=system, temperature=0.3)

    async def _extract_components(self, html_pages: dict[str, str], structure: dict) -> list[dict]:
        """Ask LLM to extract reusable components with placeholders."""
        # Use the first/main page
        main_html = ""
        for name, html in html_pages.items():
            main_html = self._truncate_html(html, max_chars=8000)
            break

        section_order = structure.get("section_order", [])

        prompt = f"""Extract reusable components from this HTML.

HTML:
{main_html}

Known sections: {section_order}

For each component:
1. Identify the section type (hero, nav, features, cta, testimonials, pricing, footer, etc.)
2. Create a reusable HTML template with {{{{placeholder}}}} markers for dynamic content
3. List all placeholder variable names

Return a JSON array:
[
  {{
    "name": "hero-centered",
    "category": "hero",
    "description": "Centered hero with headline, subtitle, and CTA button",
    "html_template": "<section class=\\"..\\">\\n  <h1>{{{{headline}}}}</h1>\\n  <p>{{{{subtitle}}}}</p>\\n  <a href=\\"{{{{cta_link}}}}\\">{{{{cta_text}}}}</a>\\n</section>",
    "variables": ["headline", "subtitle", "cta_link", "cta_text"],
    "tags": ["centered", "cta"]
  }}
]

Extract 4-8 key components. Use Tailwind CSS classes where possible."""

        system = "You are a frontend component architect. Extract reusable HTML components with template variables."
        result = await self.ask_llm_json(prompt, system=system, temperature=0.3, max_tokens=6000)

        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "error" not in result:
            # Maybe wrapped in a key
            for key in ("components", "items", "result"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    async def _extract_style(self, html_pages: dict[str, str]) -> dict:
        """Ask LLM to extract the style patterns."""
        combined = ""
        for name, html in html_pages.items():
            truncated = self._truncate_html(html, max_chars=4000)
            combined += f"\n\n=== {name} ===\n{truncated}"

        prompt = f"""Analyze the visual style of this website HTML.

{combined}

Extract:
1. Color scheme (primary, secondary, accent, background, text colors)
2. Font stack / typography approach
3. Spacing approach (compact, normal, spacious)
4. CSS class patterns used (Tailwind, Bootstrap, custom)

Return JSON:
{{
  "name": "style-name",
  "description": "Brief style description",
  "css_classes": ["key", "css", "classes", "used"],
  "color_scheme": {{
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "background": "#hex",
    "text": "#hex"
  }},
  "font_stack": "sans-serif / serif / mono",
  "spacing": "normal"
}}"""

        system = "You are a CSS/design analyst. Extract visual style patterns."
        result = await self.ask_llm_json(prompt, system=system, temperature=0.3)
        if "error" in result:
            return {}
        return result

    # ── Utilities ────────────────────────────────────────

    @staticmethod
    def _truncate_html(html: str, max_chars: int = 6000) -> str:
        """Truncate HTML intelligently — strip scripts, styles, excess whitespace."""
        # Remove script/style blocks
        html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
        # Remove HTML comments
        html = re.sub(r"<!--[\s\S]*?-->", "", html)
        # Collapse whitespace
        html = re.sub(r"\s+", " ", html).strip()
        # Truncate
        if len(html) > max_chars:
            html = html[:max_chars] + "\n<!-- TRUNCATED -->"
        return html
