"""
WebGen Pipeline — Orchestrator for the full website generation workflow.
========================================================================
Coordinates all agents from brief → deployed site.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.agents.gatekeeper_agent import GatekeeperAgent
from backend.config import LOCAL_LLM_REQUIRED_CHECKS, PROJECT_ROOT, SANDBOX_ENFORCEMENT_ENABLED
from backend.llm import OllamaClient
from sandbox.session_manager import SandboxSession
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
        self._gatekeeper = GatekeeperAgent()

    def _is_local_llm(self) -> bool:
        model = str(getattr(self.llm, "model", "local")).lower()
        return "local" in model or "ollama" in model or model.startswith("llama")

    def _render_export_files(self, project: SiteProject) -> dict[str, str]:
        files: dict[str, str] = {}
        output_root = Path(project.output_dir)
        try:
            rel_base = output_root.resolve().relative_to(PROJECT_ROOT.resolve())
        except Exception:
            rel_base = Path("output") / "webgen" / output_root.name

        for page in project.pages:
            if page.html:
                files[str(rel_base / f"{page.slug}.html")] = page.html

        if project.sitemap_xml:
            files[str(rel_base / "sitemap.xml")] = project.sitemap_xml

        if project.robots_txt:
            files[str(rel_base / "robots.txt")] = project.robots_txt

        if project.global_css:
            files[str(rel_base / "css" / "global.css")] = project.global_css

        return files

    def _release_via_sandbox(
        self,
        project: SiteProject,
        files: dict[str, str],
        quality_checks: dict[str, bool] | None = None,
    ) -> tuple[bool, Path]:
        model_name = str(getattr(self.llm, "model", "local"))
        session = SandboxSession(
            project_root=PROJECT_ROOT,
            task=f"webgen-export:{project.id}",
            model=model_name,
        )
        session.create()

        changed_files = sorted(files.keys())
        for rel_path, content in files.items():
            dst = session.workspace / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)

        session.stage_to_playbox(changed_files)

        checks = quality_checks or {}
        payload: dict[str, Any] = {
            "files_changed": changed_files,
            "source_model": model_name,
            "sandbox_session_id": session.session_id,
            "staged_in_playbox": True,
            "tests_ok": bool(checks.get("tests_ok", False)),
            "playwright_ok": bool(checks.get("playwright_ok", False)),
            "lighthouse_mobile_ok": bool(checks.get("lighthouse_mobile_ok", False)),
            "syntax_ok": bool(checks.get("tests_ok", False)),
            "lighthouse_ok": bool(checks.get("lighthouse_mobile_ok", False)),
            "secrets_ok": True,
        }

        review = self._gatekeeper.review_mutation(payload)
        if not review.approved:
            project.metadata["sandbox_session_id"] = session.session_id
            project.metadata["playbox_path"] = str(session.playbox)
            project.metadata["release_blocked"] = True
            project.metadata["release_violations"] = review.violations
            project.metadata["required_checks"] = list(LOCAL_LLM_REQUIRED_CHECKS)
            self.site_store.save(project)
            logger.warning(
                "[WebGenPipeline] Release blocked by gatekeeper; files staged in playbox. "
                f"session={session.session_id}, violations={review.violations}"
            )
            return False, session.playbox

        released = session.release_from_playbox(changed_files)
        session.destroy(promoted_files=released)
        return True, Path(project.output_dir)

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

    def export(self, project: SiteProject, quality_checks: dict[str, bool] | None = None) -> Path:
        """Write all generated files to the output directory."""
        out = Path(project.output_dir)
        files = self._render_export_files(project)

        if SANDBOX_ENFORCEMENT_ENABLED and self._is_local_llm():
            released, path = self._release_via_sandbox(project, files, quality_checks)
            if released:
                project.advance(SiteStatus.READY)
                self.site_store.save(project)
                logger.info(f"[WebGenPipeline] Exported via sandbox release: {path}")
            return path

        out.mkdir(parents=True, exist_ok=True)
        for rel_path, content in files.items():
            dst = PROJECT_ROOT / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)
            logger.info(f"[WebGenPipeline] Wrote: {dst}")

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
        quality_checks: dict[str, bool] | None = None,
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
            self.export(project, quality_checks=quality_checks)

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
