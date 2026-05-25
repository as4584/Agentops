"""
Discord Post History API — durable log of everything Agentop posts to Discord.

Endpoints:
  GET /discord/posts  — recent channel posts, filterable by event_type and channel_name
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.auth import require_api_auth

router = APIRouter(prefix="/discord", tags=["discord"], dependencies=[Depends(require_api_auth)])


@router.get("/posts")
async def get_discord_posts(
    event_type: str | None = Query(default=None, description="Filter by event type e.g. DISCORD_NEWS_POSTED"),
    channel_name: str | None = Query(default=None, description="Filter by channel name e.g. news-intel"),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    """
    Return recent Discord post records from the durable post log.
    Orchad uses this to answer 'what did Agentop post to Discord today?'
    """
    from backend.discord_bot import get_discord_post_history

    posts = get_discord_post_history(
        event_type=event_type,
        channel_name=channel_name,
        limit=limit,
    )
    return {"posts": posts, "count": len(posts)}
