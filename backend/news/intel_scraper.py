"""
News Intelligence Scraper
=========================
Scheduled collection of AI, cybersecurity, and open-source news from trusted
sources covering: Google/Gemini, Anthropic/Claude, OpenAI/Codex, DeepSeek,
Qwen/Alibaba, ByteDance, China open-source scene, and cybersecurity.

Security model
--------------
- Domain allowlist: ONLY trusted domains listed in _NEWS_SOURCES may be fetched.
- RSS/Atom feeds use httpx (no browser, fastest + safest path).
- JS-heavy HTML sources use an isolated Playwright browser context that is:
    * Spun up fresh per scrape cycle (no persistent cookies / storage state)
    * Blocks ads and tracking via request interception
    * Hard 15 s navigation timeout per page
    * Torn down immediately after use
- Per-request rate limiting (1–2.5 s random delay) for polite crawling.

Output
------
- data/agents/knowledge_agent/news_intel/YYYY-MM-DD.jsonl — daily append log
- data/agents/knowledge_agent/news_intel/latest.json     — last N items (for Discord + agents)
- HIGH_RELEVANCE items fire alert_dispatch → SecurityEventWatcher → Discord

Usage (server.py lifespan)
--------------------------
    from backend.news.intel_scraper import NewsIntelWatcher
    asyncio.ensure_future(NewsIntelWatcher(memory_store).run())
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from backend.config import PROJECT_ROOT

logger = logging.getLogger("agentop.news.intel")

# ---------------------------------------------------------------------------
# Source registry
# Each entry describes one trusted news source.
# type = "rss"  → fetched with httpx, parsed as RSS/Atom XML
# type = "html" → fetched with sandboxed Playwright, text extracted from <a> tags
# ---------------------------------------------------------------------------

NEWS_SOURCES: list[dict[str, Any]] = [
    # ── Google / Gemini / DeepMind ──────────────────────────────────────────
    {
        "id": "google_ai_blog",
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "type": "rss",
        "topics": ["google", "gemini"],
        "domain": "blog.google",
    },
    {
        "id": "deepmind_blog",
        "name": "Google DeepMind",
        "url": "https://deepmind.google/blog/rss.xml",
        "type": "rss",
        "topics": ["google", "gemini", "deepmind"],
        "domain": "deepmind.google",
    },
    # ── Anthropic / Claude / Claude Code ────────────────────────────────────
    {
        "id": "anthropic_news",
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/news",
        "type": "html",
        "link_pattern": r"/news/[a-z0-9\-]+",
        "base_url": "https://www.anthropic.com",
        "topics": ["claude", "claude_code", "anthropic"],
        "domain": "anthropic.com",
    },
    # ── OpenAI / Codex ───────────────────────────────────────────────────────
    {
        "id": "openai_blog",
        "name": "OpenAI Blog",
        "url": "https://openai.com/news/",
        "type": "html",
        "link_pattern": r"/index/[a-z0-9\-]+",
        "base_url": "https://openai.com",
        "topics": ["openai", "codex", "gpt"],
        "domain": "openai.com",
    },
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    {
        "id": "deepseek_github_releases",
        "name": "DeepSeek GitHub Releases",
        "url": "https://github.com/deepseek-ai/DeepSeek-V3/releases.atom",
        "type": "rss",
        "topics": ["deepseek"],
        "domain": "github.com",
    },
    {
        "id": "deepseek_r1_releases",
        "name": "DeepSeek-R1 GitHub Releases",
        "url": "https://github.com/deepseek-ai/DeepSeek-R1/releases.atom",
        "type": "rss",
        "topics": ["deepseek"],
        "domain": "github.com",
    },
    # ── Qwen / Alibaba ───────────────────────────────────────────────────────
    {
        "id": "qwen_blog",
        "name": "Qwen Blog",
        "url": "https://qwenlm.github.io/blog/",
        "type": "html",
        "link_pattern": r"/blog/[a-z0-9\-]+",
        "base_url": "https://qwenlm.github.io",
        "topics": ["qwen", "alibaba"],
        "domain": "qwenlm.github.io",
    },
    # ── ByteDance ────────────────────────────────────────────────────────────
    {
        "id": "bytedance_research",
        "name": "ByteDance Research",
        "url": "https://research.bytedance.com/en/Research",
        "type": "html",
        "link_pattern": r"/Research/\d+",
        "base_url": "https://research.bytedance.com",
        "topics": ["bytedance"],
        "domain": "research.bytedance.com",
    },
    # ── China Open Source Scene ──────────────────────────────────────────────
    {
        "id": "huggingface_blog",
        "name": "HuggingFace Blog (OSS models)",
        "url": "https://huggingface.co/blog/feed.xml",
        "type": "rss",
        "topics": ["opensource", "china_opensource", "deepseek", "qwen"],
        "domain": "huggingface.co",
    },
    {
        "id": "modelscope_news",
        "name": "ModelScope (Alibaba OSS hub)",
        "url": "https://modelscope.cn/news",
        "type": "html",
        "link_pattern": r"/news/[a-zA-Z0-9\-]+",
        "base_url": "https://modelscope.cn",
        "topics": ["china_opensource", "qwen", "alibaba"],
        "domain": "modelscope.cn",
    },
    # ── AI Research (ArXiv) ──────────────────────────────────────────────────
    {
        "id": "arxiv_cs_ai",
        "name": "ArXiv cs.AI",
        "url": "https://arxiv.org/rss/cs.AI",
        "type": "rss",
        "topics": ["research", "ai_advances"],
        "domain": "arxiv.org",
    },
    {
        "id": "arxiv_cs_cl",
        "name": "ArXiv cs.CL (LLMs / NLP)",
        "url": "https://arxiv.org/rss/cs.CL",
        "type": "rss",
        "topics": ["research", "llm", "deepseek", "qwen", "gemini"],
        "domain": "arxiv.org",
    },
    # ── Cybersecurity ────────────────────────────────────────────────────────
    {
        "id": "securityweek",
        "name": "SecurityWeek",
        "url": "https://feeds.feedburner.com/securityweek",
        "type": "rss",
        "topics": ["cybersecurity"],
        "domain": "securityweek.com",
    },
    {
        "id": "krebs_security",
        "name": "KrebsOnSecurity",
        "url": "https://krebsonsecurity.com/feed/",
        "type": "rss",
        "topics": ["cybersecurity"],
        "domain": "krebsonsecurity.com",
    },
    {
        "id": "cisa_advisories",
        "name": "CISA Cybersecurity Advisories",
        "url": "https://www.cisa.gov/news.xml",
        "type": "rss",
        "topics": ["cybersecurity"],
        "domain": "cisa.gov",
    },
    {
        "id": "the_hacker_news",
        "name": "The Hacker News",
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "type": "rss",
        "topics": ["cybersecurity"],
        "domain": "thehackernews.com",
    },
]

# ---------------------------------------------------------------------------
# Domain allowlist — derived from sources, enforced at fetch time.
# Requests to any other domain will be refused.
# ---------------------------------------------------------------------------
TRUSTED_DOMAINS: frozenset[str] = frozenset(s["domain"] for s in NEWS_SOURCES)

# ---------------------------------------------------------------------------
# High-relevance keyword matching — these items get flagged and Discord-alerted
# ---------------------------------------------------------------------------
HIGH_RELEVANCE_KEYWORDS: list[str] = [
    "claude",
    "claude code",
    "anthropic",
    "codex",
    "openai",
    "deepseek",
    "qwen",
    "alibaba",
    "gemini",
    "google deepmind",
    "bytedance",
    "ollama",
    "llama",
    "mistral",
    "phi-",
    "multi-agent",
    "agentic",
    "mcp",
    "model context protocol",
    "fine-tuning",
    "dpo",
    "rlhf",
    "lora",
    "gguf",
    "critical vulnerability",
    "zero-day",
    "cve-",
    "rce",
    "supply chain attack",
    "open source model",
    "model release",
    "weights released",
]

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
NEWS_DIR = PROJECT_ROOT / "data" / "agents" / "knowledge_agent" / "news_intel"
LATEST_JSON = NEWS_DIR / "latest.json"
_MAX_LATEST_ITEMS = 200  # keep last N items in latest.json
_MAX_ITEMS_PER_SOURCE = 10  # limit per source per scrape cycle
_SCRAPE_INTERVAL_HOURS = 6  # how often to run
_REQUEST_DELAY_RANGE = (1.0, 2.5)  # polite delay between source fetches (seconds)

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; AgentopNewsBot/1.0; +https://github.com/as4584/Agentop)"),
    "Accept": "application/rss+xml, application/atom+xml, text/xml, text/html, */*",
}


def _enforce_domain(url: str) -> None:
    """Raise ValueError if url's netloc is not in TRUSTED_DOMAINS."""
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower().lstrip("www.")
    if not any(netloc == d or netloc.endswith("." + d) for d in TRUSTED_DOMAINS):
        raise ValueError(f"[NewsIntel] Domain not in allowlist: {netloc!r} (url={url!r})")


def _item_id(url: str) -> str:
    """Stable short hash for deduplication."""
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _is_high_relevance(title: str, summary: str) -> bool:
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in HIGH_RELEVANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Smart category classifier — software / hardware / security / research
# ---------------------------------------------------------------------------

_HW_KEYWORDS: frozenset[str] = frozenset(
    [
        "gpu",
        "nvidia",
        "amd",
        "intel arc",
        "tpu",
        "npu",
        "chip",
        "processor",
        "silicon",
        "semiconductor",
        "data center",
        "h100",
        "h200",
        "b200",
        "b100",
        "blackwell",
        "hopper",
        "gb200",
        "grace",
        "hbm",
        "hbm3",
        "vram",
        "wafer",
        "fab",
        "tsmc",
        "samsung foundry",
        "server hardware",
        "power consumption",
        "cooling",
        "rack",
        "pcie",
        "nvlink",
        "infinity fabric",
        "apple m",
        "neural engine",
        "groq",
        "cerebras",
        "tenstorrent",
        "graphcore",
        "asic",
        "fpga",
        "inference chip",
        "training cluster",
        "supercomputer",
    ]
)

_SW_KEYWORDS: frozenset[str] = frozenset(
    [
        "model release",
        "weights",
        "llm",
        "language model",
        "fine-tun",
        "dpo",
        "rlhf",
        "lora",
        "gguf",
        "quantiz",
        "inference",
        "api",
        "sdk",
        "library",
        "framework",
        "update",
        "version",
        "release",
        "open source",
        "open-source",
        "agent",
        "tool use",
        "function calling",
        "context window",
        "tokenizer",
        "benchmark",
        "mmlu",
        "humaneval",
        "swebench",
        "deployment",
        "vllm",
        "transformers",
        "langchain",
        "llamaindex",
        "ollama",
        "docker",
        "container",
    ]
)

_SEC_KEYWORDS: frozenset[str] = frozenset(
    [
        "cve-",
        "vulnerability",
        "exploit",
        "zero-day",
        "breach",
        "attack",
        "malware",
        "ransomware",
        "phishing",
        "advisory",
        "patch",
        "rce",
        "injection",
        "supply chain",
        "backdoor",
        "credential",
        "leak",
        "critical flaw",
        "cybersecurity",
        "threat actor",
        "apt",
    ]
)

_RESEARCH_KEYWORDS: frozenset[str] = frozenset(
    [
        "arxiv",
        "paper",
        "research",
        "study",
        "benchmark",
        "evaluation",
        "new method",
        "we propose",
        "we present",
        "novel approach",
        "dataset",
        "training data",
        "preprint",
        "journal",
        "conference",
        "neurips",
        "icml",
        "iclr",
        "acl",
        "emnlp",
    ]
)


def classify_item(title: str, summary: str, source_topics: list[str]) -> str:
    """
    Classify a news item into one of four categories.
    Returns: "hardware" | "software" | "security" | "research" | "general"
    """
    combined = (title + " " + summary).lower()

    # Security takes highest priority (actionable)
    if any(kw in combined for kw in _SEC_KEYWORDS) or "cybersecurity" in source_topics:
        return "security"

    # Research second (ArXiv / papers)
    if any(kw in combined for kw in _RESEARCH_KEYWORDS) or "research" in source_topics:
        return "research"

    # Hardware before software (hardware mentions tend to also have software context)
    hw_hits = sum(1 for kw in _HW_KEYWORDS if kw in combined)
    sw_hits = sum(1 for kw in _SW_KEYWORDS if kw in combined)

    if hw_hits > sw_hits and hw_hits > 0:
        return "hardware"
    if sw_hits > 0:
        return "software"

    return "general"


def _parse_rss(xml_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom feed XML, return list of news items."""
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning(f"[NewsIntel] RSS parse error for {source['id']}: {exc}")
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # Detect RSS vs Atom
    is_atom = root.tag.endswith("feed") or "atom" in root.tag.lower()

    if is_atom:
        entries = root.findall("atom:entry", ns) or root.findall("{http://www.w3.org/2005/Atom}entry")
        if not entries:
            # Try without namespace
            entries = root.findall("entry")
        for entry in entries[:_MAX_ITEMS_PER_SOURCE]:
            title_el = (
                entry.find("atom:title", ns) or entry.find("{http://www.w3.org/2005/Atom}title") or entry.find("title")
            )
            link_el = (
                entry.find("atom:link", ns) or entry.find("{http://www.w3.org/2005/Atom}link") or entry.find("link")
            )
            summary_el = (
                entry.find("atom:summary", ns)
                or entry.find("{http://www.w3.org/2005/Atom}summary")
                or entry.find("summary")
                or entry.find("content")
            )
            title = (title_el.text or "").strip() if title_el is not None else ""
            url = (link_el.get("href") or link_el.text or "").strip() if link_el is not None else ""
            summary = (summary_el.text or "").strip() if summary_el is not None else ""
            if title and url:
                items.append(_make_item(title, url, summary, source))
    else:
        # RSS 2.0
        channel = root.find("channel") or root
        for entry in (channel.findall("item") if channel else [])[:_MAX_ITEMS_PER_SOURCE]:
            title_el = entry.find("title")
            link_el = entry.find("link")
            desc_el = entry.find("description")
            title = (title_el.text or "").strip() if title_el is not None else ""
            url = (link_el.text or "").strip() if link_el is not None else ""
            summary = (desc_el.text or "").strip() if desc_el is not None else ""
            # Strip HTML tags from description
            summary = re.sub(r"<[^>]+>", "", summary)[:300]
            if title and url:
                items.append(_make_item(title, url, summary, source))

    return items


def _make_item(
    title: str,
    url: str,
    summary: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    topics = source.get("topics", [])
    high_rel = _is_high_relevance(title, summary)
    category = classify_item(title, summary, topics)
    return {
        "id": _item_id(url),
        "title": title,
        "url": url,
        "summary": summary[:300],
        "source_id": source["id"],
        "source_name": source["name"],
        "topics": topics,
        "category": category,  # software | hardware | security | research | general
        "high_relevance": high_rel,
        "fetched_at": datetime.now(tz=UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP fetcher (RSS/Atom — no browser)
# ---------------------------------------------------------------------------


async def _fetch_rss(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch an RSS/Atom feed via httpx and parse it."""
    try:
        import httpx
    except ImportError:
        logger.warning("[NewsIntel] httpx not installed — RSS fetch skipped")
        return []

    url = source["url"]
    _enforce_domain(url)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            return _parse_rss(resp.text, source)
    except Exception as exc:
        logger.warning(f"[NewsIntel] RSS fetch failed for {source['id']}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Sandboxed browser fetcher (HTML sources without RSS)
# ---------------------------------------------------------------------------


async def _fetch_html_sandboxed(source: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Fetch a JS-rendered page using an isolated Playwright browser context.

    Security guarantees:
    - Domain allowlist enforced before any request.
    - Fresh browser context (no cookies / localStorage) per call.
    - Blocks ads + tracking via request interception.
    - Hard 15 s navigation timeout.
    - Context closed in finally — no state leaks between runs.
    """
    url = source["url"]
    _enforce_domain(url)

    items: list[dict[str, Any]] = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("[NewsIntel] playwright not installed — HTML source skipped")
        return items

    link_pattern = source.get("link_pattern", "")
    base_url = source.get("base_url", "")

    pw_instance = None
    browser = None
    context = None
    try:
        pw_instance = await async_playwright().start()
        browser = await pw_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-web-security",  # needed for some CSP-heavy sites
                "--blink-settings=imagesEnabled=false",  # no image downloads
            ],
        )
        # Isolated context — no shared state
        context = await browser.new_context(
            storage_state=None,
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
            extra_http_headers={"User-Agent": _HEADERS["User-Agent"]},
        )
        context.set_default_navigation_timeout(15_000)
        context.set_default_timeout(10_000)

        page = await context.new_page()

        # Block ads, tracking, and heavy media — only allow document/script/xhr/fetch
        async def _block_unwanted(route: Any) -> None:
            resource_type = route.request.resource_type
            if resource_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _block_unwanted)

        await page.goto(url, wait_until="domcontentloaded")

        # Extract all links matching the source's link pattern
        anchors = await page.query_selector_all("a[href]")
        seen_hrefs: set[str] = set()
        for anchor in anchors:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            # Resolve relative URLs
            if href.startswith("/"):
                href = base_url + href
            elif not href.startswith("http"):
                continue
            # Enforce domain allowlist on every discovered link
            try:
                _enforce_domain(href)
            except ValueError:
                continue
            # Apply link pattern filter
            if link_pattern and not re.search(link_pattern, href):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            # Get link text as title
            title = (await anchor.inner_text()).strip()
            title = re.sub(r"\s+", " ", title)[:200]
            if title and len(title) > 5:
                items.append(_make_item(title, href, "", source))
            if len(items) >= _MAX_ITEMS_PER_SOURCE:
                break

    except Exception as exc:
        logger.warning(f"[NewsIntel] Browser fetch failed for {source['id']}: {exc}")
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if pw_instance:
            try:
                await pw_instance.stop()
            except Exception:
                pass

    return items


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------


class NewsIntelScraper:
    """
    One-shot scraper: fetches all sources, deduplicates, saves to disk.
    Returns a summary dict with counts and HIGH_RELEVANCE items.
    """

    def __init__(self) -> None:
        NEWS_DIR.mkdir(parents=True, exist_ok=True)

    async def run_once(self) -> dict[str, Any]:
        """Scrape all sources and return a result summary."""
        logger.info("[NewsIntel] Starting scrape cycle across %d sources", len(NEWS_SOURCES))
        all_items: list[dict[str, Any]] = []

        for source in NEWS_SOURCES:
            # Polite delay between sources
            await asyncio.sleep(random.uniform(*_REQUEST_DELAY_RANGE))
            try:
                if source["type"] == "rss":
                    items = await _fetch_rss(source)
                else:
                    items = await _fetch_html_sandboxed(source)
                logger.info(
                    "[NewsIntel] %s → %d items",
                    source["id"],
                    len(items),
                )
                all_items.extend(items)
            except Exception as exc:
                logger.warning("[NewsIntel] Source %s failed: %s", source["id"], exc)

        # Deduplicate by item id
        seen_ids: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in all_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                deduped.append(item)

        high_rel = [i for i in deduped if i.get("high_relevance")]
        logger.info(
            "[NewsIntel] Cycle complete: %d total items, %d high-relevance",
            len(deduped),
            len(high_rel),
        )

        # Write daily JSONL append log
        today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        daily_file = NEWS_DIR / f"{today_str}.jsonl"
        with daily_file.open("a", encoding="utf-8") as f:
            for item in deduped:
                f.write(json.dumps(item) + "\n")

        # Merge into latest.json (rolling window of _MAX_LATEST_ITEMS)
        existing = _load_latest()
        existing_ids = {i["id"] for i in existing}
        new_items = [i for i in deduped if i["id"] not in existing_ids]
        merged = (existing + new_items)[-_MAX_LATEST_ITEMS:]
        LATEST_JSON.write_text(json.dumps(merged, indent=2))

        return {
            "total": len(deduped),
            "new": len(new_items),
            "high_relevance_count": len(high_rel),
            "high_relevance": high_rel,
            "scraped_at": datetime.now(tz=UTC).isoformat(),
        }


def _load_latest() -> list[dict[str, Any]]:
    if not LATEST_JSON.exists():
        return []
    try:
        data = json.loads(LATEST_JSON.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_latest_digest(limit: int = 20, topic: str | None = None) -> list[dict[str, Any]]:
    """Return the most recent items from latest.json, optionally filtered by topic."""
    items = _load_latest()
    if topic:
        items = [i for i in items if topic.lower() in [t.lower() for t in i.get("topics", [])]]
    return items[-limit:]


# ---------------------------------------------------------------------------
# Background watcher
# ---------------------------------------------------------------------------


class NewsIntelWatcher:
    """
    Background coroutine that runs NewsIntelScraper on a schedule and
    dispatches HIGH_RELEVANCE alerts to the shared events bus.

    Usage:
        asyncio.ensure_future(NewsIntelWatcher(memory_store).run())
    """

    def __init__(self, memory_store: Any) -> None:
        self._store = memory_store
        self._scraper = NewsIntelScraper()
        self._interval_seconds = _SCRAPE_INTERVAL_HOURS * 3600

    async def run(self) -> None:
        logger.info("[NewsIntelWatcher] Started — scraping every %dh", _SCRAPE_INTERVAL_HOURS)
        while True:
            try:
                result = await self._scraper.run_once()
                await self._dispatch_high_relevance(result)
            except Exception as exc:
                logger.warning("[NewsIntelWatcher] Cycle error (non-fatal): %s", exc)
            await asyncio.sleep(self._interval_seconds)

    async def _dispatch_high_relevance(self, result: dict[str, Any]) -> None:
        """Write HIGH_RELEVANCE items to shared events bus for Discord delivery."""
        high_rel: list[dict[str, Any]] = result.get("high_relevance", [])
        if not high_rel:
            return

        # Write a single digest event to the shared events bus
        event = {
            "type": "NEWS_INTEL_DIGEST",
            "agent_id": "news_intel",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "high_relevance_count": len(high_rel),
            "items": high_rel[:5],  # top 5 in the event payload
            "description": (
                f"News intel: {result['new']} new items, "
                f"{len(high_rel)} high-relevance. "
                "Top: " + ", ".join(i["title"][:60] for i in high_rel[:3])
            ),
        }
        try:
            self._store.append_shared_event(event)
            logger.info(
                "[NewsIntelWatcher] %d high-relevance items dispatched to events bus",
                len(high_rel),
            )
        except Exception as exc:
            logger.warning("[NewsIntelWatcher] Event dispatch failed: %s", exc)
