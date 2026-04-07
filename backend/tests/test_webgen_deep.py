"""
Deep tests for backend/webgen modules:
  - webgen/site_store.py
  - webgen/models.py  (SiteProject.advance)
  - webgen/agents/base_agent.py  (parse_json, ask_llm, ask_llm_json)
  - webgen/agents/qa_agent.py
  - webgen/agents/seo_agent.py
  - webgen/agents/aeo_agent.py
  - webgen/agents/site_planner.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.webgen.models import (
    SITE_TRANSITIONS,
    AEOProfile,
    BusinessType,
    ClientBrief,
    PageSpec,
    SEOProfile,
    SiteProject,
    SiteStatus,
)
from backend.webgen.site_store import SiteStore

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_project(*, status: SiteStatus = SiteStatus.BRIEF) -> SiteProject:
    p = SiteProject()
    p.brief = ClientBrief(
        business_name="Acme Corp",
        business_type=BusinessType.SAAS,
        description="A SaaS platform for testing",
        services=["Service A", "Service B"],
        tagline="Test everything",
    )
    p.status = status
    return p


def make_html(
    *,
    doctype: bool = True,
    lang: bool = True,
    viewport: bool = True,
    title: bool = True,
    description: bool = True,
    og_title: bool = True,
    jsonld: bool = True,
    h1_count: int = 1,
    full_body: bool = True,
    alt_img: bool = False,
    no_alt_img: bool = False,
) -> str:
    """Build a test HTML page with configurable completeness."""
    parts = []
    if doctype:
        parts.append("<!DOCTYPE html>")
    lang_attr = ' lang="en"' if lang else ""
    parts.append(f"<html{lang_attr}>")
    parts.append("<head>")
    if viewport:
        parts.append('<meta name="viewport" content="width=device-width">')
    if title:
        parts.append("<title>Test Page Title</title>")
    if description:
        parts.append('<meta name="description" content="Test description text">')
    if og_title:
        parts.append('<meta property="og:title" content="Test OG Title">')
    if jsonld:
        parts.append('<script type="application/ld+json">{"@context":"https://schema.org"}</script>')
    parts.append("</head>")
    body_items = []
    for i in range(h1_count):
        body_items.append(f"<h1>Heading {i}</h1>")
    if full_body:
        body_items.append("<p>" + "Lorem ipsum dolor sit amet consectetur. " * 8 + "</p>")
    else:
        body_items.append("<p>short</p>")
    if alt_img:
        body_items.append('<img src="a.jpg" alt="An image description">')
    if no_alt_img:
        body_items.append('<img src="b.jpg">')
    parts.append("<body>" + "".join(body_items) + "</body>")
    parts.append("</html>")
    return "\n".join(parts)


# ── SiteStore ─────────────────────────────────────────────────────────────────


class TestSiteStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        project = make_project()
        store.save(project)
        loaded = store.load(project.id)
        assert loaded is not None
        assert loaded.id == project.id
        assert loaded.brief.business_name == "Acme Corp"

    def test_load_missing_returns_none(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        assert store.load("no-such-id") is None

    def test_list_projects_empty(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        assert store.list_projects() == []

    def test_list_projects_multiple(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        p1, p2 = make_project(), make_project()
        store.save(p1)
        store.save(p2)
        listed = store.list_projects()
        assert len(listed) == 2
        ids = {p.id for p in listed}
        assert p1.id in ids and p2.id in ids

    def test_delete_existing_returns_true(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        project = make_project()
        store.save(project)
        assert store.delete(project.id) is True
        assert store.load(project.id) is None

    def test_delete_missing_returns_false(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        assert store.delete("ghost") is False

    def test_save_overwrites(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        project = make_project()
        store.save(project)
        project.status = SiteStatus.PLANNED
        store.save(project)
        loaded = store.load(project.id)
        assert loaded.status == SiteStatus.PLANNED

    def test_list_skips_corrupt_files(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        (tmp_path / "corrupt.json").write_text("not-valid-json")
        p = make_project()
        store.save(p)
        assert len(store.list_projects()) == 1

    def test_load_corrupt_file_returns_none(self, tmp_path):
        store = SiteStore(base_dir=tmp_path)
        pid = "myproject"
        (tmp_path / f"{pid}.json").write_text("{invalid}")
        assert store.load(pid) is None

    def test_creates_base_dir_if_missing(self, tmp_path):
        target = tmp_path / "nested" / "deep" / "store"
        store = SiteStore(base_dir=target)
        assert target.exists()
        p = make_project()
        store.save(p)
        assert store.load(p.id) is not None


# ── SiteProject.advance ───────────────────────────────────────────────────────


class TestSiteProjectAdvance:
    def test_advance_brief_to_planned(self):
        p = make_project(status=SiteStatus.BRIEF)
        p.advance(SiteStatus.PLANNED)
        assert p.status == SiteStatus.PLANNED

    def test_advance_invalid_transition_raises(self):
        p = make_project(status=SiteStatus.BRIEF)
        with pytest.raises(ValueError, match="Cannot transition"):
            p.advance(SiteStatus.QA_PASS)

    def test_advance_updates_updated_at(self):
        import time

        p = make_project(status=SiteStatus.BRIEF)
        before = p.updated_at
        time.sleep(0.015)
        p.advance(SiteStatus.PLANNED)
        assert p.updated_at > before

    def test_advance_deployed_to_anything_raises(self):
        p = make_project(status=SiteStatus.DEPLOYED)
        with pytest.raises(ValueError):
            p.advance(SiteStatus.READY)

    def test_all_allowed_transitions_succeed(self):
        for src, targets in SITE_TRANSITIONS.items():
            for tgt in targets:
                p = SiteProject()
                p.status = src
                p.advance(tgt)
                assert p.status == tgt

    def test_advance_full_chain_brief_to_qa_pass(self):
        p = make_project(status=SiteStatus.BRIEF)
        chain = [
            SiteStatus.PLANNED,
            SiteStatus.GENERATING,
            SiteStatus.GENERATED,
            SiteStatus.SEO_PASS,
            SiteStatus.AEO_PASS,
            SiteStatus.QA_PASS,
        ]
        for step in chain:
            p.advance(step)
        assert p.status == SiteStatus.QA_PASS


# ── WebAgentBase._parse_json ──────────────────────────────────────────────────


class TestWebAgentBaseParseJson:
    def _parse(self, raw: str):
        from backend.webgen.agents.base_agent import WebAgentBase

        return WebAgentBase._parse_json(raw)

    def test_direct_valid_json(self):
        assert self._parse('{"k": "v"}') == {"k": "v"}

    def test_fenced_json(self):
        raw = '```json\n{"k": "v"}\n```'
        assert self._parse(raw) == {"k": "v"}

    def test_embedded_json_object(self):
        raw = 'Here is the result: {"pages": []} and nothing else.'
        assert self._parse(raw) == {"pages": []}

    def test_empty_returns_error(self):
        result = self._parse("")
        assert "error" in result

    def test_garbage_returns_error_with_raw(self):
        result = self._parse("totally not json !!!")
        assert "error" in result
        assert "raw" in result

    def test_fenced_without_lang(self):
        raw = '```\n{"x": 1}\n```'
        result = self._parse(raw)
        assert result.get("x") == 1


# ── WebAgentBase async LLM methods ────────────────────────────────────────────


class _ConcreteAgent:
    """Fixture factory for a concrete WebAgentBase subclass."""

    @staticmethod
    def make(mock_chat_return=""):
        from backend.webgen.agents.base_agent import WebAgentBase

        class _Agent(WebAgentBase):
            name = "TestAgent"

            async def run(self, *a, **kw):
                return {}

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=mock_chat_return)
        return _Agent(llm=mock_llm), mock_llm


class TestWebAgentBaseAskLLM:
    @pytest.mark.asyncio
    async def test_ask_llm_returns_text(self):
        agent, _ = _ConcreteAgent.make("Hello World")
        result = await agent.ask_llm("say hello")
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_ask_llm_with_system_includes_system_message(self):
        agent, mock_llm = _ConcreteAgent.make("ok")
        await agent.ask_llm("prompt", system="be terse")
        messages = mock_llm.chat.call_args.kwargs["messages"]
        assert any(m["role"] == "system" for m in messages)

    @pytest.mark.asyncio
    async def test_ask_llm_exception_returns_empty_string(self):
        from backend.webgen.agents.base_agent import WebAgentBase

        class _Agent(WebAgentBase):
            async def run(self, *a, **kw):
                return {}

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("down"))
        agent = _Agent(llm=mock_llm)
        result = await agent.ask_llm("prompt")
        assert result == ""

    @pytest.mark.asyncio
    async def test_ask_llm_json_parses_response(self):
        agent, _ = _ConcreteAgent.make('{"pages": []}')
        result = await agent.ask_llm_json("plan the site")
        assert result == {"pages": []}

    @pytest.mark.asyncio
    async def test_ask_llm_json_with_schema_still_parses(self):
        agent, _ = _ConcreteAgent.make('{"k": "v"}')
        schema = {"type": "object", "properties": {"k": {"type": "string"}}}
        result = await agent.ask_llm_json("prompt", schema=schema)
        assert result.get("k") == "v"

    @pytest.mark.asyncio
    async def test_ask_llm_json_bad_response_returns_error_dict(self):
        agent, _ = _ConcreteAgent.make("not json at all!")
        result = await agent.ask_llm_json("prompt")
        assert "error" in result


# ── WebQAAgent._check_page ────────────────────────────────────────────────────


class TestWebQAAgentCheckPage:
    def _agent(self):
        from backend.webgen.agents.qa_agent import WebQAAgent

        return WebQAAgent(llm=MagicMock())

    def test_empty_html_reports_issue(self):
        issues = self._agent()._check_page(PageSpec(slug="t", html=""))
        assert any("no HTML" in i for i in issues)

    def test_valid_html_no_issues(self):
        issues = self._agent()._check_page(PageSpec(slug="t", html=make_html()))
        assert issues == []

    def test_missing_doctype(self):
        html = make_html(doctype=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("DOCTYPE" in i for i in issues)

    def test_missing_viewport(self):
        html = make_html(viewport=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("viewport" in i.lower() for i in issues)

    def test_missing_title(self):
        html = make_html(title=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("title" in i.lower() for i in issues)

    def test_missing_meta_description(self):
        html = make_html(description=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("description" in i.lower() for i in issues)

    def test_missing_h1(self):
        html = make_html(h1_count=0)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("h1" in i.lower() for i in issues)

    def test_multiple_h1(self):
        html = make_html(h1_count=3)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("Multiple" in i for i in issues)

    def test_missing_lang_attribute(self):
        html = make_html(lang=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("lang" in i.lower() for i in issues)

    def test_image_missing_alt_flagged(self):
        html = make_html(no_alt_img=True)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("alt" in i.lower() for i in issues)

    def test_image_with_alt_not_flagged(self):
        html = make_html(alt_img=True)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert not any("alt" in i.lower() for i in issues)

    def test_missing_og_title(self):
        html = make_html(og_title=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("og:title" in i.lower() for i in issues)

    def test_missing_jsonld(self):
        html = make_html(jsonld=False)
        issues = self._agent()._check_page(PageSpec(slug="t", html=html))
        assert any("json-ld" in i.lower() or "JSON-LD" in i for i in issues)


# ── WebQAAgent.run ────────────────────────────────────────────────────────────


class TestWebQAAgentRun:
    def _agent(self, llm_return: str = "[]"):
        from backend.webgen.agents.qa_agent import WebQAAgent

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=llm_return)
        return WebQAAgent(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_run_advances_to_qa_pass(self):
        agent = self._agent()
        project = make_project(status=SiteStatus.AEO_PASS)
        project.pages = [PageSpec(slug="index", html=make_html())]
        result = await agent.run(project)
        assert result.status == SiteStatus.QA_PASS

    @pytest.mark.asyncio
    async def test_run_collects_issues_from_bad_pages(self):
        agent = self._agent()
        project = make_project(status=SiteStatus.AEO_PASS)
        project.pages = [PageSpec(slug="bad", html="")]
        result = await agent.run(project)
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_run_with_no_pages_still_advances(self):
        agent = self._agent()
        project = make_project(status=SiteStatus.AEO_PASS)
        result = await agent.run(project)
        assert result.status == SiteStatus.QA_PASS

    @pytest.mark.asyncio
    async def test_run_stores_ux_scores_in_metadata(self):
        agent = self._agent()
        project = make_project(status=SiteStatus.AEO_PASS)
        project.pages = [PageSpec(slug="index", html=make_html())]
        result = await agent.run(project)
        assert "ux_scores" in result.metadata

    @pytest.mark.asyncio
    async def test_run_llm_review_on_index_page(self):
        agent = self._agent(llm_return='["Missing CTA button"]')
        project = make_project(status=SiteStatus.AEO_PASS)
        html = make_html()
        project.pages = [PageSpec(slug="index", html=html)]
        result = await agent.run(project)
        # LLM issued one additional issue for the index page
        assert any("[index][llm]" in e for e in result.errors)


# ── SEOAgent helpers ──────────────────────────────────────────────────────────


class TestSEOAgentHelpers:
    def _agent(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        return SEOAgent(llm=MagicMock())

    def test_escape_attr_double_quotes(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        assert "&quot;" in SEOAgent._escape_attr('say "hello"')

    def test_escape_attr_angle_brackets(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        result = SEOAgent._escape_attr("<script>alert(1)</script>")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_generate_sitemap_contains_pages(self):
        agent = self._agent()
        pages = [PageSpec(slug="index"), PageSpec(slug="about")]
        xml = agent._generate_sitemap(pages, "https://example.com")
        assert "index.html" in xml
        assert "about.html" in xml
        assert '<?xml version="1.0"' in xml

    def test_generate_sitemap_index_priority_higher(self):
        agent = self._agent()
        pages = [PageSpec(slug="index"), PageSpec(slug="about")]
        xml = agent._generate_sitemap(pages, "https://example.com")
        # index should have priority 1.0, about should have 0.8
        assert "<priority>1.0</priority>" in xml
        assert "<priority>0.8</priority>" in xml

    def test_generate_robots_txt(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        result = SEOAgent._generate_robots("https://example.com")
        assert "User-agent: *" in result
        assert "Allow: /" in result
        assert "https://example.com/sitemap.xml" in result

    def test_inject_seo_adds_meta_description(self):
        agent = self._agent()
        seo = SEOProfile(meta_description="A great business")
        html = "<html><head></head><body><h1>Hi</h1></body></html>"
        brief = MagicMock(business_name="TestCo")
        result = agent._inject_seo(html, seo, brief)
        assert 'name="description"' in result

    def test_inject_seo_adds_og_tags(self):
        agent = self._agent()
        seo = SEOProfile(og_title="OG Title", og_description="OG Desc")
        html = "<html><head></head><body></body></html>"
        brief = MagicMock(business_name="TestCo")
        result = agent._inject_seo(html, seo, brief)
        assert 'property="og:title"' in result
        assert 'property="og:description"' in result

    def test_inject_seo_adds_jsonld(self):
        agent = self._agent()
        seo = SEOProfile(schema_json_ld={"@type": "WebPage"})
        html = "<html><head></head><body></body></html>"
        brief = MagicMock(business_name="TestCo")
        result = agent._inject_seo(html, seo, brief)
        assert "application/ld+json" in result

    def test_inject_seo_adds_canonical(self):
        agent = self._agent()
        seo = SEOProfile(canonical_url="https://example.com/page")
        html = "<html><head></head><body></body></html>"
        brief = MagicMock(business_name="TestCo")
        result = agent._inject_seo(html, seo, brief)
        assert 'rel="canonical"' in result

    def test_inject_seo_empty_html_unchanged(self):
        agent = self._agent()
        seo = SEOProfile(title="T")
        brief = MagicMock(business_name="X")
        assert agent._inject_seo("", seo, brief) == ""

    @pytest.mark.asyncio
    async def test_run_advances_to_seo_pass(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        seo_response = json.dumps(
            {
                "title": "Great Title | Acme",
                "meta_description": "A great SaaS platform.",
                "keywords": ["saas", "platform"],
                "og_title": "OG Title",
                "og_description": "OG Desc",
                "schema_type": "WebPage",
                "schema_json_ld": {"@type": "WebPage"},
            }
        )
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=seo_response)
        agent = SEOAgent(llm=mock_llm)
        project = make_project(status=SiteStatus.GENERATED)
        project.pages = [PageSpec(slug="index", title="Home", html="<html><head></head><body></body></html>")]
        result = await agent.run(project)
        assert result.status == SiteStatus.SEO_PASS
        assert result.sitemap_xml != ""
        assert result.robots_txt != ""

    @pytest.mark.asyncio
    async def test_run_uses_fallback_on_bad_llm_response(self):
        from backend.webgen.agents.seo_agent import SEOAgent

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="not json at all")
        agent = SEOAgent(llm=mock_llm)
        project = make_project(status=SiteStatus.GENERATED)
        project.pages = [PageSpec(slug="index", title="Home", html="<html><head></head><body></body></html>")]
        result = await agent.run(project)
        # Should still advance; fallback SEO profile applied
        assert result.status == SiteStatus.SEO_PASS


# ── AEOAgent helpers ──────────────────────────────────────────────────────────


class TestAEOAgentHelpers:
    def _agent(self):
        from backend.webgen.agents.aeo_agent import AEOAgent

        return AEOAgent(llm=MagicMock())

    def test_build_faq_section_contains_questions(self):
        from backend.webgen.agents.aeo_agent import AEOAgent

        faqs = [
            {"q": "What is it?", "a": "A platform."},
            {"q": "How much?", "a": "Free tier available."},
        ]
        html = AEOAgent._build_faq_section(faqs)
        assert "What is it?" in html
        assert "A platform." in html
        assert "faq-answer" in html

    def test_inject_aeo_adds_faq_schema(self):
        agent = self._agent()
        aeo = AEOProfile(faq_pairs=[{"q": "Q?", "a": "A."}])
        html = "<html><head></head><body></body></html>"
        result = agent._inject_aeo(html, aeo, MagicMock(business_name="X"))
        assert "FAQPage" in result

    def test_inject_aeo_adds_speakable_schema(self):
        agent = self._agent()
        aeo = AEOProfile(speakable_selectors=["#hero h1"])
        html = "<html><head></head><body></body></html>"
        result = agent._inject_aeo(html, aeo, MagicMock(business_name="X"))
        assert "speakable" in result

    def test_inject_aeo_empty_html_unchanged(self):
        agent = self._agent()
        aeo = AEOProfile(faq_pairs=[{"q": "Q?", "a": "A."}])
        result = agent._inject_aeo("", aeo, MagicMock(business_name="X"))
        assert result == ""

    def test_inject_aeo_no_faq_no_speakable_unchanged(self):
        agent = self._agent()
        aeo = AEOProfile()  # no FAQ, no speakable
        html = "<html><head></head><body></body></html>"
        brief = MagicMock(business_name="X")
        assert agent._inject_aeo(html, aeo, brief) == html

    def test_inject_aeo_faq_appended_to_body(self):
        agent = self._agent()
        aeo = AEOProfile(faq_pairs=[{"q": "Q?", "a": "A."}])
        html = "<html><head></head><body><h1>Hi</h1></body></html>"
        result = agent._inject_aeo(html, aeo, MagicMock(business_name="X"))
        # FAQ section should appear before </body>
        assert result.index("Q?") < result.index("</body>")

    @pytest.mark.asyncio
    async def test_run_advances_to_aeo_pass(self):
        from backend.webgen.agents.aeo_agent import AEOAgent

        aeo_response = json.dumps(
            {
                "faq_pairs": [{"q": "What?", "a": "This."}],
                "entity_name": "Acme Corp",
                "entity_type": "LocalBusiness",
                "entity_description": "A SaaS company",
                "topic_cluster": "Software",
                "related_topics": ["cloud", "saas"],
                "speakable_selectors": [".faq-answer"],
            }
        )
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=aeo_response)
        agent = AEOAgent(llm=mock_llm)
        project = make_project(status=SiteStatus.SEO_PASS)
        project.pages = [PageSpec(slug="index", html="<html><head></head><body></body></html>")]
        result = await agent.run(project)
        assert result.status == SiteStatus.AEO_PASS

    @pytest.mark.asyncio
    async def test_run_uses_fallback_on_bad_response(self):
        from backend.webgen.agents.aeo_agent import AEOAgent

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="bad json")
        agent = AEOAgent(llm=mock_llm)
        project = make_project(status=SiteStatus.SEO_PASS)
        project.pages = [PageSpec(slug="index", html="<html><head></head><body></body></html>")]
        result = await agent.run(project)
        assert result.status == SiteStatus.AEO_PASS


# ── SitePlannerAgent ──────────────────────────────────────────────────────────


class TestSitePlannerAgent:
    def _agent(self, llm_return: str = "{}"):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=llm_return)
        mock_store = MagicMock()
        mock_store.list_templates.return_value = []
        return SitePlannerAgent(llm=mock_llm, store=mock_store)

    def test_parse_plan_dict_with_pages(self):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        agent = SitePlannerAgent(llm=MagicMock(), store=MagicMock(list_templates=MagicMock(return_value=[])))
        brief = ClientBrief(business_name="Acme")
        plan = {
            "pages": [
                {
                    "slug": "index",
                    "title": "Home - Acme",
                    "purpose": "Landing",
                    "nav_label": "Home",
                    "nav_order": 1,
                    "sections": [
                        {"name": "hero", "component_type": "hero-centered", "content_hints": {}},
                    ],
                }
            ]
        }
        pages = agent._parse_plan(plan, brief)
        assert len(pages) == 1
        assert pages[0].slug == "index"
        assert pages[0].sections[0].name == "hero"

    def test_parse_plan_from_list(self):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        agent = SitePlannerAgent(llm=MagicMock(), store=MagicMock(list_templates=MagicMock(return_value=[])))
        brief = ClientBrief(business_name="Acme")
        plan_list = [
            {"slug": "about", "title": "About", "purpose": "Company info", "nav_label": "About", "sections": []}
        ]
        pages = agent._parse_plan(plan_list, brief)
        assert len(pages) == 1
        assert pages[0].slug == "about"

    def test_parse_plan_empty_uses_fallback(self):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        agent = SitePlannerAgent(llm=MagicMock(), store=MagicMock(list_templates=MagicMock(return_value=[])))
        brief = ClientBrief(business_name="Acme")
        pages = agent._parse_plan({"pages": []}, brief)
        assert len(pages) == 4  # fallback has 4 pages

    def test_fallback_plan_has_required_pages(self):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        agent = SitePlannerAgent(llm=MagicMock(), store=MagicMock(list_templates=MagicMock(return_value=[])))
        brief = ClientBrief(business_name="Acme Corp")
        pages = agent._fallback_plan(brief)
        slugs = [p.slug for p in pages]
        assert "index" in slugs
        assert "about" in slugs
        assert "contact" in slugs
        # Title should include business name
        for p in pages:
            assert "Acme Corp" in p.title

    def test_fallback_plan_sections_populated(self):
        from backend.webgen.agents.site_planner import SitePlannerAgent

        agent = SitePlannerAgent(llm=MagicMock(), store=MagicMock(list_templates=MagicMock(return_value=[])))
        brief = ClientBrief(business_name="X")
        pages = agent._fallback_plan(brief)
        # Each page should have at least one section
        for p in pages:
            assert len(p.sections) > 0

    @pytest.mark.asyncio
    async def test_run_advances_to_planned(self):
        plan_json = json.dumps(
            {
                "pages": [
                    {
                        "slug": "index",
                        "title": "Home - Acme Corp",
                        "purpose": "Landing page",
                        "nav_label": "Home",
                        "nav_order": 1,
                        "sections": [{"name": "hero", "component_type": "hero-centered", "content_hints": {}}],
                    }
                ]
            }
        )
        agent = self._agent(llm_return=plan_json)
        project = make_project(status=SiteStatus.BRIEF)
        result = await agent.run(project)
        assert result.status == SiteStatus.PLANNED
        assert len(result.pages) >= 1

    @pytest.mark.asyncio
    async def test_run_uses_fallback_on_bad_llm_response(self):
        agent = self._agent(llm_return="not json")
        project = make_project(status=SiteStatus.BRIEF)
        result = await agent.run(project)
        # Fallback kicks in, should still advance
        assert result.status == SiteStatus.PLANNED
        assert len(result.pages) == 4
