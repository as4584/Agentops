"""
WebGen Pipeline — Orchestrator for the full website generation workflow.
========================================================================
Coordinates all agents from brief → deployed site.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.aeo_agent import AEOAgent
from backend.webgen.agents.page_generator import PageGeneratorAgent
from backend.webgen.agents.qa_agent import WebQAAgent
from backend.webgen.agents.seo_agent import SEOAgent
from backend.webgen.agents.site_planner import SitePlannerAgent
from backend.webgen.agents.template_learner import TemplateLearnerAgent
from backend.webgen.models import ClientBrief, SiteProject, SiteStatus
from backend.webgen.site_store import SiteStore
from backend.webgen.template_store import TemplateStore


class WebGenPipeline:
    """
    End-to-end website generation pipeline.

    Workflow:
    1. learn_site()  — Learn templates from existing sites (optional)
    2. create()      — Create a new project from a brief
    3. plan()        — Plan site structure
    4. generate()    — Generate all pages
    5. seo()         — SEO optimization
    6. aeo()         — AEO optimization
    7. qa()          — Quality assurance
    8. export()      — Write files to disk

    Or use quick_generate() for the full pipeline in one call.
    """

    def __init__(
        self,
        llm: Optional[OllamaClient] = None,
        template_store: Optional[TemplateStore] = None,
        site_store: Optional[SiteStore] = None,
        output_base: str | Path | None = None,
    ) -> None:
        self.llm = llm or OllamaClient()
        self.template_store = template_store or TemplateStore()
        self.site_store = site_store or SiteStore()

        if output_base is None:
            output_base = Path(__file__).resolve().parent.parent.parent / "output" / "webgen"
        self.output_base = Path(output_base)

        # Initialize agents
        self.template_learner = TemplateLearnerAgent(self.llm, self.template_store)
        self.planner = SitePlannerAgent(self.llm, self.template_store)
        self.generator = PageGeneratorAgent(self.llm, self.template_store)
        self.seo_agent = SEOAgent(self.llm)
        self.aeo_agent = AEOAgent(self.llm)
        self.qa_agent = WebQAAgent(self.llm)

    # ── Template learning ────────────────────────────────

    async def learn_site(self, source: str, business_type: str = "custom", name: str = ""):
        """Learn a template from an existing site (directory path)."""
        return await self.template_learner.run(source, business_type, name)

    async def learn_html(self, html: str, source_name: str = "pasted",
                          business_type: str = "custom", name: str = ""):
        """Learn a template from raw HTML content."""
        return await self.template_learner.learn_from_html(html, source_name, business_type, name)

    # ── Project lifecycle ────────────────────────────────

    def create(self, brief: ClientBrief, base_url: str = "") -> SiteProject:
        """Create a new project from a client brief."""
        project = SiteProject(brief=brief)
        if base_url:
            project.metadata["base_url"] = base_url

        slug = brief.business_name.lower().replace(" ", "-").replace("'", "")
        project.output_dir = str(self.output_base / slug)

        self.site_store.save(project)
        logger.info(f"[WebGenPipeline] Created project {project.id} for {brief.business_name}")
        return project

    async def plan(self, project: SiteProject) -> SiteProject:
        """Plan the site structure."""
        project = await self.planner.run(project)
        self.site_store.save(project)
        return project

    async def generate(self, project: SiteProject) -> SiteProject:
        """Generate HTML for all pages."""
        project = await self.generator.run(project)
        self.site_store.save(project)
        return project

    async def seo(self, project: SiteProject) -> SiteProject:
        """Run SEO optimization."""
        project = await self.seo_agent.run(project)
        self.site_store.save(project)
        return project

    async def aeo(self, project: SiteProject) -> SiteProject:
        """Run AEO optimization."""
        project = await self.aeo_agent.run(project)
        self.site_store.save(project)
        return project

    async def qa(self, project: SiteProject) -> SiteProject:
        """Run quality assurance."""
        project = await self.qa_agent.run(project)
        self.site_store.save(project)
        return project

    def export(self, project: SiteProject) -> Path:
        """Write all generated files to the output directory."""
        out = Path(project.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Write HTML pages
        for page in project.pages:
            if page.html:
                page_path = out / f"{page.slug}.html"
                page_path.write_text(page.html)
                logger.info(f"[WebGenPipeline] Wrote: {page_path}")

        # Write sitemap.xml
        if project.sitemap_xml:
            (out / "sitemap.xml").write_text(project.sitemap_xml)

        # Write robots.txt
        if project.robots_txt:
            (out / "robots.txt").write_text(project.robots_txt)

        # Write global CSS
        if project.global_css:
            css_dir = out / "css"
            css_dir.mkdir(exist_ok=True)
            (css_dir / "global.css").write_text(project.global_css)

        project.advance(SiteStatus.READY)
        self.site_store.save(project)
        logger.info(f"[WebGenPipeline] Exported to: {out}")
        return out

    # ── Full pipeline ────────────────────────────────────

    async def quick_generate(
        self,
        brief: ClientBrief,
        base_url: str = "",
        export: bool = True,
    ) -> SiteProject:
        """
        Run the full pipeline from brief to exported site.

        This is the main entry point for automated site generation.
        """
        logger.info(f"[WebGenPipeline] Starting full pipeline for: {brief.business_name}")

        project = self.create(brief, base_url)

        # Plan → Generate → SEO → AEO → QA
        project = await self.plan(project)
        project = await self.generate(project)
        project = await self.seo(project)
        project = await self.aeo(project)
        project = await self.qa(project)

        if export:
            self.export(project)

        logger.info(
            f"[WebGenPipeline] Pipeline complete: {project.id} "
            f"({len(project.pages)} pages, status={project.status.value})"
        )
        return project

    # ── Info helpers ──────────────────────────────────────

    def list_projects(self) -> list[SiteProject]:
        return self.site_store.list_projects()

    def get_project(self, project_id: str) -> Optional[SiteProject]:
        return self.site_store.load(project_id)

    def list_templates(self, business_type: str = ""):
        return self.template_store.list_templates(business_type)

    def list_components(self, category: str = "", business_type: str = ""):
        return self.template_store.list_components(category, business_type)
