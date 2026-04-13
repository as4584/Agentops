"""Social Media Manager routes — TikTok, Facebook, Instagram posting + analytics."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/social", tags=["social_media"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIKTOK_BASE = "https://open.tiktokapis.com"
META_GRAPH_BASE = "https://graph.facebook.com/v22.0"
ANALYTICS_CACHE_PATH = Path("backend/memory/social_media/analytics_cache.json")
POST_HISTORY_PATH = Path("backend/memory/social_media/posted_content.json")
POST_QUEUE_PATH = Path("backend/memory/social_media/post_queue.json")
ALERT_HISTORY_PATH = Path("backend/memory/social_media/alert_history.json")
IG_PERFORMANCE_LOG_PATH = Path("backend/memory/social_media/instagram_performance_log.json")

HYPOTHESIS_THRESHOLD = 15  # minimum posts before switching to pattern_recognition mode

# Non-retryable Meta error codes — halt and alert operator
META_NON_RETRYABLE = {3, 10, 368}
META_RETRYABLE = {1, 2, 4, 17, 341}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_memory_dir() -> None:
    Path("backend/memory/social_media").mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    _ensure_memory_dir()
    if path.exists():
        return json.loads(path.read_text())
    return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_memory_dir()
    path.write_text(json.dumps(data, indent=2))


def _tiktok_headers() -> dict[str, str]:
    token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="TIKTOK_ACCESS_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _meta_page_token() -> str:
    token = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="META_PAGE_ACCESS_TOKEN not set")
    return token


def _meta_page_id() -> str:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "")
    if not page_id:
        raise HTTPException(status_code=500, detail="FACEBOOK_PAGE_ID not set")
    return page_id


def _ig_business_id() -> str:
    ig_id = os.getenv("INSTAGRAM_BUSINESS_ID", "")
    if not ig_id:
        raise HTTPException(status_code=500, detail="INSTAGRAM_BUSINESS_ID not set")
    return ig_id


def _handle_meta_error(data: dict) -> None:
    """Raise HTTPException with context for known Meta error codes."""
    error = data.get("error", {})
    code = error.get("code", 0)
    msg = error.get("message", "Unknown Meta API error")
    if code in META_NON_RETRYABLE:
        raise HTTPException(
            status_code=403,
            detail=f"[NON-RETRYABLE] Meta error {code}: {msg}. Alert operator — do not retry.",
        )
    if code == 190:
        raise HTTPException(
            status_code=401,
            detail="Meta access token expired (code 190). Refresh META_PAGE_ACCESS_TOKEN.",
        )
    if code == 506:
        raise HTTPException(
            status_code=409,
            detail="Duplicate post (code 506). Modify content or caption before retrying.",
        )
    if code:
        raise HTTPException(status_code=400, detail=f"Meta error {code}: {msg}")


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class TikTokVideoPost(BaseModel):
    title: str = Field(..., max_length=2200)
    privacy_level: str = Field(
        default="SELF_ONLY",
        description="SELF_ONLY | MUTUAL_FOLLOW_FRIENDS | FOLLOWER_OF_CREATOR | PUBLIC_TO_EVERYONE",
    )
    source: str = Field(default="PULL_FROM_URL", description="PULL_FROM_URL | FILE_UPLOAD")
    video_url: str | None = None  # for PULL_FROM_URL
    video_size: int | None = None  # bytes, for FILE_UPLOAD
    chunk_size: int | None = None  # bytes, for FILE_UPLOAD
    total_chunk_count: int | None = None  # for FILE_UPLOAD
    disable_duet: bool = False
    disable_stitch: bool = False
    disable_comment: bool = False
    is_aigc: bool = True  # default True — always flag AI content
    brand_content_toggle: bool = False


class FacebookPost(BaseModel):
    message: str
    link: str | None = None
    published: bool = True
    scheduled_publish_time: int | None = None  # Unix timestamp


class FacebookPhotoPost(BaseModel):
    url: str
    caption: str = ""
    published: bool = True


class FacebookVideoPost(BaseModel):
    file_url: str
    title: str
    description: str = ""
    published: bool = True


class InstagramMediaPost(BaseModel):
    media_type: str = Field(description="IMAGE | VIDEO | REELS | STORIES")
    image_url: str | None = None
    video_url: str | None = None
    caption: str = ""
    is_carousel_item: bool = False


class InstagramCarouselPost(BaseModel):
    children: list[str] = Field(..., description="List of media container IDs")
    caption: str = ""


# ---------------------------------------------------------------------------
# TikTok endpoints
# ---------------------------------------------------------------------------


@router.post("/tiktok/post/init")
async def tiktok_init_post(payload: TikTokVideoPost) -> dict:
    """Initialize a TikTok Direct Post upload. Returns upload_url and publish_id."""
    body: dict[str, Any] = {
        "post_info": {
            "title": payload.title,
            "privacy_level": payload.privacy_level,
            "disable_duet": payload.disable_duet,
            "disable_stitch": payload.disable_stitch,
            "disable_comment": payload.disable_comment,
            "is_aigc": payload.is_aigc,
            "brand_content_toggle": payload.brand_content_toggle,
        },
        "source_info": {"source": payload.source},
    }
    if payload.source == "PULL_FROM_URL":
        if not payload.video_url:
            raise HTTPException(status_code=422, detail="video_url required for PULL_FROM_URL")
        body["source_info"]["video_url"] = payload.video_url
    else:
        for field in ("video_size", "chunk_size", "total_chunk_count"):
            if getattr(payload, field) is None:
                raise HTTPException(status_code=422, detail=f"{field} required for FILE_UPLOAD")
        body["source_info"]["video_size"] = payload.video_size
        body["source_info"]["chunk_size"] = payload.chunk_size
        body["source_info"]["total_chunk_count"] = payload.total_chunk_count

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TIKTOK_BASE}/v2/post/publish/video/init/",
            headers=_tiktok_headers(),
            json=body,
        )
    data = resp.json()
    if data.get("error", {}).get("code") != "ok":
        err = data.get("error", {})
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"TikTok error {err.get('code')}: {err.get('message')}",
        )

    # Log to post history
    history = _load_json(POST_HISTORY_PATH, [])
    history.append(
        {
            "platform": "tiktok",
            "publish_id": data.get("data", {}).get("publish_id"),
            "title": payload.title,
            "initiated_at": int(time.time()),
            "status": "initiated",
        }
    )
    _save_json(POST_HISTORY_PATH, history)

    return data


@router.post("/tiktok/post/status")
async def tiktok_post_status(publish_id: str) -> dict:
    """Check the status of a TikTok publish job."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TIKTOK_BASE}/v2/post/publish/status/fetch/",
            headers=_tiktok_headers(),
            json={"publish_id": publish_id},
        )
    return resp.json()


@router.post("/tiktok/analytics")
async def tiktok_analytics(video_ids: list[str]) -> dict:
    """Fetch analytics for up to 20 TikTok video IDs."""
    if len(video_ids) > 20:
        raise HTTPException(status_code=422, detail="Max 20 video IDs per request (TikTok limit)")

    body = {
        "filters": {"video_ids": video_ids},
        "fields": [
            "id",
            "title",
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "create_time",
            "duration",
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TIKTOK_BASE}/v2/video/query/",
            headers=_tiktok_headers(),
            json=body,
        )
    data = resp.json()

    # Cache results
    cache = _load_json(ANALYTICS_CACHE_PATH, {})
    cache["tiktok"] = {
        "fetched_at": int(time.time()),
        "videos": data.get("data", {}).get("videos", []),
    }
    _save_json(ANALYTICS_CACHE_PATH, cache)

    return data


# ---------------------------------------------------------------------------
# Facebook endpoints
# ---------------------------------------------------------------------------


@router.post("/facebook/post/text")
async def facebook_post_text(payload: FacebookPost) -> dict:
    """Post a text (or link) update to the Facebook Page."""
    page_id = _meta_page_id()
    token = _meta_page_token()

    params: dict[str, Any] = {
        "message": payload.message,
        "access_token": token,
        "published": payload.published,
    }
    if payload.link:
        params["link"] = payload.link
    if payload.scheduled_publish_time and not payload.published:
        params["scheduled_publish_time"] = payload.scheduled_publish_time

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{page_id}/feed", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    _append_post_history("facebook", "text", data.get("id"), payload.message[:80])
    return data


@router.post("/facebook/post/photo")
async def facebook_post_photo(payload: FacebookPhotoPost) -> dict:
    """Post a photo to the Facebook Page."""
    page_id = _meta_page_id()
    token = _meta_page_token()

    params = {
        "url": payload.url,
        "caption": payload.caption,
        "published": str(payload.published).lower(),
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{page_id}/photos", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    _append_post_history("facebook", "photo", data.get("id"), payload.caption[:80])
    return data


@router.post("/facebook/post/video")
async def facebook_post_video(payload: FacebookVideoPost) -> dict:
    """Post a video to the Facebook Page."""
    page_id = _meta_page_id()
    token = _meta_page_token()

    params = {
        "file_url": payload.file_url,
        "title": payload.title,
        "description": payload.description,
        "published": str(payload.published).lower(),
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{page_id}/videos", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    _append_post_history("facebook", "video", data.get("id"), payload.title)
    return data


@router.get("/facebook/insights")
async def facebook_page_insights(
    metric: str = "page_impressions,page_engaged_users,page_fan_adds,page_views_total",
    period: str = "day",
) -> dict:
    """Fetch Facebook Page insights."""
    page_id = _meta_page_id()
    token = _meta_page_token()

    params = {
        "metric": metric,
        "period": period,
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{META_GRAPH_BASE}/{page_id}/insights", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    cache = _load_json(ANALYTICS_CACHE_PATH, {})
    cache["facebook"] = {"fetched_at": int(time.time()), "insights": data.get("data", [])}
    _save_json(ANALYTICS_CACHE_PATH, cache)
    return data


# ---------------------------------------------------------------------------
# Instagram endpoints
# ---------------------------------------------------------------------------


@router.post("/instagram/media/create")
async def instagram_create_container(payload: InstagramMediaPost) -> dict:
    """Step 1: Create an Instagram media container. Returns creation_id."""
    ig_id = _ig_business_id()
    token = _meta_page_token()

    if payload.media_type == "IMAGE" and not payload.image_url:
        raise HTTPException(status_code=422, detail="image_url required for IMAGE media_type")
    if payload.media_type in ("VIDEO", "REELS", "STORIES") and not payload.video_url:
        raise HTTPException(status_code=422, detail="video_url required for VIDEO/REELS/STORIES")

    params: dict[str, Any] = {
        "media_type": payload.media_type,
        "caption": payload.caption,
        "access_token": token,
    }
    if payload.image_url:
        params["image_url"] = payload.image_url
    if payload.video_url:
        params["video_url"] = payload.video_url
    if payload.is_carousel_item:
        params["is_carousel_item"] = True

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{ig_id}/media", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)
    return data


@router.get("/instagram/media/status/{container_id}")
async def instagram_container_status(container_id: str) -> dict:
    """Step 2: Check container status. Poll until FINISHED before publishing."""
    token = _meta_page_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{META_GRAPH_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
        )
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)
    return data


@router.post("/instagram/media/publish/{creation_id}")
async def instagram_publish(creation_id: str) -> dict:
    """Step 3: Publish a FINISHED Instagram container."""
    ig_id = _ig_business_id()
    token = _meta_page_token()

    # Check quota before publishing
    quota = await _check_ig_quota(ig_id, token)
    if quota.get("quota_usage", 0) >= 100:
        raise HTTPException(
            status_code=429,
            detail="Instagram 100-post/24h limit reached. Cannot publish until quota resets.",
        )

    params = {"creation_id": creation_id, "access_token": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{ig_id}/media_publish", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    _append_post_history("instagram", "media", data.get("id"), f"container:{creation_id}")
    return data


@router.post("/instagram/carousel/publish")
async def instagram_publish_carousel(payload: InstagramCarouselPost) -> dict:
    """Create and publish an Instagram carousel (up to 10 items)."""
    if len(payload.children) > 10:
        raise HTTPException(status_code=422, detail="Instagram carousel max 10 items")

    ig_id = _ig_business_id()
    token = _meta_page_token()

    # Create carousel container
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(payload.children),
        "caption": payload.caption,
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{META_GRAPH_BASE}/{ig_id}/media", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    creation_id = data.get("id")
    if not creation_id:
        raise HTTPException(status_code=500, detail="Failed to get carousel creation_id")

    return await instagram_publish(creation_id)


@router.get("/instagram/insights/profile")
async def instagram_profile_insights(
    metric: str = "impressions,reach,profile_views,accounts_engaged",
    period: str = "day",
) -> dict:
    """Fetch Instagram profile-level insights."""
    ig_id = _ig_business_id()
    token = _meta_page_token()

    params = {"metric": metric, "period": period, "access_token": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{META_GRAPH_BASE}/{ig_id}/insights", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)

    cache = _load_json(ANALYTICS_CACHE_PATH, {})
    cache["instagram"] = {"fetched_at": int(time.time()), "insights": data.get("data", [])}
    _save_json(ANALYTICS_CACHE_PATH, cache)
    return data


@router.get("/instagram/insights/post/{media_id}")
async def instagram_post_insights(media_id: str) -> dict:
    """Fetch insights for a specific Instagram post."""
    token = _meta_page_token()
    params = {
        "metric": "impressions,reach,likes,comments,shares,saved,video_views",
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{META_GRAPH_BASE}/{media_id}/insights", params=params)
    data = resp.json()
    if "error" in data:
        _handle_meta_error(data)
    return data


# ---------------------------------------------------------------------------
# Instagram performance log + analyze_performance
# ---------------------------------------------------------------------------


@router.post("/instagram/performance/log")
async def instagram_log_post(entry: dict) -> dict:
    """Append a post entry to instagram_performance_log.json.

    Caller provides any subset of the schema; missing fields default to UNKNOWN/0.
    """
    template: dict[str, Any] = {
        "post_id": "UNKNOWN",
        "type": "UNKNOWN",
        "topic": "UNKNOWN",
        "hook": "UNKNOWN",
        "posted_at": "UNKNOWN",
        "views": 0,
        "saves": 0,
        "comments": 0,
        "follows": 0,
        "reach": 0,
        "source_breakdown": {"feed_pct": 0, "profile_pct": 0},
        "hypotheses_tested": [],
    }
    template.update(entry)
    log = _load_json(IG_PERFORMANCE_LOG_PATH, [])
    log.append(template)
    _save_json(IG_PERFORMANCE_LOG_PATH, log)
    return {"status": "logged", "total_posts": len(log)}


@router.get("/instagram/analyze")
async def instagram_analyze_performance() -> dict:
    """analyze_performance — data_confidence gate.

    < 15 posts  → hypothesis mode: generate 3 testable hypotheses, tag posts
    >= 15 posts → pattern_recognition mode: surface confirmed patterns
    """
    log: list[dict] = _load_json(IG_PERFORMANCE_LOG_PATH, [])
    post_count = len(log)

    if post_count < HYPOTHESIS_THRESHOLD:
        mode = "hypothesis"
        prompt = (
            f"You have insufficient data for pattern recognition. "
            f"Given these {post_count} posts, generate 3 testable hypotheses "
            f"about what might drive saves/reach. "
            f"Tag each post with which hypothesis it's testing. "
            f"Flag when you have enough data to confirm or reject each one."
        )
        return {
            "mode": mode,
            "post_count": post_count,
            "threshold": HYPOTHESIS_THRESHOLD,
            "posts_until_pattern_mode": HYPOTHESIS_THRESHOLD - post_count,
            "agent_prompt": prompt,
            "posts": log,
        }
    else:
        mode = "pattern_recognition"
        saves_avg = (
            sum(p.get("saves", 0) for p in log) / post_count if post_count else 0
        )
        reach_avg = (
            sum(p.get("reach", 0) for p in log) / post_count if post_count else 0
        )
        top_by_saves = sorted(log, key=lambda p: p.get("saves", 0), reverse=True)[:3]
        return {
            "mode": mode,
            "post_count": post_count,
            "averages": {"saves": round(saves_avg, 2), "reach": round(reach_avg, 2)},
            "top_posts_by_saves": top_by_saves,
            "posts": log,
        }


@router.get("/instagram/performance/backfill")
async def instagram_backfill_performance() -> dict:
    """Attempt to backfill instagram_performance_log.json from the Graph API.

    Reads post history for Instagram entries, fetches per-post insights,
    and writes to the performance log. Requires INSTAGRAM_BUSINESS_ID and
    META_PAGE_ACCESS_TOKEN to be set — returns a dry summary if credentials
    are missing.
    """
    history: list[dict] = _load_json(POST_HISTORY_PATH, [])
    ig_posts = [p for p in history if p.get("platform") == "instagram"]

    if not ig_posts:
        return {"status": "no_instagram_posts_in_history", "logged": 0}

    ig_id = os.getenv("INSTAGRAM_BUSINESS_ID", "")
    token = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    if not ig_id or not token:
        return {
            "status": "credentials_missing",
            "detail": "INSTAGRAM_BUSINESS_ID and META_PAGE_ACCESS_TOKEN required",
            "posts_found": len(ig_posts),
            "logged": 0,
        }

    log: list[dict] = _load_json(IG_PERFORMANCE_LOG_PATH, [])
    existing_ids = {e["post_id"] for e in log}
    added = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for post in ig_posts:
            post_id = post.get("post_id")
            if not post_id or post_id in existing_ids:
                continue

            # Fetch per-post insights
            resp = await client.get(
                f"{META_GRAPH_BASE}/{post_id}/insights",
                params={
                    "metric": "impressions,reach,likes,comments,shares,saved",
                    "access_token": token,
                },
            )
            raw = resp.json()
            if "error" in raw:
                continue  # skip on error, don't halt full backfill

            metrics: dict[str, int] = {
                m["name"]: m.get("values", [{}])[0].get("value", 0)
                for m in raw.get("data", [])
            }

            entry: dict[str, Any] = {
                "post_id": post_id,
                "type": post.get("type", "UNKNOWN"),
                "topic": "UNKNOWN",
                "hook": "UNKNOWN",
                "posted_at": post.get("posted_at", "UNKNOWN"),
                "views": metrics.get("impressions", 0),
                "saves": metrics.get("saved", 0),
                "comments": metrics.get("comments", 0),
                "follows": 0,  # Graph API does not expose per-post follows
                "reach": metrics.get("reach", 0),
                "source_breakdown": {"feed_pct": 0, "profile_pct": 0},
                "hypotheses_tested": [],
            }
            log.append(entry)
            existing_ids.add(post_id)
            added += 1

    if added:
        _save_json(IG_PERFORMANCE_LOG_PATH, log)

    return {"status": "ok", "posts_found": len(ig_posts), "logged": added}


# ---------------------------------------------------------------------------
# Analytics dashboard
# ---------------------------------------------------------------------------


@router.get("/analytics/cache")
async def get_analytics_cache() -> dict:
    """Return the latest cached analytics for all platforms."""
    return _load_json(ANALYTICS_CACHE_PATH, {})


@router.get("/history")
async def get_post_history() -> list:
    """Return full post history across all platforms."""
    return _load_json(POST_HISTORY_PATH, [])


@router.get("/alerts")
async def get_alert_history() -> list:
    """Return fired alert history."""
    return _load_json(ALERT_HISTORY_PATH, [])


@router.get("/status")
async def social_media_status() -> dict:
    """Return credential readiness status without exposing secret values."""
    return {
        "tiktok": {
            "client_key_set": bool(os.getenv("TIKTOK_CLIENT_KEY")),
            "access_token_set": bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
            "open_id_set": bool(os.getenv("TIKTOK_OPEN_ID")),
        },
        "facebook": {
            "app_id_set": bool(os.getenv("META_APP_ID")),
            "page_token_set": bool(os.getenv("META_PAGE_ACCESS_TOKEN")),
            "page_id_set": bool(os.getenv("FACEBOOK_PAGE_ID")),
        },
        "instagram": {
            "business_id_set": bool(os.getenv("INSTAGRAM_BUSINESS_ID")),
            "page_token_set": bool(os.getenv("META_PAGE_ACCESS_TOKEN")),
        },
        "analytics_cache_exists": ANALYTICS_CACHE_PATH.exists(),
        "post_count": len(_load_json(POST_HISTORY_PATH, [])),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _append_post_history(platform: str, post_type: str, post_id: str | None, label: str) -> None:
    history = _load_json(POST_HISTORY_PATH, [])
    history.append(
        {
            "platform": platform,
            "type": post_type,
            "post_id": post_id,
            "label": label,
            "posted_at": int(time.time()),
        }
    )
    _save_json(POST_HISTORY_PATH, history)


async def _check_ig_quota(ig_id: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{META_GRAPH_BASE}/{ig_id}/content_publishing_limit",
            params={"fields": "config,quota_usage", "access_token": token},
        )
    data = resp.json()
    if data.get("data"):
        return data["data"][0]
    return {}
