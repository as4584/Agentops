"""
SEO Agent — Search Engine Optimization for generated pages.
============================================================
Adds meta tags, schema.org JSON-LD, Open Graph,
sitemaps, robots.txt, and internal linking.
"""

from __future__ import annotations

import json

from backend.utils import logger
from backend.webgen.agents.base_agent import WebAgentBase
from backend.webgen.models import (
    PageSpec,
    SEOProfile,
    SiteProject,
    SiteStatus,
)


class SEOAgent(WebAgentBase):
    """
    Optimizes pages for search engines.

    Process:
    1. Generate SEO profiles for each page via LLM
    2. Inject meta tags, OG tags, JSON-LD into HTML
    3. Generate sitemap.xml and robots.txt
    4. Add internal cross-links between pages
    """

    name = "SEOAgent"

    async def run(self, project: SiteProject) -> SiteProject:
        """Run SEO optimization on all pages."""
        brief = project.brief
        logger.info(f"[{self.name}] Optimizing SEO for {len(project.pages)} pages")

        # Generate SEO profiles
        for page in project.pages:
            logger.info(f"[{self.name}] SEO for: {page.slug}")
            seo = await self._generate_seo_profile(page, brief)
            page.seo = seo
            page.html = self._inject_seo(page.html, seo, brief)

        # Generate sitemap
        base_url = project.metadata.get("base_url", f"https://{brief.business_name.lower().replace(' ', '')}.com")
        project.sitemap_xml = self._generate_sitemap(project.pages, base_url)
        project.robots_txt = self._generate_robots(base_url)

        project.advance(SiteStatus.SEO_PASS)
        logger.info(f"[{self.name}] SEO optimization complete")
        return project

    async def _generate_seo_profile(self, page: PageSpec, brief) -> SEOProfile:
        """Generate SEO metadata for a page via LLM."""
        prompt = f"""Generate SEO metadata for this webpage:

Page: {page.slug} — {page.title}
Purpose: {page.purpose}
Business: {brief.business_name}
Type: {brief.business_type.value}
Services: {", ".join(brief.services) if brief.services else "Various"}
Location: {brief.address or "Not specified"}

Generate:
1. SEO title (50-60 characters, includes business name)
2. Meta description (150-160 characters, includes call-to-action)
3. Keywords (5-8 relevant keywords)
4. Open Graph title and description
5. Schema.org type (e.g., LocalBusiness, WebPage, Service, AboutPage)
6. Schema.org JSON-LD structured data

Return JSON:
{{
  "title": "SEO title",
  "meta_description": "Meta description",
  "keywords": ["keyword1", "keyword2"],
  "og_title": "OG title",
  "og_description": "OG description",
  "schema_type": "LocalBusiness",
  "schema_json_ld": {{...}}
}}"""

        system = "You are an SEO specialist. Generate optimized metadata following current best practices."
        result = await self.ask_llm_json(prompt, system=system, temperature=0.4)

        if "error" in result:
            logger.warning(f"[{self.name}] SEO profile parse failed for {page.slug}")
            return SEOProfile(
                title=f"{page.title} | {brief.business_name}",
                meta_description=brief.tagline or brief.description[:160],
            )

        return SEOProfile(
            title=result.get("title", page.title),
            meta_description=result.get("meta_description", ""),
            keywords=result.get("keywords", []),
            og_title=result.get("og_title", result.get("title", "")),
            og_description=result.get("og_description", result.get("meta_description", "")),
            schema_type=result.get("schema_type", "WebPage"),
            schema_json_ld=result.get("schema_json_ld", {}),
        )

    def _inject_seo(self, html: str, seo: SEOProfile, brief) -> str:
        """Inject SEO tags into the page HTML."""
        if not html:
            return html

        seo_tags = []

        # Title
        if seo.title:
            html = html.replace(
                f"<title>{brief.business_name}</title>",
                f"<title>{seo.title}</title>",
            )
            if "<title>" not in html:
                seo_tags.append(f"  <title>{seo.title}</title>")

        # Meta description
        if seo.meta_description:
            seo_tags.append(f'  <meta name="description" content="{self._escape_attr(seo.meta_description)}">')

        # Keywords
        if seo.keywords:
            seo_tags.append(f'  <meta name="keywords" content="{", ".join(seo.keywords)}">')

        # Open Graph
        if seo.og_title:
            seo_tags.append(f'  <meta property="og:title" content="{self._escape_attr(seo.og_title)}">')
        if seo.og_description:
            seo_tags.append(f'  <meta property="og:description" content="{self._escape_attr(seo.og_description)}">')
        seo_tags.append('  <meta property="og:type" content="website">')

        # JSON-LD
        if seo.schema_json_ld:
            ld_json = json.dumps(seo.schema_json_ld, indent=2)
            seo_tags.append(f'  <script type="application/ld+json">\n{ld_json}\n  </script>')

        # Canonical
        if seo.canonical_url:
            seo_tags.append(f'  <link rel="canonical" href="{seo.canonical_url}">')

        # Inject before </head>
        if seo_tags:
            injection = "\n" + "\n".join(seo_tags) + "\n"
            html = html.replace("</head>", f"{injection}</head>")

        return html

    def _generate_sitemap(self, pages: list[PageSpec], base_url: str) -> str:
        """Generate sitemap.xml."""
        urls = []
        for page in pages:
            priority = "1.0" if page.slug == "index" else "0.8"
            urls.append(
                f"  <url>\n"
                f"    <loc>{base_url}/{page.slug}.html</loc>\n"
                f"    <priority>{priority}</priority>\n"
                f"    <changefreq>weekly</changefreq>\n"
                f"  </url>"
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n"
            "</urlset>"
        )

    @staticmethod
    def _generate_robots(base_url: str) -> str:
        """Generate robots.txt."""
        return f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"

    @staticmethod
    def _escape_attr(text: str) -> str:
        """Escape text for HTML attribute values."""
        return text.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
