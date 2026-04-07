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
        self.design_ctx = None  # injected by pipeline

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
        critique: list[str] | None = None,
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

        design_hint = ""
        if self.design_ctx:
            design_hint = (
                f"\nDesign system: {self.design_ctx.style_name} — {self.design_ctx.style_keywords}"
                f"\nColors: primary={self.design_ctx.primary_color}, "
                f"secondary={self.design_ctx.secondary_color}, accent={self.design_ctx.accent_color}"
                f"\nFonts: heading='{self.design_ctx.heading_font}', body='{self.design_ctx.body_font}'"
                f"\nEffects hint: {self.design_ctx.effects_hint}"
            )
        critique_block = ""
        if critique:
            critique_block = (
                "\n\nCRITIQUE FROM PREVIOUS VERSION — fix ALL of these before returning:\n"
                + "".join(f"  ✗ {v}\n" for v in critique)
                + "This regeneration MUST address every violation above."
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
{design_hint}

Navigation items:
{nav_context}
{template_context}

Requirements:
- Use Tailwind CSS utility classes + inline <style> when Tailwind can't express the effect
- Semantic HTML5 elements
- Mobile-first responsive design
- Component type: {section.component_type}
- Use the exact brand colors from the design system above as CSS vars or Tailwind arbitrary values
- Include aria labels for accessibility
- Hero sections: heading MUST have `style="animation: fadeInUp 0.8s ease-out both"`
- All <button> and <a class="btn"> MUST have `class="... transition-all duration-300 hover:scale-105 hover:shadow-xl"`
- Feature/service cards MUST use class `glass-card` (defined in global.css)
{critique_block}
Return ONLY the HTML for this section, no explanation."""

        system = (
            "You are a senior frontend engineer building premium, award-winning websites. "
            "Generate VISUALLY STUNNING HTML using Tailwind CSS + inline <style> for animations. "
            "Output only HTML — no markdown fences, no explanation.\n"
            "VISUAL MANDATES (all required — creativity is rewarded, rigidity is penalized):\n"
            "- ANIMATIONS: Hero headings MUST have `style='animation: fadeInUp 0.8s ease-out both'`. "
            "Add staggered delays on sub-elements (0.2s, 0.4s). Feel free to invent bespoke keyframes.\n"
            "- GRADIENTS: Hero/header backgrounds MUST use multi-stop gradients e.g. "
            "`background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-secondary) 60%, #0f172a 100%)`. "
            "Gradient text on h1: `background: linear-gradient(90deg,var(--color-primary),var(--color-accent)); "
            "-webkit-background-clip:text; -webkit-text-fill-color:transparent`\n"
            "- GLASS CARDS: Service/feature cards MUST use class `glass-card` (defined in global CSS). "
            "Add `hover:-translate-y-2 transition-transform duration-300` to every card.\n"
            "- MICRO-INTERACTIONS: ALL buttons → `transition-all duration-300 hover:scale-105 hover:shadow-2xl`. "
            "ALL nav links → `hover:text-[var(--color-accent)] transition-colors duration-200`.\n"
            "- EFFECTS HINT: If an effects_hint is in the prompt, implement it — never ignore it.\n"
            "- CREATIVITY: You have freedom within the design system. Surprise with layout, depth, color.\n"
            "STRUCTURE RULES (mandatory):\n"
            "- Use <nav> for ALL navigation menus. NEVER use <div> as a navigation container.\n"
            "- Use <header> for page/section headers.\n"
            "- Use <main> to wrap primary content.\n"
            "- Use <footer> for footer regions.\n"
            "- Use <section> for distinct content areas. Each section MUST have an accessible heading.\n"
            "- Use <article> for self-contained content blocks.\n"
            "- Use <h1> exactly once per page. Use <h2>/<h3> for subsections.\n"
            "- Include at most 3 CTAs per section and at most 7 nav links.\n"
            "- Interactive CTAs: buttons need `role='button'` and `aria-label`."
        )

        temperature = 0.85 if critique else 0.7
        html = await self.ask_llm(prompt, system=system, temperature=temperature, max_tokens=3500)

        # Clean any markdown artifacts
        html = html.strip()
        if html.startswith("```"):
            lines = html.split("\n")
            html = "\n".join(lines[1:])
        if html.endswith("```"):
            html = html[:-3].strip()

        return html

    async def _regenerate_with_critique(
        self,
        page: PageSpec,
        brief: ClientBrief,
        nav_items: list[dict],
        global_css: str,
        violations: list[str],
    ) -> str:
        """
        Re-generate a full page with UX violation critique fed back to the LLM.
        Higher temperature for creative variation — find the art, not the formula.
        """
        sections_html = []
        for section in sorted(page.sections, key=lambda s: s.order):
            html = await self._generate_section(section, brief, nav_items, critique=violations)
            section.html = html
            sections_html.append(html)

        body = "\n\n".join(sections_html)
        return self._wrap_page(
            title=page.title or brief.business_name,
            body=body,
            global_css=global_css,
            brief=brief,
        )

    async def _generate_global_css(self, brief: ClientBrief) -> str:
        """Generate global CSS custom properties based on brand."""
        if self.design_ctx:
            primary = self.design_ctx.primary_color
            secondary = self.design_ctx.secondary_color
            accent = self.design_ctx.accent_color
            background = self.design_ctx.background_color
            foreground = self.design_ctx.foreground_color
            heading_font = self.design_ctx.heading_font
            body_font = self.design_ctx.body_font
        else:
            colors = brief.colors or {}
            primary = colors.get("primary", "#2563eb")
            secondary = colors.get("secondary", "#1e40af")
            accent = colors.get("accent", "#f59e0b")
            background = "#F8FAFC"
            foreground = "#1E293B"
            heading_font = "Poppins"
            body_font = "Open Sans"

        return f"""/* WebGen Global Styles */
:root {{
  --color-primary: {primary};
  --color-secondary: {secondary};
  --color-accent: {accent};
  --color-bg: {background};
  --color-fg: {foreground};
  --font-heading: '{heading_font}', system-ui, -apple-system, sans-serif;
  --font-body: '{body_font}', system-ui, -apple-system, sans-serif;
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
  transform: scale(1.05);
  box-shadow: 0 20px 40px rgba(0,0,0,0.2);
}}

/* ── Premium animation keyframes ─────────────────── */
@keyframes fadeInUp {{
  from {{ opacity: 0; transform: translateY(32px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes slideInLeft {{
  from {{ opacity: 0; transform: translateX(-40px); }}
  to   {{ opacity: 1; transform: translateX(0); }}
}}

@keyframes glowPulse {{
  0%, 100% {{ box-shadow: 0 0 20px {accent}4d; }}
  50%       {{ box-shadow: 0 0 40px {accent}b3; }}
}}

@keyframes gradientShift {{
  0%   {{ background-position: 0% 50%; }}
  50%  {{ background-position: 100% 50%; }}
  100% {{ background-position: 0% 50%; }}
}}

/* ── Glassmorphism card ───────────────────────────── */
.glass-card {{
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 1rem;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}}

.glass-card:hover {{
  transform: translateY(-8px);
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.3);
}}

/* ── Gradient text utility ───────────────────────── */
.gradient-text {{
  background: linear-gradient(90deg, {primary}, {accent});
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

/* ── Animated hero gradient background ──────────── */
.hero-gradient {{
  background: linear-gradient(135deg, {primary} 0%, {secondary} 50%, #0f172a 100%);
  background-size: 200% 200%;
  animation: gradientShift 8s ease infinite;
}}

/* ── Scroll-reveal (JS-free fade) ────────────────── */
.reveal {{
  opacity: 0;
  transform: translateY(24px);
  transition: opacity 0.7s ease, transform 0.7s ease;
}}

.reveal.visible {{
  opacity: 1;
  transform: translateY(0);
}}
"""

    def _wrap_page(self, title: str, body: str, global_css: str, brief: ClientBrief) -> str:
        """Wrap section HTML in a full page document."""
        fonts_link = ""
        if self.design_ctx and self.design_ctx.google_fonts_css_import:
            hf = self.design_ctx.heading_font.replace(" ", "+")
            bf = self.design_ctx.body_font.replace(" ", "+")
            fonts_link = f'  <link href="https://fonts.googleapis.com/css2?family={hf}:wght@400;600;700&family={bf}:wght@300;400;500&display=swap" rel="stylesheet">\n'
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{brief.tagline}">
  <script src="https://cdn.tailwindcss.com"></script>
{fonts_link}  <style>
{global_css}
  </style>
</head>
<body class="min-h-screen bg-white">

{body}

</body>
</html>"""
