"""Real tests for WebGenPipeline — generate_section_with_retry and create().

These tests validate:
1. The retry loop calls the LLM the right number of times
2. Feedback is injected on attempt 2+
3. Temperature drops from 0.6 → 0.4 on retries
4. Best score across attempts is preserved, not overwritten
5. Early exit fires when quality gate passes
6. create() slugifies business_name into output_dir
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.webgen.models import ClientBrief
from backend.webgen.pipeline import WebGenPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline(tmp_path: Path | None = None) -> WebGenPipeline:
    """Create a pipeline with a mock LLM and in-memory stores."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value="<section><nav>Test</nav></section>")
    mock_llm.model = "local"

    mock_site_store = MagicMock()
    mock_site_store.save = MagicMock()

    pipeline = WebGenPipeline(
        llm=mock_llm,
        site_store=mock_site_store,
        output_base=tmp_path or Path("/tmp/webgen_test"),
    )
    return pipeline


def _minimal_brief(name: str = "Acme Corp") -> ClientBrief:
    return ClientBrief(
        business_name=name,
        tagline="Test tagline",
        services=["Service A", "Service B"],
        tone="professional",
    )


# ---------------------------------------------------------------------------
# generate_section_with_retry — attempt count
# ---------------------------------------------------------------------------


def test_single_attempt_when_quality_gate_passes() -> None:
    """When the first attempt passes the quality gate, LLM should be called exactly once."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    good_html = (
        "<section><nav><a href='/'>Home</a><a href='/about'>About</a>"
        "<a href='/services'>Services</a><a href='/contact'>Contact</a>"
        "<a href='/blog'>Blog</a></nav>"
        "<header><h1>Acme Corp</h1><p>Test tagline</p></header>"
        "<div><button>Contact Us</button></div></section>"
    )
    pipeline.llm.chat = AsyncMock(return_value=good_html)  # type: ignore[method-assign]

    with patch("backend.webgen.pipeline.passes_quality_gate", return_value=True):
        html, score = asyncio.run(
            pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3, min_ux_score=50)
        )

    assert pipeline.llm.chat.call_count == 1
    assert html == good_html


def test_retry_fires_when_first_attempt_fails_gate() -> None:
    """When attempt 1 fails the quality gate, LLM is called again for attempt 2."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    pipeline.llm.chat = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            "<div>Bad HTML</div>",  # attempt 1 — fails gate
            "<section><nav><a>Home</a></nav><header><h1>Test</h1></header></section>",  # attempt 2
        ]
    )

    # Gate fails on attempt 1, passes on attempt 2
    gate_calls = [False, True]
    with patch("backend.webgen.pipeline.passes_quality_gate", side_effect=gate_calls):
        asyncio.run(
            pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3, min_ux_score=50)
        )

    assert pipeline.llm.chat.call_count == 2


def test_max_attempts_respected() -> None:
    """The loop must NEVER exceed max_attempts LLM calls."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    pipeline.llm.chat = AsyncMock(return_value="<div>Mediocre HTML</div>")  # type: ignore[method-assign]

    with patch("backend.webgen.pipeline.passes_quality_gate", return_value=False):
        asyncio.run(
            pipeline.generate_section_with_retry(brief, "footer", "simple-footer", max_attempts=2, min_ux_score=50)
        )

    assert pipeline.llm.chat.call_count == 2


# ---------------------------------------------------------------------------
# generate_section_with_retry — temperature discipline
# ---------------------------------------------------------------------------


def test_attempt_1_uses_temperature_06() -> None:
    """First attempt must use temperature=0.6."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    pipeline.llm.chat = AsyncMock(return_value="<div>OK</div>")  # type: ignore[method-assign]

    with patch("backend.webgen.pipeline.passes_quality_gate", return_value=True):
        asyncio.run(pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3))

    first_call_kwargs = pipeline.llm.chat.call_args_list[0]
    assert first_call_kwargs.kwargs.get("temperature") == 0.6


def test_attempt_2_uses_temperature_04() -> None:
    """Second attempt must use temperature=0.4 (stricter generation)."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    pipeline.llm.chat = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            "<div>Bad</div>",  # attempt 1
            "<div>Better</div>",  # attempt 2
        ]
    )

    gate_calls = [False, True]
    with patch("backend.webgen.pipeline.passes_quality_gate", side_effect=gate_calls):
        asyncio.run(pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3))

    second_call_kwargs = pipeline.llm.chat.call_args_list[1]
    assert second_call_kwargs.kwargs.get("temperature") == 0.4


# ---------------------------------------------------------------------------
# generate_section_with_retry — feedback injection
# ---------------------------------------------------------------------------


def test_retry_prompt_contains_previous_attempt_score() -> None:
    """The second attempt's prompt must mention 'PREVIOUS ATTEMPT SCORED'."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    # Minimal HTML that's valid enough to score > 0 but won't pass gate
    # (needs enough structure to trigger score_html to produce some violations)
    pipeline.llm.chat = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            "<div>First attempt</div>",
            "<div>Second attempt</div>",
        ]
    )

    gate_calls = [False, True]
    with patch("backend.webgen.pipeline.passes_quality_gate", side_effect=gate_calls):
        asyncio.run(pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3))

    # Extract the prompt from the second LLM call
    second_call = pipeline.llm.chat.call_args_list[1]
    messages = second_call.kwargs.get("messages") or second_call.args[0]
    # The user message is the last message
    user_prompt = next(m["content"] for m in messages if m["role"] == "user")
    assert "PREVIOUS ATTEMPT SCORED" in user_prompt


def test_first_attempt_has_no_feedback_prefix() -> None:
    """The first attempt should NOT contain any 'PREVIOUS ATTEMPT' text."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    pipeline.llm.chat = AsyncMock(return_value="<section><nav/></section>")  # type: ignore[method-assign]

    with patch("backend.webgen.pipeline.passes_quality_gate", return_value=True):
        asyncio.run(pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=3))

    first_call = pipeline.llm.chat.call_args_list[0]
    messages = first_call.kwargs.get("messages") or first_call.args[0]
    user_prompt = next(m["content"] for m in messages if m["role"] == "user")
    assert "PREVIOUS ATTEMPT SCORED" not in user_prompt


# ---------------------------------------------------------------------------
# generate_section_with_retry — best score tracking
# ---------------------------------------------------------------------------


def test_returns_best_score_not_last() -> None:
    """If attempt 1 scores higher than attempt 2, return attempt 1's HTML."""
    pipeline = _make_pipeline()
    brief = _minimal_brief()

    html_good = "<section><nav><a>1</a></nav><header><h1>T</h1></header><button>CTA</button></section>"
    html_bad = "<div>Bad</div>"

    pipeline.llm.chat = AsyncMock(side_effect=[html_good, html_bad])  # type: ignore[method-assign]

    # Gate never passes so we run all attempts
    with patch("backend.webgen.pipeline.passes_quality_gate", return_value=False):
        # Use real score_html — html_good will outscore html_bad
        returned_html, returned_score = asyncio.run(
            pipeline.generate_section_with_retry(brief, "hero", "hero-centered", max_attempts=2)
        )

    assert returned_html == html_good
    # score of html_good must be >= score of html_bad
    from backend.webgen.agents.ux_scorer import score_html

    assert returned_score == score_html(html_good).total


# ---------------------------------------------------------------------------
# create() — slug output_dir
# ---------------------------------------------------------------------------


def test_create_sets_slug_from_business_name(tmp_path: Path) -> None:
    """Business name 'Acme Corp' → output_dir ends with 'acme-corp'."""
    pipeline = _make_pipeline(tmp_path)
    brief = _minimal_brief("Acme Corp")

    project = pipeline.create(brief)

    assert project.output_dir.endswith("acme-corp")


def test_create_strips_apostrophes_in_slug(tmp_path: Path) -> None:
    """Business name "Pat's Gym" → slug 'pats-gym', no apostrophes."""
    pipeline = _make_pipeline(tmp_path)
    brief = _minimal_brief("Pat's Gym")

    project = pipeline.create(brief)

    assert "'" not in project.output_dir
    assert "pats-gym" in project.output_dir


def test_create_returns_site_project_with_brief(tmp_path: Path) -> None:
    """create() should return a SiteProject whose brief matches the input."""
    pipeline = _make_pipeline(tmp_path)
    brief = _minimal_brief("Demo Business")

    project = pipeline.create(brief)

    assert project.brief.business_name == "Demo Business"
    assert project.id != ""
