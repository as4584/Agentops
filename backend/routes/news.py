"""
News Intelligence API — serves scraped news items to the Discord bot and dashboard.

Endpoints:
  GET /news/latest           — recent items, optional ?topic= and ?category= filters
  GET /news/digest           — lightweight summary counts by category
  POST /news/mark-delivered  — mark item IDs as delivered (bot ack)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.auth import require_api_auth
from backend.news.intel_scraper import get_latest_digest

router = APIRouter(prefix="/news", tags=["news"], dependencies=[Depends(require_api_auth)])


@router.get("/latest")
async def get_latest_news(
    limit: int = Query(default=20, le=100),
    topic: str | None = Query(default=None),
    category: str | None = Query(default=None),
    high_relevance_only: bool = Query(default=False),
) -> dict[str, Any]:
    """
    Return recent news items from latest.json.
    Filters: topic (e.g. 'deepseek'), category ('software'|'hardware'|'security'|'research'),
             high_relevance_only.
    """
    items = get_latest_digest(limit=100, topic=topic)

    if category:
        items = [i for i in items if i.get("category", "general") == category.lower()]

    if high_relevance_only:
        items = [i for i in items if i.get("high_relevance")]

    # Sort: high relevance first, then by fetched_at desc
    items = sorted(
        items,
        key=lambda i: (not i.get("high_relevance"), i.get("fetched_at", "")),
        reverse=True,
    )[:limit]

    return {
        "items": items,
        "count": len(items),
        "filters": {"topic": topic, "category": category, "high_relevance_only": high_relevance_only},
    }


@router.get("/digest")
async def get_news_digest() -> dict[str, Any]:
    """Return item counts grouped by category — for dashboard widgets."""
    all_items = get_latest_digest(limit=200)
    categories: dict[str, int] = {}
    high_rel_count = 0
    for item in all_items:
        cat = item.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        if item.get("high_relevance"):
            high_rel_count += 1

    return {
        "total": len(all_items),
        "high_relevance": high_rel_count,
        "by_category": categories,
        "sources_active": len({i.get("source_id") for i in all_items}),
    }
