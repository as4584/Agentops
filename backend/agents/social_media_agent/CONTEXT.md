# social_media_agent — context v0.1

## State
- Instagram Graph API: BROKEN (INSTAGRAM_BUSINESS_ID + META_PAGE_ACCESS_TOKEN not set)
- Performance log: 0 posts, schema v1
- Pattern engine: hypothesis mode (insufficient data — threshold: 15 posts)
- Brief queue: empty

## Skills
- fetch_instagram_insights: STUBBED (no credentials)
- analyze_performance: ACTIVE (hypothesis mode — endpoint GET /social/instagram/analyze)
- generate_brief: STUBBED
- publish_post: STUBBED

## Open decisions
- [ ] Carousel slide copy: generate all at once or slide-by-slide?
- [ ] Discord /social command: which channel receives output?

## Do not change
- Post scheduling tied to peak hours config in gateway/config.py
- Brand voice rules in skills/social_media/voice.md

## Rules
- Keep this file under 100 lines
- Update State section after every session
- Never add prose paragraphs
