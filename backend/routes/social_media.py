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
