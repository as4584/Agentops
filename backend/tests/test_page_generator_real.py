"""Real tests for PageGeneratorAgent — backend/webgen/agents/page_generator.py.

Tests focus on deterministic logic that would catch real bugs:
  1. Markdown fence stripping in _generate_section()
  2. Brand-colour injection in _generate_global_css()
  3. Google Fonts <link> insertion in _wrap_page()
  4. Per-page error isolation in run()
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.webgen.agents.page_generator import PageGeneratorAgent
from backend.webgen.models import (
    ClientBrief,
    PageSpec,
    SectionSpec,
    SiteProject,
    SiteStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generator(ask_llm_return: str = "<div>mock</div>") -> PageGeneratorAgent:
    """PageGeneratorAgent with a mocked ask_llm and no-op store."""
    mock_store = MagicMock()
    mock_store.find_components.return_value = []  # no templates

    gen = PageGeneratorAgent(llm=MagicMock(), store=mock_store)
    gen.ask_llm = AsyncMock(return_value=ask_llm_return)  # type: ignore[method-assign]
    return gen


def _minimal_brief(
    business_name: str = "Test Biz",
    tagline: str = "Great service",
    services: list[str] | None = None,
    tone: str = "professional",
    colors: dict[str, str] | None = None,
) -> ClientBrief:
    return ClientBrief(
        business_name=business_name,
        tagline=tagline,
        services=services or ["Service A", "Service B"],
        tone=tone,
        colors=colors or {},
    )


# ---------------------------------------------------------------------------
# _generate_section — markdown fence stripping
# ---------------------------------------------------------------------------


def test_strips_html_fence() -> None:
    """LLM returns ```html\\n<nav/>\\n``` — output must be bare <nav/>."""
    gen = _make_generator("```html\n<nav>Home</nav>\n```")
    section = SectionSpec(name="nav", component_type="navbar-simple")
    brief = _minimal_brief()

    result = asyncio.run(gen._generate_section(section, brief, []))

    assert result == "<nav>Home</nav>"


def test_strips_bare_fence() -> None:
    """LLM returns ```\\n<nav/>\\n``` (no language tag) — still stripped."""
    gen = _make_generator("```\n<nav>Menu</nav>\n```")
    section = SectionSpec(name="nav", component_type="navbar-simple")
    brief = _minimal_brief()

    result = asyncio.run(gen._generate_section(section, brief, []))

    assert result == "<nav>Menu</nav>"


def test_strips_trailing_fence_only() -> None:
    """LLM returns <nav>...</nav>\\n``` — trailing fence removed, content intact."""
    gen = _make_generator("<nav>Menu</nav>\n```")
    section = SectionSpec(name="nav", component_type="navbar-simple")
    brief = _minimal_brief()

    result = asyncio.run(gen._generate_section(section, brief, []))

    assert result == "<nav>Menu</nav>"
    assert "```" not in result


def test_no_mutation_when_clean_html() -> None:
    """Clean HTML from the LLM must pass through unchanged."""
    clean = "<section><h1>Title</h1><p>Body</p></section>"
    gen = _make_generator(clean)
    section = SectionSpec(name="hero", component_type="hero-centered")
    brief = _minimal_brief()

    result = asyncio.run(gen._generate_section(section, brief, []))

    assert result == clean


def test_multiline_fence_strips_only_first_and_last_lines() -> None:
    """Only the fence lines are removed, not inner content."""
    inner = "<nav>\n  <a href='/'>Home</a>\n</nav>"
    gen = _make_generator(f"```html\n{inner}\n```")
    section = SectionSpec(name="nav", component_type="navbar-simple")
    brief = _minimal_brief()

    result = asyncio.run(gen._generate_section(section, brief, []))

    assert "<a href='/'>Home</a>" in result
    assert "```" not in result


# ---------------------------------------------------------------------------
# _generate_global_css — colour injection
# ---------------------------------------------------------------------------


def test_global_css_uses_design_ctx_colors() -> None:
    """When design_ctx is set, the CSS must use its exact hex colours."""
    from backend.webgen.agents.design_advisor import DesignContext

    gen = _make_generator()
    gen.design_ctx = DesignContext(  # type: ignore[assignment]
        style_name="test",
        style_keywords="test, clean",
        primary_color="#AABBCC",
        secondary_color="#112233",
        accent_color="#FFEEDD",
        background_color="#FFFFFF",
        foreground_color="#000000",
        heading_font="Roboto",
        body_font="Lato",
        effects_hint="",
        google_fonts_css_import="",
    )
    brief = _minimal_brief()

    css = asyncio.run(gen._generate_global_css(brief))

    assert "#AABBCC" in css  # primary
    assert "#112233" in css  # secondary
    assert "#FFEEDD" in css  # accent
    assert "Roboto" in css
    assert "Lato" in css


def test_global_css_fallback_uses_brief_colors() -> None:
    """Without design_ctx, CSS must reflect the colours from the brief."""
    gen = _make_generator()
    gen.design_ctx = None
    brief = _minimal_brief(
        colors={"primary": "#112200", "secondary": "#334455", "accent": "#FF6600"},
    )

    css = asyncio.run(gen._generate_global_css(brief))

    assert "#112200" in css
    assert "#334455" in css
    assert "#FF6600" in css


def test_global_css_fallback_defaults_when_no_brief_colors() -> None:
    """Without design_ctx and without brief.colors, should use built-in defaults."""
    gen = _make_generator()
    gen.design_ctx = None
    brief = _minimal_brief()  # no colors dict

    css = asyncio.run(gen._generate_global_css(brief))

    # Defaults defined in the source: #2563eb, #1e40af, #f59e0b
    assert "#2563eb" in css
    assert "#1e40af" in css


# ---------------------------------------------------------------------------
# _wrap_page — Google Fonts <link> injection
# ---------------------------------------------------------------------------


def test_wrap_page_includes_fonts_link_when_design_ctx_set() -> None:
    """When design_ctx.google_fonts_css_import is set, a <link> must appear in <head>."""
    from backend.webgen.agents.design_advisor import DesignContext

    gen = _make_generator()
    gen.design_ctx = DesignContext(  # type: ignore[assignment]
        style_name="modern",
        style_keywords="modern, clean",
        primary_color="#000",
        secondary_color="#111",
        accent_color="#222",
        background_color="#FFF",
        foreground_color="#000",
        heading_font="Poppins",
        body_font="Open Sans",
        effects_hint="",
        google_fonts_css_import="https://fonts.googleapis.com/css2?family=Poppins&display=swap",
    )
    brief = _minimal_brief()

    html_out = gen._wrap_page("My Page", "<main>body</main>", "/* css */", brief)

    assert '<link href="https://fonts.googleapis.com' in html_out
    assert "Poppins" in html_out


def test_wrap_page_omits_fonts_link_when_no_design_ctx() -> None:
    """Without design_ctx, no Google Fonts link tag should appear."""
    gen = _make_generator()
    gen.design_ctx = None
    brief = _minimal_brief()

    html_out = gen._wrap_page("My Page", "<main>body</main>", "/* css */", brief)

    assert "fonts.googleapis.com" not in html_out


# ---------------------------------------------------------------------------
# run() — per-page error isolation
# ---------------------------------------------------------------------------


def test_run_catches_exception_and_continues_to_next_page() -> None:
    """If one page raises, its error is logged and remaining pages still process."""
    gen = _make_generator()
    gen.design_ctx = None

    # Override _generate_page: first call raises, second returns valid HTML
    call_count = 0

    async def _mock_generate_page(page, brief, nav_items, global_css):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM timeout")
        return "<main><h1>Page 2</h1></main>"

    gen._generate_page = _mock_generate_page  # type: ignore[method-assign,assignment]

    project = SiteProject(
        brief=_minimal_brief(),
        status=SiteStatus.PLANNED,
        pages=[
            PageSpec(slug="index", title="Home", nav_label="Home", nav_order=0),
            PageSpec(slug="about", title="About", nav_label="About", nav_order=1),
        ],
    )

    result = asyncio.run(gen.run(project))

    assert len(result.errors) == 1
    assert "index" in result.errors[0]
    assert result.pages[1].html == "<main><h1>Page 2</h1></main>"


def test_run_advances_status_to_generated() -> None:
    """run() must transition the project to GENERATED even when pages succeed."""
    gen = _make_generator()

    async def _mock_generate_page(*_args, **_kwargs):
        return "<main><h1>OK</h1></main>"

    gen._generate_page = _mock_generate_page  # type: ignore[method-assign,assignment]

    project = SiteProject(
        brief=_minimal_brief(),
        status=SiteStatus.PLANNED,
        pages=[PageSpec(slug="index", title="Home", nav_label="Home", nav_order=0)],
    )

    result = asyncio.run(gen.run(project))

    assert result.status == SiteStatus.GENERATED
