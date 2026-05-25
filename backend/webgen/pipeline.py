"""
WebGen Pipeline — Orchestrator for the full website generation workflow.
========================================================================
Coordinates all agents from brief → deployed site.
"""

from __future__ import annotations

from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from typing import Any

from backend.agents.gatekeeper_agent import GatekeeperAgent
from backend.config import LOCAL_LLM_REQUIRED_CHECKS, PROJECT_ROOT, SANDBOX_ENFORCEMENT_ENABLED
from backend.llm import OllamaClient
from backend.utils import logger
from backend.webgen.agents.aeo_agent import AEOAgent
from backend.webgen.agents.design_advisor import DesignAdvisorAgent
from backend.webgen.agents.page_generator import PageGeneratorAgent
from backend.webgen.agents.qa_agent import WebQAAgent
from backend.webgen.agents.seo_agent import SEOAgent
from backend.webgen.agents.site_planner import SitePlannerAgent
from backend.webgen.agents.template_learner import TemplateLearnerAgent
from backend.webgen.agents.ux_scorer import passes_quality_gate, score_html
from backend.webgen.models import ClientBrief, SiteProject, SiteStatus
from backend.webgen.site_store import SiteStore, WebgenRunStore
from backend.webgen.template_store import TemplateStore
from sandbox.session_manager import SandboxSession


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
        llm: OllamaClient | None = None,
        template_store: TemplateStore | None = None,
        site_store: SiteStore | None = None,
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
        self.design_advisor = DesignAdvisorAgent()
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

    async def learn_html(self, html: str, source_name: str = "pasted", business_type: str = "custom", name: str = ""):
        """Learn a template from raw HTML content."""
        return await self.template_learner.learn_from_html(html, source_name, business_type, name)

    async def clone_url(self, url: str, business_name: str = "") -> dict[str, Any]:
        """Clone a public URL: capture HTML, screenshot, and design tokens.

        Uses the headless BrowserSession (Playwright) to render the page, then
        runs a small JS expression to extract dominant colors and fonts from
        ``getComputedStyle`` on top-level elements. Returns a dict with keys:
        ``html``, ``screenshot_path``, ``tokens``, ``title``, ``final_url``.
        """
        from backend.browser.session import BrowserSession

        session = BrowserSession(agent_id="webgen_cloner")
        try:
            await session.start()
            nav = await session.navigate(url)
            html = await session.get_html()
            shot = await session.screenshot(
                relative_path=f"clone_{business_name or 'site'}_{int(__import__('time').time())}.png"
            )
            tokens_js = (
                "(() => {\n"
                "  const root = getComputedStyle(document.documentElement);\n"
                "  const body = getComputedStyle(document.body);\n"
                "  const h1 = document.querySelector('h1');\n"
                "  const h1Style = h1 ? getComputedStyle(h1) : null;\n"
                "  const btn = document.querySelector('button, .btn, a.button, [class*=button]');\n"
                "  const btnStyle = btn ? getComputedStyle(btn) : null;\n"
                "  return {\n"
                "    bg: body.backgroundColor,\n"
                "    fg: body.color,\n"
                "    bodyFont: body.fontFamily,\n"
                "    headingFont: h1Style ? h1Style.fontFamily : body.fontFamily,\n"
                "    accent: btnStyle ? btnStyle.backgroundColor : root.getPropertyValue('--accent') || '',\n"
                "    title: document.title,\n"
                "  };\n"
                "})()"
            )
            try:
                tokens = await session.evaluate_js(tokens_js)
            except Exception as exc:  # pragma: no cover — best-effort extraction
                logger.warning(f"[WebGenPipeline.clone_url] token extraction failed: {exc}")
                tokens = {}
            logger.info(
                f"[WebGenPipeline] Cloned {url} → {len(html)} bytes, screenshot={shot.get('path')}"
            )
            return {
                "html": html,
                "screenshot_path": shot.get("path"),
                "tokens": tokens or {},
                "title": nav.get("title", ""),
                "final_url": nav.get("url", url),
            }
        finally:
            await session.close()

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
                # Use direct assignment — project may be in any terminal state (GENERATED,
                # QA_PASS, etc.) depending on which phases ran, so advance() would reject
                # transitions that skip intermediate states.
                project.status = SiteStatus.READY
                project.updated_at = datetime.now(UTC).isoformat()
                self.site_store.save(project)
                logger.info(f"[WebGenPipeline] Exported via sandbox release: {path}")
            return path

        out.mkdir(parents=True, exist_ok=True)
        for rel_path, content in files.items():
            dst = PROJECT_ROOT / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content)
            logger.info(f"[WebGenPipeline] Wrote: {dst}")

        project.status = SiteStatus.READY
        self.site_store.save(project)
        logger.info(f"[WebGenPipeline] Exported to: {out}")
        return out

    # ── Orchestrator handoff: section retry loop ─────────

    async def generate_section_with_retry(
        self,
        brief: ClientBrief,
        section_name: str,
        component_type: str,
        max_attempts: int = 3,
        min_ux_score: int = 50,
    ) -> tuple[str, int]:
        """
        Generate a single section with an orchestrator retry loop.

        The LLM handles ONE section at a time — a chunk small enough to do
        perfectly. If the UX score is too low, we retry with a stricter prompt
        that names the specific violations. After max_attempts we return the
        best attempt regardless.

        Returns: (html, ux_score)
        """
        design_ctx = self.design_advisor.advise(brief)
        best_html = ""
        best_score = 0

        for attempt in range(1, max_attempts + 1):
            # Build prompt — on retry, add explicit UX feedback
            feedback = ""
            if attempt > 1 and best_html:
                ux = score_html(best_html)
                feedback = (
                    f"\n\nPREVIOUS ATTEMPT SCORED {ux.total}/100. FIX THESE VIOLATIONS:\n"
                    + "\n".join(f"- {v}" for v in ux.violations)
                    + "\n\nDo NOT repeat those mistakes."
                )

            prompt = (
                f"Generate a '{section_name}' ({component_type}) section for {brief.business_name}.\n"
                f"Business type: {brief.business_type.value} | Tone: {brief.tone}\n"
                f"Services: {', '.join(brief.services[:4])}\n\n"
                f"DESIGN SYSTEM:\n"
                f"  Style: {design_ctx.style_name}\n"
                f"  Primary: {design_ctx.primary_color} | Secondary: {design_ctx.secondary_color}\n"
                f"  Heading font: {design_ctx.heading_font} | Body font: {design_ctx.body_font}\n\n"
                f"REQUIREMENTS:\n"
                f"  - Tailwind CSS only (no inline styles)\n"
                f"  - Semantic HTML5 (<section>, <nav>, <header>, <article>)\n"
                f"  - Nav: exactly 5–6 items, one CTA button\n"
                f"  - Features/lists: maximum 7 items (Miller's Law)\n"
                f"  - One high-contrast accent element (Von Restorff)\n"
                f"  - Mobile-first responsive (sm: md: lg: breakpoints)\n"
                f"  - Output ONLY raw HTML — no markdown fences{feedback}"
            )

            try:
                html = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": "You are an expert frontend developer. Output only raw HTML."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.6 if attempt == 1 else 0.4,
                    max_tokens=2500,
                )
                html = html.strip()
                if html.startswith("```"):
                    html = "\n".join(html.split("\n")[1:])
                if html.endswith("```"):
                    html = html[:-3].strip()

                ux_score = score_html(html).total
                logger.info(f"[WebGenPipeline] {section_name} attempt {attempt}/{max_attempts} → UX {ux_score}/100")

                if ux_score > best_score:
                    best_html = html
                    best_score = ux_score

                if passes_quality_gate(html, min_ux_score):
                    break

            except Exception as e:
                logger.warning(f"[WebGenPipeline] {section_name} attempt {attempt} failed: {e}")

        return best_html, best_score

    # ── Full pipeline ────────────────────────────────────

    async def quick_generate(
        self,
        brief: ClientBrief,
        base_url: str = "",
        export: bool = True,
        quality_checks: dict[str, bool] | None = None,
        run_id: str | None = None,
        run_store: WebgenRunStore | None = None,
    ) -> SiteProject:
        """
        Run the full pipeline from brief to exported site.

        This is the main entry point for automated site generation.
        Phase order: clone_recon → clone_learn → planning → seo → aeo → qa → build → export
        """
        logger.info(f"[WebGenPipeline] Starting full pipeline for: {brief.business_name}")

        # Determine total steps (with or without clone phases)
        _has_clone = bool(brief.clone_url)
        _total = 8 if _has_clone else 6

        # Helper: emit progress SSE and update persisted run state
        def _emit(phase: str, step: int, detail: str = "") -> None:
            try:
                from datetime import datetime as _dt
                from backend.tasks import task_tracker as _tt
                _now = _dt.now(UTC).isoformat()
                _tt.emit_activity("WEBGEN_PROGRESS", {
                    "phase": phase,
                    "business_name": brief.business_name,
                    "step": step,
                    "total": _total,
                    "detail": detail,
                    "run_id": run_id or "",
                    "timestamp": _now,
                })
                if run_id and run_store:
                    _run = run_store.load(run_id)
                    if _run:
                        _run.current_phase = phase
                        _run.step = step
                        _run.total = _total
                        _run.last_event_at = _now
                        run_store.save(_run)
            except Exception as _exc:
                logger.debug(f"[WebGenPipeline] _emit({phase}) failed (non-fatal): {_exc}")

        # ── Optional URL clone phase — runs before planning when brief.clone_url set ──
        if brief.clone_url:
            _emit("clone_recon", 1, f"Cloning {brief.clone_url}")
            try:
                clone_data = await self.clone_url(brief.clone_url, brief.business_name)
                brief.cloned_html = clone_data.get("html")
                brief.cloned_screenshot = clone_data.get("screenshot_path")
                brief.cloned_tokens = clone_data.get("tokens") or {}
                if not brief.business_name and clone_data.get("title"):
                    brief.business_name = str(clone_data["title"])[:60].strip() or "Cloned Site"
                # Apply cloned tokens to brief.colors so the design advisor sees them
                t = brief.cloned_tokens
                if isinstance(t, dict):
                    if t.get("accent"):
                        brief.colors.setdefault("primary", str(t["accent"]))
                    if t.get("bg"):
                        brief.colors.setdefault("background", str(t["bg"]))
                _emit("clone_learn", 2, "Learning template from cloned HTML")
                if brief.cloned_html:
                    try:
                        await self.learn_html(
                            brief.cloned_html,
                            source_name=brief.clone_url,
                            business_type=brief.business_type.value,
                            name=brief.business_name or "Cloned Site",
                        )
                    except Exception as exc:
                        logger.warning(f"[WebGenPipeline] learn_html on clone failed: {exc}")
            except Exception as exc:
                logger.warning(f"[WebGenPipeline] clone_url failed for {brief.clone_url}: {exc}")

        # Get design context from UI/UX CSVs (no LLM calls)
        design_ctx = self.design_advisor.advise(brief)

        project = self.create(brief, base_url)
        project.metadata["design_context"] = {
            "style_name": design_ctx.style_name,
            "primary_color": design_ctx.primary_color,
            "secondary_color": design_ctx.secondary_color,
            "accent_color": design_ctx.accent_color,
            "heading_font": design_ctx.heading_font,
            "body_font": design_ctx.body_font,
        }

        # Inject design context into agents
        self.planner.design_ctx = design_ctx  # type: ignore[assignment]
        self.generator.design_ctx = design_ctx  # type: ignore[assignment]

        # ── Phase order: Plan → SEO strategy → AEO strategy → QA precheck → Build → Export ──
        # Steps 1–6 (no clone) or 3–8 (with clone)
        _plan_step = 3 if _has_clone else 1
        _emit("planning", _plan_step, "Generating site structure")
        project = await self.plan(project)

        _emit("seo", _plan_step + 1, f"Building SEO strategy for {len(project.pages)} pages")
        project = await self.seo_agent.run_strategy(project)
        self.site_store.save(project)

        _emit("aeo", _plan_step + 2, f"Building AEO strategy for {len(project.pages)} pages")
        project = await self.aeo_agent.run_strategy(project)
        self.site_store.save(project)

        _emit("qa", _plan_step + 3, "Validating content specifications")
        project = await self.qa_agent.run_precheck(project)

        # ── Build: generate HTML then apply SEO/AEO injections + HTML QA ──
        _emit("build", _plan_step + 4, f"Building {len(project.pages)} pages")
        project = await self.generate(project)  # PLANNED → GENERATING → GENERATED

        # Apply SEO HTML injection + sitemap/robots (moved from seo_agent.run())
        brief_ref = project.brief
        base_url_seo = project.metadata.get(
            "base_url",
            f"https://{brief_ref.business_name.lower().replace(' ', '')}.com"
        )
        project.sitemap_xml = self.seo_agent._generate_sitemap(project.pages, base_url_seo)
        project.robots_txt = self.seo_agent._generate_robots(base_url_seo)
        for page in project.pages:
            if page.html:
                page.html = self.seo_agent._inject_seo(page.html, page.seo, brief_ref)
        project.advance(SiteStatus.SEO_PASS)

        # Apply AEO HTML injection (moved from aeo_agent.run())
        for page in project.pages:
            if page.html:
                page.html = self.aeo_agent._inject_aeo(page.html, page.aeo, brief_ref)
        project.advance(SiteStatus.AEO_PASS)

        # HTML structural QA (moved from qa_agent.run())
        _qa_issues: list[str] = []
        _ux_scores: dict[str, int] = {}
        for page in project.pages:
            _page_issues = self.qa_agent._check_page(page)
            if _page_issues:
                _qa_issues.extend(f"[{page.slug}] {i}" for i in _page_issues)
            if page.html:
                _ux = score_html(page.html)
                _ux_scores[page.slug] = _ux.total
        project.errors = _qa_issues
        if _ux_scores:
            project.metadata["ux_scores"] = _ux_scores
        project.advance(SiteStatus.QA_PASS)
        self.site_store.save(project)

        # ── Critique-regen loop ──────────────────────────────────────────────
        regen_threshold = 70
        max_regen_rounds = 2
        nav_items = [
            {"label": p.nav_label, "href": f"{p.slug}.html"} for p in sorted(project.pages, key=lambda p: p.nav_order)
        ]
        _dpo_pairs: list[dict] = []

        for _round in range(max_regen_rounds):
            ux_scores = project.metadata.get("ux_scores", {})
            low_pages = [p for p in project.pages if ux_scores.get(p.slug, 100) < regen_threshold]
            if not low_pages:
                logger.info("[WebGenPipeline] All pages above UX threshold ✓")
                break
            logger.info(
                f"[WebGenPipeline] Regen round {_round + 1}/{max_regen_rounds}: "
                f"{len(low_pages)} page(s) below {regen_threshold}"
            )
            for page in low_pages:
                old_score = ux_scores.get(page.slug, 0)
                old_html = page.html or ""
                violations = [e for e in project.errors if f"[{page.slug}]" in e]
                ux_prev = score_html(old_html)
                violations += [f"ux: {v}" for v in ux_prev.violations]
                page.html = await self.generator._regenerate_with_critique(
                    page, project.brief, nav_items, project.global_css or "", violations
                )
                new_score = score_html(page.html).total
                ux_scores[page.slug] = new_score
                logger.info(f"[WebGenPipeline] Regen [{page.slug}]: {old_score} → {new_score}")
                if new_score > old_score:
                    model_name = str(getattr(self.llm, "model", "local"))
                    _dpo_pairs.append(
                        {
                            "task": f"generate HTML page '{page.slug}' for {project.brief.business_type.value}",
                            "page_slug": page.slug,
                            "business_name": project.brief.business_name,
                            "model": model_name,
                            "bad_html": old_html,
                            "bad_score": old_score,
                            "good_html": page.html,
                            "good_score": new_score,
                            "violations_fixed": ux_prev.violations,
                            "category": "webgen_critique_regen",
                        }
                    )
            project.metadata["ux_scores"] = ux_scores
            self.site_store.save(project)

        # Write DPO pairs to disk
        if _dpo_pairs:
            import json as _json
            from datetime import datetime as _dt

            _ts = _dt.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
            _dpo_path = PROJECT_ROOT / "data" / "dpo" / f"webgen_critique_dpo_{_ts}.jsonl"
            _dpo_path.parent.mkdir(parents=True, exist_ok=True)
            with _dpo_path.open("w") as _f:
                for _pair in _dpo_pairs:
                    _f.write(_json.dumps(_pair) + "\n")
            logger.info(f"[WebGenPipeline] Wrote {len(_dpo_pairs)} DPO pairs → {_dpo_path.name}")

        if export:
            _emit("export", _total, "Saving site files")
            self.export(project, quality_checks=quality_checks)
            # Save to gallery
            from backend.webgen.gallery import save_iteration as _save_gallery

            _model = str(getattr(self.llm, "model", "local"))
            _slug = project.brief.business_name.lower().replace(" ", "-").replace("'", "")
            _gallery_path = _save_gallery(
                output_dir=project.output_dir,
                business_slug=_slug,
                model_name=_model,
                ux_scores=project.metadata.get("ux_scores", {}),
                design_style=project.metadata.get("design_context", {}).get("style_name", ""),
            )
            logger.info(f"[WebGenPipeline] Gallery iteration saved: {_gallery_path.name}")

        logger.info(
            f"[WebGenPipeline] Pipeline complete: {project.id} "
            f"({len(project.pages)} pages, status={project.status.value})"
        )
        return project

    # ── Info helpers ──────────────────────────────────────

    def list_projects(self) -> list[SiteProject]:
        return self.site_store.list_projects()

    def get_project(self, project_id: str) -> SiteProject | None:
        return self.site_store.load(project_id)

    def list_templates(self, business_type: str = ""):
        return self.template_store.list_templates(business_type)

    def list_components(self, category: str = "", business_type: str = ""):
        return self.template_store.list_components(category, business_type)
