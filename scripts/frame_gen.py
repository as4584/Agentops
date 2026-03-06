#!/usr/bin/env python3
"""
Frame Generator — Pixel-accurate UI mockups via PIL
====================================================
Renders Reddit posts, tweets, news headlines, YouTube screenshots as
crisp 1080×1920 9:16 frames. No AI needed. Reads correctly, looks real.

All frames use:
  - Dark background (#0d1117 / #1a1a2e)
  - Cold blue accent
  - System fonts (DejaVu, Liberation, Ubuntu) or bundled fallback
  - Proper padding, shadows, typography hierarchy
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Font loading ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent

# Try to find a good system font, fall back to PIL default
FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = FONT_BOLD_PATHS if bold else FONT_PATHS
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ── Colours ───────────────────────────────────────────────────────────────────
BG_DARK   = (13, 17, 23)       # deep charcoal
BG_CARD   = (22, 27, 34)       # card background
BG_DEEP   = (8, 10, 14)        # letterbox bars
ACCENT    = (100, 160, 255)    # cold blue
ACCENT2   = (255, 80, 80)      # red for negative numbers
TEXT_PRI  = (230, 237, 243)    # primary text
TEXT_SEC  = (139, 148, 158)    # secondary / meta
TEXT_MUT  = (80, 90, 100)      # muted
GOLD      = (212, 175, 55)     # upvote gold
RED_STAMP = (220, 50, 50)
GREEN     = (63, 185, 80)

W, H = 1080, 1920
MARGIN = 72


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _new_canvas(bg=BG_DARK) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    return img, draw


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, border=None, border_width=2):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                           outline=border, width=border_width)


def _wrap_text(draw, text: str, x: int, y: int, max_width: int,
               font, fill, line_spacing: int = 8) -> int:
    """Draw wrapped text, return final y position."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), line, font=font)
        cy += bbox[3] - bbox[1] + line_spacing
    return cy


def _vignette(img: Image.Image, strength: float = 0.45) -> Image.Image:
    """Apply subtle dark vignette."""
    vig = Image.new("RGB", img.size, (0, 0, 0))
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    cx, cy = img.width // 2, img.height // 2
    rx, ry = int(cx * 1.1), int(cy * 0.95)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=180))
    inv_mask = Image.fromarray(255 - __import__("numpy").array(mask))
    blend = Image.composite(vig, img, inv_mask)
    return Image.blend(img, blend, strength)


# ── Frame types ───────────────────────────────────────────────────────────────

def reddit_post(
    out_path: Path,
    subreddit: str,
    title: str,
    upvotes: str,
    top_comment: str = "",
    awarded: bool = True,
    poster: str = "u/GamingNewsFeed",
    timestamp: str = "6 hours ago",
):
    img, draw = _new_canvas()

    # subtle gradient header strip
    for i in range(120):
        alpha = int(40 * (1 - i / 120))
        draw.line([(0, i), (W, i)], fill=(100, 160, 255, alpha))

    # Subreddit pill
    pill_font = _load_font(28, bold=True)
    sub_text = f"r/{subreddit}"
    bb = draw.textbbox((0, 0), sub_text, font=pill_font)
    pw = bb[2] - bb[0] + 32
    _rounded_rect(draw, [MARGIN, 140, MARGIN + pw, 140 + 44], 22, (30, 50, 80))
    draw.text((MARGIN + 16, 147), sub_text, font=pill_font, fill=ACCENT)

    # poster + timestamp
    meta_font = _load_font(26)
    draw.text((MARGIN + pw + 20, 150), f"{poster}  ·  {timestamp}", font=meta_font, fill=TEXT_MUT)

    # Card
    card_top = 220
    card_bot = 1480
    _rounded_rect(draw, [MARGIN - 8, card_top, W - MARGIN + 8, card_bot], 20, BG_CARD)

    # Title
    title_font = _load_font(62, bold=True)
    title_y = _wrap_text(draw, title, MARGIN + 24, card_top + 48,
                         W - MARGIN * 2 - 48, title_font, TEXT_PRI, line_spacing=12)

    # Divider
    draw.line([(MARGIN + 24, title_y + 24), (W - MARGIN - 24, title_y + 24)],
              fill=(50, 60, 70), width=1)

    # Top comment
    if top_comment:
        cmt_label_font = _load_font(26, bold=True)
        draw.text((MARGIN + 24, title_y + 44), "Top comment:", font=cmt_label_font, fill=TEXT_SEC)
        cmt_font = _load_font(44)
        _wrap_text(draw, f'"{top_comment}"', MARGIN + 24, title_y + 90,
                   W - MARGIN * 2 - 48, cmt_font, TEXT_PRI, line_spacing=10)

    # Footer bar: upvotes + awards
    foot_y = card_bot - 80
    draw.line([(MARGIN + 24, foot_y - 8), (W - MARGIN - 24, foot_y - 8)],
              fill=(40, 50, 60), width=1)
    up_font = _load_font(38, bold=True)
    draw.text((MARGIN + 24, foot_y + 4), f"▲ {upvotes}", font=up_font, fill=GOLD)
    if awarded:
        draw.text((MARGIN + 200, foot_y + 4), "🏆 Gold  🥈 Silver  ✨ Helpful", font=_load_font(32), fill=TEXT_SEC)

    # Subtle cold blue bottom glow
    for i in range(60):
        opacity = int(30 * (1 - i / 60))
        y = H - i
        draw.line([(0, y), (W, y)], fill=(100, 160, 255))

    img = _vignette(img)
    img.save(out_path, "PNG", optimize=True)


def tweet_card(
    out_path: Path,
    handle: str,
    display_name: str,
    text: str,
    likes: str,
    retweets: str,
    timestamp: str = "Mar 5, 2026",
    verified: bool = True,
):
    img, draw = _new_canvas()

    # Card
    card_y = 320
    _rounded_rect(draw, [MARGIN - 8, card_y, W - MARGIN + 8, 1560], 24, BG_CARD,
                 border=(50, 70, 90), border_width=2)

    # Header: avatar placeholder + name
    av_x, av_y = MARGIN + 16, card_y + 40
    draw.ellipse([av_x, av_y, av_x + 80, av_y + 80], fill=(50, 80, 120))
    draw.text((av_x + 28, av_y + 22), "X", font=_load_font(42, bold=True), fill=ACCENT)

    name_font = _load_font(44, bold=True)
    draw.text((av_x + 100, av_y + 4), display_name, font=name_font, fill=TEXT_PRI)
    if verified:
        draw.text((av_x + 100 + draw.textbbox((0,0), display_name, font=name_font)[2] + 8,
                   av_y + 8), "✓", font=_load_font(38), fill=ACCENT)
    draw.text((av_x + 100, av_y + 46), f"@{handle}  ·  {timestamp}", font=_load_font(30), fill=TEXT_SEC)

    # Tweet text
    tw_font = _load_font(52)
    text_y = _wrap_text(draw, text, MARGIN + 16, card_y + 160,
                        W - MARGIN * 2 - 32, tw_font, TEXT_PRI, line_spacing=14)

    # Divider
    draw.line([(MARGIN + 16, text_y + 24), (W - MARGIN - 16, text_y + 24)],
              fill=(40, 55, 70), width=1)

    # Metrics
    met_font = _load_font(36)
    met_y = text_y + 44
    draw.text((MARGIN + 16, met_y), f"♡  {likes}", font=met_font, fill=TEXT_SEC)
    draw.text((MARGIN + 220, met_y), f"↺  {retweets}", font=met_font, fill=TEXT_SEC)
    draw.text((W - MARGIN - 140, met_y), "⋯  Share", font=met_font, fill=TEXT_SEC)

    # X logo watermark — top right
    draw.text((W - MARGIN - 60, card_y + 40), "✕", font=_load_font(48, bold=True), fill=(80, 90, 100))

    img = _vignette(img)
    img.save(out_path, "PNG", optimize=True)


def news_headline(
    out_path: Path,
    outlet: str,
    headline: str,
    subhead: str = "",
    timestamp: str = "March 5, 2026",
    outlet_color: tuple = ACCENT,
    breaking: bool = False,
):
    img, draw = _new_canvas(BG_DEEP)

    # Top outlet bar
    _rounded_rect(draw, [0, 0, W, 130], 0, (15, 25, 40))
    outlet_font = _load_font(54, bold=True)
    ow = draw.textbbox((0, 0), outlet, font=outlet_font)[2]
    draw.text(((W - ow) // 2, 38), outlet, font=outlet_font, fill=outlet_color)

    if breaking:
        brk_font = _load_font(30, bold=True)
        brk_text = "● BREAKING NEWS"
        bw = draw.textbbox((0, 0), brk_text, font=brk_font)[2]
        _rounded_rect(draw, [(W - bw) // 2 - 16, 148, (W + bw) // 2 + 16, 196], 8, RED_STAMP)
        draw.text(((W - bw) // 2, 152), brk_text, font=brk_font, fill=(255, 240, 240))

    # Main card
    card_top = 220 if not breaking else 220
    _rounded_rect(draw, [MARGIN - 8, card_top, W - MARGIN + 8, 1600], 20, BG_CARD)

    # Timestamp
    ts_font = _load_font(28)
    draw.text((MARGIN + 24, card_top + 32), timestamp.upper(), font=ts_font, fill=TEXT_MUT)

    # Headline
    hl_font = _load_font(68, bold=True)
    hl_y = _wrap_text(draw, headline, MARGIN + 24, card_top + 80,
                      W - MARGIN * 2 - 48, hl_font, TEXT_PRI, line_spacing=14)

    # Divider rule
    draw.line([(MARGIN + 24, hl_y + 24), (MARGIN + 180, hl_y + 24)],
              fill=outlet_color, width=3)

    # Subhead
    if subhead:
        sub_font = _load_font(44)
        _wrap_text(draw, subhead, MARGIN + 24, hl_y + 52,
                   W - MARGIN * 2 - 48, sub_font, TEXT_SEC, line_spacing=10)

    img = _vignette(img)
    img.save(out_path, "PNG", optimize=True)


def youtube_screenshot(
    out_path: Path,
    title: str,
    views: str,
    channel: str,
    duration: str = "1:47:22",
    subs: str = "34.9M subscribers",
):
    img, draw = _new_canvas()

    # Fake video thumbnail area — dark cinematic bar
    thumb_h = 580
    _rounded_rect(draw, [MARGIN - 8, 180, W - MARGIN + 8, 180 + thumb_h], 16, (10, 12, 16))
    # Film grain texture
    import random
    rng = random.Random(42)
    for _ in range(4000):
        px = rng.randint(MARGIN, W - MARGIN)
        py = rng.randint(180, 180 + thumb_h)
        v = rng.randint(20, 45)
        draw.point((px, py), fill=(v, v, v + 10))

    # Submarine silhouette (geometric approximation)
    cx, cy = W // 2, 180 + thumb_h // 2 + 20
    # Body
    draw.ellipse([cx - 180, cy - 55, cx + 180, cy + 55], fill=(30, 25, 20))
    # Conning tower
    draw.rectangle([cx - 25, cy - 100, cx + 25, cy - 55], fill=(28, 23, 18))
    # Periscope
    draw.rectangle([cx + 5, cy - 130, cx + 12, cy - 100], fill=(28, 23, 18))
    # Blood-red water tint beneath
    for i in range(30):
        alpha = int(60 * (i / 30))
        draw.line([(MARGIN, cy + 56 + i), (W - MARGIN, cy + 56 + i)],
                  fill=(80 + alpha, 5, 5))

    # Duration badge
    dur_font = _load_font(30, bold=True)
    dw = draw.textbbox((0, 0), duration, font=dur_font)[2]
    _rounded_rect(draw, [W - MARGIN - dw - 24, 180 + thumb_h - 52,
                         W - MARGIN - 4, 180 + thumb_h - 10], 6, (0, 0, 0))
    draw.text((W - MARGIN - dw - 12, 180 + thumb_h - 48), duration, font=dur_font, fill=(240, 240, 240))

    # Channel info
    ch_y = 180 + thumb_h + 30
    draw.ellipse([MARGIN, ch_y, MARGIN + 68, ch_y + 68], fill=(30, 50, 80))
    draw.text((MARGIN + 22, ch_y + 14), "M", font=_load_font(40, bold=True), fill=ACCENT)
    draw.text((MARGIN + 82, ch_y + 2), channel, font=_load_font(38, bold=True), fill=TEXT_PRI)
    draw.text((MARGIN + 82, ch_y + 40), subs, font=_load_font(30), fill=TEXT_SEC)

    # Video title
    title_font = _load_font(56, bold=True)
    _wrap_text(draw, title, MARGIN, ch_y + 100, W - MARGIN * 2,
               title_font, TEXT_PRI, line_spacing=12)

    # View count — big, prominent
    vc_y = ch_y + 300
    vc_font = _load_font(72, bold=True)
    vc_w = draw.textbbox((0, 0), views, font=vc_font)[2]
    draw.text(((W - vc_w) // 2, vc_y), views, font=vc_font, fill=ACCENT)
    views_label = "VIEWS"
    vl_font = _load_font(32)
    vl_w = draw.textbbox((0, 0), views_label, font=vl_font)[2]
    draw.text(((W - vl_w) // 2, vc_y + 80), views_label, font=vl_font, fill=TEXT_MUT)

    img = _vignette(img)
    img.save(out_path, "PNG", optimize=True)


def rejection_letters(
    out_path: Path,
    studios: list[str],
    stamp_text: str = "PASSED",
):
    img, draw = _new_canvas()

    studios = studios[:3]
    card_h = 380
    gap = 60
    start_y = (H - (len(studios) * card_h + (len(studios) - 1) * gap)) // 2

    for i, studio in enumerate(studios):
        y = start_y + i * (card_h + gap)
        # Slight tilt for each letter
        tilts = [-2, 0, 2]
        # Draw as flat card (PIL doesn't do rotate per-layer well, keep straight)
        _rounded_rect(draw, [MARGIN, y, W - MARGIN, y + card_h], 12,
                      (240, 235, 225))  # paper white

        # Letterhead rule
        draw.rectangle([MARGIN, y, W - MARGIN, y + 8], fill=(200, 190, 180))

        # Studio name
        s_font = _load_font(44, bold=True)
        draw.text((MARGIN + 32, y + 24), studio, font=s_font, fill=(40, 40, 50))

        # Body text
        b_font = _load_font(28)
        body = "After careful consideration, we regret that this project does not align with our current slate."
        _wrap_text(draw, body, MARGIN + 32, y + 88, W - MARGIN * 2 - 64,
                   b_font, (80, 80, 90), line_spacing=8)

        # Red PASSED / DECLINED stamp
        stamp_font = _load_font(72, bold=True)
        sw = draw.textbbox((0, 0), stamp_text, font=stamp_font)[2]
        sh = draw.textbbox((0, 0), stamp_text, font=stamp_font)[3]
        sx = W - MARGIN - sw - 32
        sy = y + card_h - sh - 32
        # Rough stamp border
        draw.rectangle([sx - 12, sy - 8, sx + sw + 12, sy + sh + 8],
                       outline=RED_STAMP, width=5)
        draw.text((sx, sy), stamp_text, font=stamp_font, fill=(*RED_STAMP, 180))

    img = _vignette(img)
    img.save(out_path, "PNG", optimize=True)


def stat_callout(
    out_path: Path,
    label: str,
    value: str,
    sublabel: str = "",
    context_line: str = "",
    value_color: tuple = ACCENT,
):
    """Full-screen centered stat — e.g. '$50,000,000' — cinematic impact frame."""
    img, draw = _new_canvas(BG_DEEP)

    # Subtle horizontal lines (cinematic scan lines)
    for y in range(0, H, 4):
        if y % 8 == 0:
            draw.line([(0, y), (W, y)], fill=(20, 22, 28))

    # Label
    lbl_font = _load_font(40)
    lw = draw.textbbox((0, 0), label.upper(), font=lbl_font)[2]
    draw.text(((W - lw) // 2, H // 2 - 240), label.upper(), font=lbl_font, fill=TEXT_MUT)

    # Value — giant
    val_font = _load_font(130, bold=True)
    vw = draw.textbbox((0, 0), value, font=val_font)[2]
    # Glow effect via multiple offset draws
    for dx, dy, alpha in [(-2, -2, 30), (2, -2, 30), (-2, 2, 30), (2, 2, 30)]:
        r, g, b = value_color
        glow_col = (min(r + 20, 255), min(g + 20, 255), min(b + 60, 255))
        draw.text(((W - vw) // 2 + dx, H // 2 - 120 + dy), value, font=val_font, fill=glow_col)
    draw.text(((W - vw) // 2, H // 2 - 120), value, font=val_font, fill=value_color)

    # Sub-label
    if sublabel:
        sl_font = _load_font(44)
        slw = draw.textbbox((0, 0), sublabel, font=sl_font)[2]
        draw.text(((W - slw) // 2, H // 2 + 80), sublabel, font=sl_font, fill=TEXT_SEC)

    # Context
    if context_line:
        ctx_font = _load_font(36)
        ctxw = draw.textbbox((0, 0), context_line, font=ctx_font)[2]
        draw.text(((W - ctxw) // 2, H // 2 + 160), context_line, font=ctx_font, fill=TEXT_MUT)

    # Bottom accent line
    draw.rectangle([MARGIN, H - 120, W - MARGIN, H - 116], fill=value_color)

    img = _vignette(img, strength=0.55)
    img.save(out_path, "PNG", optimize=True)


# ── Generate all 8 frames for Markiplier / Iron Lung ─────────────────────────

def generate_markiplier_frames(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Rendering 8 UI mockup frames → {out_dir}")

    # 1 — HOOK: YouTube screenshot
    youtube_screenshot(
        out_dir / "frame_1.png",
        title="I played Iron Lung.",
        views="40,287,445 views",
        channel="Markiplier",
        duration="34:17",
        subs="34.9M subscribers",
    )
    print("  [1/8] YouTube screenshot ✓")

    # 2 — RISING ACTION: Stat callout
    stat_callout(
        out_dir / "frame_2.png",
        label="game cost",
        value="$6.00",
        sublabel="Iron Lung — by David Szymanski",
        context_line="Built in 2 weeks. No studio. No budget.",
        value_color=ACCENT,
    )
    print("  [2/8] Stat callout ($6) ✓")

    # 3 — CONFLICT: Rejection letters
    rejection_letters(
        out_dir / "frame_3.png",
        studios=["Netflix", "Amazon Studios", "A24"],
        stamp_text="PASSED",
    )
    print("  [3/8] Rejection letters ✓")

    # 4 — COMEBACK: Stat callout — $50M
    stat_callout(
        out_dir / "frame_4.png",
        label="Markiplier self-financed",
        value="$50M",
        sublabel="No studio. No distributor.",
        context_line="His own money. His own rules.",
        value_color=(255, 200, 60),
    )
    print("  [4/8] Stat callout ($50M) ✓")

    # 5 — SECOND RISING: Tweet thread
    tweet_card(
        out_dir / "frame_5.png",
        handle="variety",
        display_name="Variety",
        text="EXCLUSIVE: Markiplier has self-financed a $50M feature adaptation of Iron Lung. No studio involved. He controls IP, production, and distribution. 'My audience is the only studio I need.'",
        likes="284K",
        retweets="91.2K",
        timestamp="Mar 4, 2026",
        verified=True,
    )
    print("  [5/8] Tweet (Variety) ✓")

    # 6 — SECOND CONFLICT: News headline
    news_headline(
        out_dir / "frame_6.png",
        outlet="The Hollywood Reporter",
        headline="Every Major Studio Passed on the Iron Lung Movie. A YouTuber Greenlit It Himself.",
        subhead="Markiplier's $50M bet could rewrite the rules of creator-owned cinema.",
        timestamp="March 5, 2026",
        outlet_color=(220, 40, 40),
        breaking=True,
    )
    print("  [6/8] News headline ✓")

    # 7 — FINAL COMEBACK: Reddit post
    reddit_post(
        out_dir / "frame_7.png",
        subreddit="videos",
        title="If the Iron Lung movie works, creators own Hollywood forever. No studios needed.",
        upvotes="198K",
        top_comment="Imagine if this is how the studio system finally dies.",
        poster="u/FilmTheoryPod",
        timestamp="14 hours ago",
        awarded=True,
    )
    print("  [7/8] Reddit post ✓")

    # 8 — PAYOFF: Stat callout — release date
    stat_callout(
        out_dir / "frame_8.png",
        label="Iron Lung — the movie",
        value="OCT 2026",
        sublabel="Directed by Markiplier × David Szymanski",
        context_line="Self-distributed. No middlemen.",
        value_color=ACCENT,
    )
    print("  [8/8] Payoff callout ✓")

    print(f"  All 8 frames saved.")


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/frames/markiplier_v3_mockup")
    generate_markiplier_frames(out)
    print("Done.")
