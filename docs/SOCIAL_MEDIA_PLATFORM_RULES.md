# Social Media Platform Rules — Agentop Reference
> Last updated: 2026-03-31  
> Maintained by: social_media_manager skill  
> Purpose: Canonical constraints the social media manager agent MUST respect when posting content or reading analytics. Never post, query, or schedule anything that violates a rule in this document.

---

## 1. TikTok — Content Posting API (Direct Post)

### Developer Portal
- **Dashboard:** https://developers.tiktok.com
- **App creation:** https://developers.tiktok.com/apps/
- **Required product to add:** `Content Posting API`

### Authentication
| Credential | Env Var | How to Get |
|---|---|---|
| Client Key | `TIKTOK_CLIENT_KEY` | TikTok for Developers → App → App Key |
| Client Secret | `TIKTOK_CLIENT_SECRET` | TikTok for Developers → App → App Secret |
| User Access Token | `TIKTOK_ACCESS_TOKEN` | OAuth flow via Login Kit |
| Open ID | `TIKTOK_OPEN_ID` | Returned in OAuth token exchange response |

**OAuth scopes required:**
- `video.publish` — post videos
- `video.list` — query video analytics/metrics

**Token flow:**
```
GET https://www.tiktok.com/v2/auth/authorize/
  ?client_key={TIKTOK_CLIENT_KEY}
  &response_type=code
  &scope=video.publish,video.list
  &redirect_uri={YOUR_REDIRECT_URI}
  &state={CSRF_TOKEN}

POST https://open.tiktokapis.com/v2/oauth/token/
  Body: code, client_key, client_secret, grant_type=authorization_code, redirect_uri
  Returns: access_token, refresh_token, open_id, scope, expires_in
```

### Posting — Direct Post API
**Base URL:** `https://open.tiktokapis.com`

**Step 1 — Initialize upload:**
```
POST /v2/post/publish/video/init/
Authorization: Bearer {TIKTOK_ACCESS_TOKEN}
Content-Type: application/json; charset=UTF-8

{
  "post_info": {
    "title": "...",              // max 2200 UTF-16 runes
    "privacy_level": "...",      // SELF_ONLY | MUTUAL_FOLLOW_FRIENDS | FOLLOWER_OF_CREATOR | PUBLIC_TO_EVERYONE
    "disable_duet": false,
    "disable_stitch": false,
    "disable_comment": false,
    "brand_content_toggle": false,
    "is_aigc": false,
    "video_cover_timestamp_ms": 0
  },
  "source_info": {
    "source": "FILE_UPLOAD",     // or PULL_FROM_URL
    "video_size": 12345678,      // bytes (FILE_UPLOAD only)
    "chunk_size": 10485760,      // 10MB recommended (FILE_UPLOAD only)
    "total_chunk_count": 2       // (FILE_UPLOAD only)
    // OR for PULL_FROM_URL:
    // "video_url": "https://..."  // must be on verified domain
  }
}
```

**Step 2 — Upload video:**
```
PUT {upload_url from step 1 response}
Content-Range: bytes 0-{chunk_size-1}/{total_size}
Content-Type: video/mp4
Body: binary chunk data
```

**Step 3 — Check status:**
```
POST /v2/post/publish/status/fetch/
Body: { "publish_id": "..." }
```

### TikTok Content Rules
| Rule | Constraint |
|---|---|
| Title max length | 2200 UTF-16 runes |
| Per-user rate limit | 6 requests/minute per access token |
| Daily post cap | Enforced per-user and per-client (exact number varies by audit status) |
| PULL_FROM_URL domain | Must be on verified domain list in app settings |
| Unaudited app visibility | All posts forced to **private** until app passes TikTok audit |
| AIGC flag | MUST set `is_aigc: true` if content is AI-generated — violation = ban risk |
| Brand content | MUST set `brand_content_toggle: true` for paid partnerships |
| Spam ban | Error `spam_risk_user_banned_from_posting` — do NOT retry; alert operator |

### TikTok Analytics API
**Endpoint:** `POST /v2/video/query/`  
**Scope:** `video.list`

```
POST https://open.tiktokapis.com/v2/video/query/
Authorization: Bearer {TIKTOK_ACCESS_TOKEN}
Body: {
  "filters": {
    "video_ids": ["<id1>", "<id2>"]   // max 20 per request
  },
  "fields": ["id", "title", "view_count", "like_count", "comment_count", "share_count", "create_time", "duration"]
}
```

**Available metrics per video:**
- `view_count` — total views
- `like_count` — total likes
- `comment_count` — total comments
- `share_count` — total shares
- `duration` — video length in seconds
- `cover_image_url` — thumbnail (TTL refreshed on query)

**Analytics polling rule:** Poll at most every **5 minutes** per video set to stay within rate limits. Store results in `backend/memory/social_analytics.json`.

---

## 2. Facebook — Graph API (Pages)

### Developer Portal
- **Dashboard:** https://developers.facebook.com
- **App creation:** https://developers.facebook.com/apps/
- **Required products to add:** Facebook Login, Pages API

### Authentication
| Credential | Env Var | How to Get |
|---|---|---|
| App ID | `META_APP_ID` | App Dashboard → App ID |
| App Secret | `META_APP_SECRET` | App Dashboard → App Secret |
| Page Access Token | `META_PAGE_ACCESS_TOKEN` | Graph Explorer → generate long-lived page token |
| Facebook Page ID | `FACEBOOK_PAGE_ID` | Page About section or Graph API `/me/accounts` |

**Required permissions:**
- `pages_manage_posts` — create/delete posts on pages
- `pages_read_engagement` — read page insights
- `pages_show_list` — list pages
- `read_insights` — access page analytics

**Getting a long-lived Page Token:**
```
1. Get short-lived User Token via Login (scope: pages_manage_posts,pages_read_engagement,read_insights)
2. Exchange for long-lived User Token:
   GET /oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id={META_APP_ID}
     &client_secret={META_APP_SECRET}
     &fb_exchange_token={SHORT_LIVED_TOKEN}
3. Get Page Token from long-lived User Token:
   GET /{FACEBOOK_PAGE_ID}?fields=access_token&access_token={LONG_LIVED_USER_TOKEN}
   → Store this as META_PAGE_ACCESS_TOKEN (never expires while page role active)
```

### Posting to Facebook Pages
**Base URL:** `https://graph.facebook.com/v22.0`

**Text + Link post:**
```
POST /{FACEBOOK_PAGE_ID}/feed
  ?access_token={META_PAGE_ACCESS_TOKEN}
  Body: {
    "message": "Your post text here",
    "link": "https://...",          // optional
    "published": true               // false = schedule
  }
```

**Photo post:**
```
POST /{FACEBOOK_PAGE_ID}/photos
  Body: {
    "url": "https://publicly-hosted-image.jpg",
    "caption": "Photo caption",
    "published": true,
    "access_token": "{META_PAGE_ACCESS_TOKEN}"
  }
```

**Video post:**
```
POST /{FACEBOOK_PAGE_ID}/videos
  Body: {
    "file_url": "https://publicly-hosted-video.mp4",
    "title": "Video title",
    "description": "Description",
    "published": true,
    "access_token": "{META_PAGE_ACCESS_TOKEN}"
  }
```

**Scheduled post (future publish):**
```
POST /{FACEBOOK_PAGE_ID}/feed
  Body: {
    "message": "...",
    "published": false,
    "scheduled_publish_time": 1700000000  // Unix timestamp, min 10 min from now, max 6 months
  }
```

### Facebook Content Rules
| Rule | Constraint |
|---|---|
| Message max length | 63,206 characters |
| Duplicate post | Error 506 — must modify content before reposting |
| Scheduled time | Minimum 10 minutes from now, maximum 6 months out |
| Link scraping | Error 1609005 — validate URL is publicly accessible |
| Rate limit (app-level) | Error 4 — back off exponentially, do not hammer |
| Rate limit (user-level) | Error 17 — user-scoped throttle, wait before retry |
| Policy violation | Error 368 — do NOT immediately retry; alert operator |
| Permission denied | Error 10/200-299 — do NOT retry; check app permissions |

### Facebook Page Insights
```
GET /{FACEBOOK_PAGE_ID}/insights
  ?metric=page_impressions,page_engaged_users,page_fan_adds,page_views_total,page_post_engagements
  &period=day
  &since={unix_timestamp}
  &until={unix_timestamp}
  &access_token={META_PAGE_ACCESS_TOKEN}
```

**Available metrics:**
| Metric | Description |
|---|---|
| `page_impressions` | Total times content seen |
| `page_impressions_unique` | Unique accounts that saw content |
| `page_engaged_users` | Unique accounts that engaged |
| `page_fan_adds` | New page likes |
| `page_fan_removes` | Page unlikes |
| `page_views_total` | Total page profile views |
| `page_post_engagements` | Reactions, comments, shares |
| `page_video_views` | Total video views |
| `page_video_views_unique` | Unique video viewers |

**Periods:** `day` · `week` · `days_28` · `month` · `lifetime`

---

## 3. Instagram — Graph API (Business/Creator)

### Authentication
| Credential | Env Var | How to Get |
|---|---|---|
| Instagram Business Account ID | `INSTAGRAM_BUSINESS_ID` | Graph API → `/{FACEBOOK_PAGE_ID}?fields=instagram_business_account` |
| Page Access Token | `META_PAGE_ACCESS_TOKEN` | Same token as Facebook (shared) |

**Required permissions (Facebook Login path):**
- `instagram_basic`
- `instagram_content_publish`
- `pages_read_engagement`
- `instagram_manage_insights` (for analytics)

### Posting to Instagram

**Step 1 — Create media container:**
```
POST /{INSTAGRAM_BUSINESS_ID}/media
  Body: {
    "image_url": "https://publicly-hosted.jpg",   // for IMAGE
    // OR
    "video_url": "https://publicly-hosted.mp4",   // for VIDEO/REELS
    "media_type": "IMAGE",          // IMAGE | VIDEO | REELS | STORIES
    "caption": "Post caption #hashtag @mention",
    "location_id": "...",           // optional
    "user_tags": [...],             // optional
    "access_token": "{META_PAGE_ACCESS_TOKEN}"
  }
```

**Step 2 — Poll container status:**
```
GET /{CONTAINER_ID}?fields=status_code&access_token={META_PAGE_ACCESS_TOKEN}
Statuses: IN_PROGRESS → FINISHED → publish | ERROR | EXPIRED (24h TTL)
Poll every 5 seconds until FINISHED or ERROR.
```

**Step 3 — Publish:**
```
POST /{INSTAGRAM_BUSINESS_ID}/media_publish
  Body: {
    "creation_id": "{CONTAINER_ID}",
    "access_token": "{META_PAGE_ACCESS_TOKEN}"
  }
```

**Carousel post (multi-image):**
```
1. Create a container for each item (with is_carousel_item: true)
2. Create parent container: media_type=CAROUSEL, children=[id1,id2,...] (max 10)
3. Publish parent container via media_publish
```

### Instagram Content Rules
| Rule | Constraint |
|---|---|
| Daily API publish limit | **100 posts per 24-hour moving window** |
| Check remaining quota | `GET /{IG_ID}/content_publishing_limit?fields=config,quota_usage` |
| Image format | JPEG only — no MPO, JPS, PNG (convert before upload) |
| Video format | MP4 recommended, H.264 codec |
| Carousel max items | 10 (images, videos, or mixed) |
| Carousel crop | All images cropped to first image's aspect ratio (default 1:1) |
| Stories | Only available to **business accounts** (not creator accounts) |
| Consumer accounts | API access BLOCKED — must be Professional (Business or Creator) |
| Media hosting | Media URL must be **publicly accessible** at time of posting |
| Container TTL | Containers expire after **24 hours** if not published |
| Reels aspect ratio | 9:16 recommended, min 0.01:1 max 10:1 |

### Instagram Insights (Profile-Level)
```
GET /{INSTAGRAM_BUSINESS_ID}/insights
  ?metric=impressions,reach,profile_views,follower_count,accounts_engaged
  &period=day
  &since={unix_timestamp}
  &until={unix_timestamp}
  &access_token={META_PAGE_ACCESS_TOKEN}
```

**Post-level insights:**
```
GET /{IG_MEDIA_ID}/insights
  ?metric=impressions,reach,likes,comments,shares,saved,video_views
  &access_token={META_PAGE_ACCESS_TOKEN}
```

**Available profile metrics:**
| Metric | Period |
|---|---|
| `impressions` | day / week / days_28 |
| `reach` | day / week / days_28 |
| `profile_views` | day / week / days_28 |
| `follower_count` | day (lifetime only via audience) |
| `accounts_engaged` | day / week / days_28 |
| `total_interactions` | day / week / days_28 |

**Note:** `User Insights` is the only Instagram endpoint that supports **time-based pagination**. All other endpoints use cursor-based pagination. Ordering results is not supported.

---

## 4. Graph API — Error Handling Reference

All agents MUST handle these codes before retrying:

| Code | Name | Action |
|---|---|---|
| 1 | API Unknown | Retry with 5s backoff |
| 2 | API Service | Retry with 30s backoff |
| 3 | API Method | Check permissions — do NOT retry |
| 4 | API Too Many Calls | Exponential backoff, alert operator |
| 10 | Permission Denied | Check app permissions — do NOT retry |
| 17 | User Too Many Calls | Backoff 60s minimum |
| 190 | Token Expired | Refresh token — do NOT retry with old token |
| 200-299 | Permission variable | Check scope — do NOT retry |
| 341 | App limit reached | Back off and reduce frequency |
| 368 | Policy violation | Stop immediately — alert operator |
| 506 | Duplicate post | Modify content before retry |
| 1609005 | Link error | Validate URL — do NOT retry as-is |

**Retry policy:**
```python
RETRYABLE_CODES = {1, 2, 4, 17, 341}
NON_RETRYABLE_CODES = {3, 10, 368}  # alert operator immediately
MAX_RETRIES = 3
BACKOFF_SECONDS = [5, 30, 120]
```

---

## 5. 24/7 Analytics Monitoring Schedule

The scheduler runs these jobs automatically (via `AgentopScheduler` / APScheduler):

| Job | Schedule | Action |
|---|---|---|
| `tiktok_analytics_poll` | Every 15 minutes | Fetch view/like/comment/share counts for all tracked videos |
| `instagram_insights_poll` | Every 30 minutes | Fetch profile impressions, reach, and post insights |
| `facebook_page_insights_poll` | Every 60 minutes | Fetch page impressions, engaged users, fan adds |
| `tiktok_trending_check` | Every 6 hours | Check view velocity against `VIEW_VELOCITY_THRESHOLD` |
| `content_performance_report` | Daily at `UPLOAD_HOUR_UTC` | Aggregate 24h metrics into daily report |
| `token_refresh_check` | Daily at 02:00 UTC | Warn if access tokens expire within 7 days |

**Alert thresholds (configurable via env):**
- `VIEW_VELOCITY_THRESHOLD=1000` — alert if a video gets this many views in `VIEW_VELOCITY_WINDOW_HOURS`
- `SOCIAL_ENGAGEMENT_ALERT_THRESHOLD=0.05` — alert if engagement rate drops below 5%
- `SOCIAL_FOLLOWER_DROP_THRESHOLD=50` — alert if followers drop by this many in 24h

---

## 6. Developer App Setup Checklist

### TikTok App
- [ ] Go to https://developers.tiktok.com → Create App → Select "Web" app type
- [ ] Add product: **Content Posting API**
- [ ] Add product: **Login Kit** (required for OAuth)
- [ ] Set redirect URI in App settings (e.g., `http://localhost:8000/auth/tiktok/callback`)
- [ ] Copy `Client Key` → `TIKTOK_CLIENT_KEY` in `.env`
- [ ] Copy `Client Secret` → `TIKTOK_CLIENT_SECRET` in `.env`
- [ ] Run OAuth flow to get access token → store in `TIKTOK_ACCESS_TOKEN` + `TIKTOK_OPEN_ID`
- [ ] Submit app for audit to enable public posting (otherwise all posts are private)
- [ ] For PULL_FROM_URL: verify your domain in app settings

### Meta (Facebook + Instagram) App
- [ ] Go to https://developers.facebook.com → Create App → Select "Business" type
- [ ] Add products: **Facebook Login**, **Pages API**
- [ ] For Instagram: ensure your IG account is a **Professional (Business or Creator)** account
- [ ] Link Instagram account to a Facebook Page in Meta Business Suite
- [ ] Add `instagram_content_publish` and `instagram_manage_insights` permissions in App Review
- [ ] Generate long-lived Page Access Token (see auth section above)
- [ ] Copy App ID → `META_APP_ID`, App Secret → `META_APP_SECRET`
- [ ] Copy Page Token → `META_PAGE_ACCESS_TOKEN`
- [ ] Get Page ID → `FACEBOOK_PAGE_ID`
- [ ] Get Instagram Business ID → `INSTAGRAM_BUSINESS_ID`
- [ ] Submit permissions for App Review (required for `instagram_content_publish` in production)
- [ ] Add test users during development (App Review not required for test users)

---

## 7. Environment Variables Required

Add these to `.env` (and `.env.example`):

```bash
# TikTok
TIKTOK_CLIENT_KEY=your_tiktok_client_key
TIKTOK_CLIENT_SECRET=your_tiktok_client_secret
TIKTOK_ACCESS_TOKEN=your_tiktok_user_access_token
TIKTOK_OPEN_ID=your_tiktok_open_id
TIKTOK_REFRESH_TOKEN=your_tiktok_refresh_token

# Meta (Facebook + Instagram)
META_APP_ID=your_meta_app_id
META_APP_SECRET=your_meta_app_secret
META_PAGE_ACCESS_TOKEN=your_long_lived_page_access_token
FACEBOOK_PAGE_ID=your_facebook_page_id
INSTAGRAM_BUSINESS_ID=your_instagram_business_account_id

# Social Media Manager Behavior
SOCIAL_ANALYTICS_POLL_INTERVAL_SECONDS=300
SOCIAL_POST_QUEUE_ENABLED=true
VIEW_VELOCITY_THRESHOLD=1000
VIEW_VELOCITY_WINDOW_HOURS=24
SOCIAL_ENGAGEMENT_ALERT_THRESHOLD=0.05
SOCIAL_FOLLOWER_DROP_THRESHOLD=50
```
