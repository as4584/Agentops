# social_media_agent — handoff v2026-04-12

## Status

| Component | State | Notes |
|---|---|---|
| `backend/routes/social_media.py` | ACTIVE | TikTok + Facebook + Instagram + analytics routes all wired |
| `backend/routes/auth_oauth.py` | ACTIVE | TikTok OAuth login, callback, refresh, status endpoints working |
| `backend/skills/social_media_manager/skill.json` | ACTIVE | Skill manifest enabled, registered in registry |
| TikTok OAuth tokens | BROKEN | Token EXPIRED as of ~2026-04-10 — needs refresh via `POST /auth/tiktok/refresh` |
| TikTok developer app "Social_media manager" | BROKEN | In Draft status — blocked on demo video showing app posting; app ID 7623523415232677906 |
| Meta (Facebook + Instagram) credentials | BROKEN | Only `FACEBOOK_PAGE_ID` is set; `META_APP_ID`, `META_APP_SECRET`, `META_PAGE_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ID` all missing |
| `docs/SOCIAL_MEDIA_PLATFORM_RULES.md` | ACTIVE | Exists — referenced in skill manifest |
| Scheduled polling (analytics, token refresh) | STUBBED | Cron schedule defined in skill.json but no scheduler wired to execute it |
| Token auto-refresh | STUBBED | `POST /auth/tiktok/refresh` endpoint implemented; no automated trigger hooked up |
| `backend/memory/social_media/tiktok_tokens.json` | ACTIVE | File exists with open_id + scope; access_token is stale |

---

## Session Decisions

- TikTok `is_aigc: true` set as default on all video posts — required by TikTok policy for AI-generated content; must never be removed
- `POST /auth/tiktok/refresh` was implemented (reads from `.env` `TIKTOK_REFRESH_TOKEN` or falls back to saved JSON) — prior memory said it wasn't; it is now
- Meta non-retryable error codes `{3, 10, 368}` halt with 403, code `190` returns 401, code `506` returns 409 — explicit handling prevents silent retry loops
- Instagram publish checks `/content_publishing_limit` quota before every post — prevents silent failures at the 100-post/24h wall
- Analytics results are cached to `backend/memory/social_media/analytics_cache.json` — avoids redundant API calls; cache is not TTL-invalidated, manual or scheduled refresh required
- Post history written to `backend/memory/social_media/posted_content.json` on every successful post — source of truth for what was published

---

## Live Config

```
TIKTOK_CLIENT_KEY: SET (in .env)
TIKTOK_CLIENT_SECRET: SET (in .env)
TIKTOK_ACCESS_TOKEN: SET but EXPIRED (obtained ~2026-04-10, ~86400s TTL)
TIKTOK_OPEN_ID: -0000r_nQjhPL481kgLEK3iRyK1a9VHd89Fv
TIKTOK_REFRESH_TOKEN: SET (in .env)
TIKTOK_REDIRECT_URI: http://localhost:8000/auth/tiktok/callback
TIKTOK_APP_ID: 7623523415232677906

FACEBOOK_PAGE_ID: SET (in .env)
META_APP_ID: NOT SET
META_APP_SECRET: NOT SET
META_PAGE_ACCESS_TOKEN: NOT SET
INSTAGRAM_BUSINESS_ID: NOT SET

TikTok scopes granted: video.list, video.publish, user.info.basic
TikTok token expires_at unix: 1775864019 (EXPIRED)
```

---

## Memory Snapshot

**In memory (`project_social_media_manager.md`):**
- TikTok OAuth done, all 5 TikTok vars set in `.env`
- Meta NOT started — no credentials
- TikTok app in Draft, blocked on demo video
- Doppler `agentop` project missing all 9 social credentials

**MISSING from memory:**
- TikTok token expiry state (token is now EXPIRED — memory says it was valid)
- `POST /auth/tiktok/refresh` is implemented — memory says it was not
- `FACEBOOK_PAGE_ID` is now set in `.env` — memory says Meta is entirely NOT started

**Action needed:** Update `project_social_media_manager.md` to reflect expired token and partial Meta progress.

---

## Open Questions

1. Is the TikTok app still in Draft? Has the demo video been recorded yet to unblock app review?
2. When will Meta credentials (developers.facebook.com) be obtained to unlock Facebook + Instagram routes?
3. Should the cron schedule in `skill.json` be wired to an actual scheduler (APScheduler, system cron, or Agentop GSD)? Currently defined but never executes.
4. Should the 9 social credentials be added to Doppler `agentop` project? Currently only in `.env`.
5. Token auto-refresh is implemented but not triggered — should a GSD task or system cron call `POST /auth/tiktok/refresh` daily at 2am as specified in the skill schedule?

---

## Next Session Starts Here

Run `POST /auth/tiktok/refresh` to get a new access token, then update `TIKTOK_ACCESS_TOKEN` and `TIKTOK_REFRESH_TOKEN` in `.env` with the values from `backend/memory/social_media/tiktok_tokens.json`.
