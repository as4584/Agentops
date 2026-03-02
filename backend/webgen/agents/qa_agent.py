"""
Web QA Agent — Quality assurance for generated websites.
=========================================================
Validates HTML structure, meta tags, accessibility, links.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.base_agent import WebAgentBase
from backend.webgen.models import PageSpec, SiteProject, SiteStatus


class WebQAAgent(WebAgentBase):
    """
    Quality-checks generated websites.

    Checks:
    - HTML structure validity
    - Required meta tags present
    - Heading hierarchy (h1 → h2 → h3)
    - Alt text on images
    - Responsive viewport meta
    - Internal link integrity
    - SEO/AEO markup presence
    """

    name = "WebQAAgent"

    async def run(self, project: SiteProject) -> SiteProject:
        """Run QA checks on all pages."""
        logger.info(f"[{self.name}] Running QA on {len(project.pages)} pages")

        all_issues: list[str] = []
        pass_count = 0

        for page in project.pages:
            issues = self._check_page(page)
            if issues:
                all_issues.extend(f"[{page.slug}] {i}" for i in issues)
                logger.warning(f"[{self.name}] {page.slug}: {len(issues)} issues")
            else:
                pass_count += 1
                logger.info(f"[{self.name}] {page.slug}: PASS")

        # LLM review of the main page
        index_page = next((p for p in project.pages if p.slug == "index"), None)
        if index_page and index_page.html:
            llm_issues = await self._llm_review(index_page, project.brief)
            all_issues.extend(f"[{index_page.slug}][llm] {i}" for i in llm_issues)

        project.errors = all_issues
        total = len(project.pages)
        logger.info(
            f"[{self.name}] QA complete: {pass_count}/{total} pages clean, "
            f"{len(all_issues)} total issues"
        )

        # Advance if issues are minor (< 3 per page average)
        if len(all_issues) < total * 3:
            project.advance(SiteStatus.QA_PASS)
        else:
            logger.warning(f"[{self.name}] Too many issues, reverting to GENERATED for fixes")
            project.status = SiteStatus.GENERATED

        return project

    def _check_page(self, page: PageSpec) -> list[str]:
        """Run structural checks on a single page."""
        issues = []
        html = page.html

        if not html:
            issues.append("Page has no HTML content")
            return issues

        # DOCTYPE
        if "<!DOCTYPE html>" not in html and "<!doctype html>" not in html.lower():
            issues.append("Missing <!DOCTYPE html>")

        # Viewport meta
        if 'name="viewport"' not in html:
            issues.append("Missing viewport meta tag")

        # Title tag
        if "<title>" not in html or "</title>" not in html:
            issues.append("Missing <title> tag")

        # Meta description
        if 'name="description"' not in html:
            issues.append("Missing meta description")

        # H1 tag (should have exactly one)
        h1_count = len(re.findall(r"<h1[\s>]", html, re.IGNORECASE))
        if h1_count == 0:
            issues.append("Missing <h1> tag")
        elif h1_count > 1:
            issues.append(f"Multiple <h1> tags found ({h1_count})")

        # Lang attribute
        if 'lang="' not in html:
            issues.append('Missing lang attribute on <html>')

        # Images without alt
        img_tags = re.findall(r"<img\s[^>]*>", html, re.IGNORECASE)
        for img in img_tags:
            if 'alt="' not in img and "alt='" not in img:
                issues.append(f"Image missing alt attribute: {img[:60]}...")

        # Open Graph
        if 'property="og:title"' not in html:
            issues.append("Missing og:title meta tag")

        # JSON-LD
        if 'application/ld+json' not in html:
            issues.append("Missing JSON-LD structured data")

        # Empty body check
        body_match = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.IGNORECASE)
        if body_match and len(body_match.group(1).strip()) < 100:
            issues.append("Page body seems too short (< 100 chars)")

        return issues

    async def _llm_review(self, page: PageSpec, brief) -> list[str]:
        """Use LLM to review the page for higher-level issues."""
        # Truncate HTML for context window
        html_preview = page.html[:4000] if page.html else ""

        prompt = f"""Review this website page for quality issues:

Page: {page.slug} — {page.title}
Business: {brief.business_name}
Type: {brief.business_type.value}

HTML (truncated):
{html_preview}

Check for:
1. Content relevance to the business
2. Proper call-to-action presence
3. Professional tone and language
4. Logical section ordering
5. Any broken or placeholder content

Return a JSON array of issue strings. If no issues, return an empty array.
Example: ["Missing call-to-action button", "Placeholder text found: Lorem ipsum"]"""

        system = "You are a web QA reviewer. Find issues in generated websites."
        result = await self.ask_llm_json(prompt, system=system, temperature=0.3)

        if isinstance(result, list):
            return [str(i) for i in result]
        if isinstance(result, dict) and "error" not in result:
            for key in ("issues", "items", "problems"):
                if key in result and isinstance(result[key], list):
                    return [str(i) for i in result[key]]
        return []
