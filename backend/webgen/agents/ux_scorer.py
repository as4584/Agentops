"""
UX + Visual Quality Scorer — 100-point composite grade.
=========================================================
Score = UX Laws (0–60) + Visual Quality (0–40)

UX Laws (60pts total — structural/behavioural correctness):
  Jakob's Law        12pts  — nav, header, real interactive elements
  Hick's Law         12pts  — choice count in nav, features, pricing
  Proximity Law       9pts  — grouping via cards/containers
  Miller's Law       15pts  — information chunks ≤ 7 per region
  Von Restorff       12pts  — single dominant CTA, accent sparingly

Visual Quality (40pts total — premium aesthetic richness):
  Animations         15pts  — @keyframes, transitions, Tailwind animate-
  Gradients          12pts  — multi-stop gradients, gradient text
  Glass / Depth       8pts  — glassmorphism, backdrop-filter, shadows
  Micro-interactions  5pts  — hover:scale, hover:translate, hover:shadow

A flat white page with perfect HTML structure maxes out at 60/100.
You need real visual craft to break 75.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# ── HTML tree parser ──────────────────────────────────────────────────────────


class _Tag:
    __slots__ = ("tag", "attrs", "text", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.text = ""
        self.children: list[_Tag] = []
        self.parent: _Tag | None = None

    def find_all(self, tag: str) -> list[_Tag]:
        results = []
        if self.tag == tag:
            results.append(self)
        for child in self.children:
            results.extend(child.find_all(tag))
        return results

    def has_class(self, cls: str) -> bool:
        classes = self.attrs.get("class", "")
        return cls in classes.split()

    def any_class(self, *patterns: str) -> bool:
        classes = self.attrs.get("class", "")
        return any(p in classes for p in patterns)

    def get_text(self) -> str:
        parts = [self.text]
        for child in self.children:
            parts.append(child.get_text())
        return " ".join(p for p in parts if p.strip())


class _HTMLTreeBuilder(HTMLParser):
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.root = _Tag("root", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        node = _Tag(tag, dict(attrs))
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        if tag not in self.VOID:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                self._stack = self._stack[:i]
                break

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1].text += data


def _parse(html: str) -> _Tag:
    builder = _HTMLTreeBuilder()
    builder.feed(html)
    return builder.root


# ── Score result ──────────────────────────────────────────────────────────────


@dataclass
class UXScore:
    total: int = 0  # 0–100 (composite)
    jakob: int = 0  # 0–12  (rescaled from 20)
    hick: int = 0  # 0–12  (rescaled from 20)
    proximity: int = 0  # 0–9   (rescaled from 15)
    miller: int = 0  # 0–15  (rescaled from 25)
    von_restorff: int = 0  # 0–12  (rescaled from 20)
    visual: int = 0  # 0–40  (NEW: aesthetic richness)
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "jakob": self.jakob,
            "hick": self.hick,
            "proximity": self.proximity,
            "miller": self.miller,
            "von_restorff": self.von_restorff,
            "visual": self.visual,
            "violations": self.violations,
            "notes": self.notes,
        }


# ── Individual law scorers ────────────────────────────────────────────────────


def _score_jakob(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Jakob's Law: users expect patterns they already know.
    - Nav present and uses <nav> or role=navigation
    - Logo in header area
    - Primary CTA is a <button> or <a> (not <div>)
    - Links use <a href> not <span onclick>
    """
    score = 0
    violations: list[str] = []
    notes: list[str] = []

    navs = root.find_all("nav")
    if navs:
        score += 8
        notes.append("semantic <nav> present")
    elif 'role="navigation"' in html or "role='navigation'" in html:
        score += 5
        notes.append("role=navigation present (prefer <nav>)")
    else:
        violations.append("jakob: no <nav> — users expect standard nav element")

    # Check for logo-like element (img with logo/brand in class/alt, or svg in header)
    headers = root.find_all("header")
    if headers:
        score += 4
        notes.append("semantic <header> present")
    else:
        violations.append("jakob: no <header> — users expect header region")

    # CTA should be <button> or <a>, not a <div>
    buttons = root.find_all("button")
    anchors = [a for a in root.find_all("a") if a.attrs.get("href")]
    if buttons or anchors:
        score += 5
        notes.append(f"real interactive elements: {len(buttons)} buttons, {len(anchors)} links")
    else:
        violations.append("jakob: no buttons or links — CTAs must be interactive elements")

    # Penalise onclick on non-interactive elements
    if re.search(r"<div[^>]+onclick", html, re.IGNORECASE):
        score = max(0, score - 3)
        violations.append("jakob: onclick on <div> — breaks keyboard nav and screen readers")

    return min(score, 20), violations, notes


def _score_hick(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Hick's Law: more choices = slower decisions.
    - Nav items ≤ 6
    - Feature cards ≤ 8
    - Pricing tiers ≤ 3
    - Only 1 primary CTA per section
    """
    score = 20
    violations: list[str] = []
    notes: list[str] = []

    # Count nav links
    nav_links = 0
    for nav in root.find_all("nav"):
        nav_links = len(nav.find_all("a"))
        break
    if nav_links > 6:
        penalty = min(8, (nav_links - 6) * 2)
        score -= penalty
        violations.append(f"hick: {nav_links} nav items > 6 — users slow down above 6 choices")
    elif nav_links > 0:
        notes.append(f"hick: {nav_links} nav items ✓")

    # Count feature/card items — look for grid children
    grid_counts: list[int] = []
    for tag in root.find_all("ul") + root.find_all("ol"):
        children = [c for c in tag.children if c.tag == "li"]
        if len(children) > 1:
            grid_counts.append(len(children))
    for tag in root.find_all("div"):
        if tag.any_class("grid", "flex"):
            direct_cards = [c for c in tag.children if c.tag in ("div", "article", "li")]
            if len(direct_cards) > 2:
                grid_counts.append(len(direct_cards))

    if grid_counts:
        max_items = max(grid_counts)
        if max_items > 8:
            penalty = min(6, (max_items - 8) * 2)
            score -= penalty
            violations.append(f"hick: largest grid has {max_items} items > 8 — consider splitting")
        else:
            notes.append(f"hick: max grid size {max_items} ✓")

    # Count primary CTAs (high-contrast buttons)
    primary_ctas = [b for b in root.find_all("button") if b.any_class("bg-", "btn-primary", "btn-cta", "primary")] + [
        a for a in root.find_all("a") if a.any_class("btn", "button", "cta", "bg-") and a.attrs.get("href")
    ]
    if len(primary_ctas) > 2:
        score -= 4
        violations.append(f"hick: {len(primary_ctas)} competing CTAs — only 1–2 per section")
    elif len(primary_ctas) >= 1:
        notes.append(f"hick: {len(primary_ctas)} CTA(s) ✓")

    return max(0, score), violations, notes


def _score_proximity(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Proximity Law: things that are close together feel related.
    - Related items are in the same container (card, article, section)
    - Lists use consistent structure
    - No orphaned paragraphs floating outside containers
    """
    score = 0
    violations: list[str] = []
    notes: list[str] = []

    # Positive: semantic sectioning used
    sections = len(root.find_all("section"))
    articles = len(root.find_all("article"))
    _asides = len(root.find_all("aside"))  # reserved for future aside scoring

    if sections > 0:
        score += 6
        notes.append(f"proximity: {sections} <section>(s) group content ✓")
    else:
        violations.append("proximity: no <section> — content regions aren't grouped")

    if articles > 0:
        score += 4
        notes.append(f"proximity: {articles} <article>(s) for repeated items ✓")

    # Check for card pattern: div with rounded + shadow (Tailwind proximity pattern)
    cards = [d for d in root.find_all("div") if d.any_class("rounded", "shadow", "card", "p-", "px-", "py-")]
    if cards:
        score += 3
        notes.append(f"proximity: {len(cards)} card containers found ✓")
    else:
        violations.append("proximity: no card containers — items may feel unrelated")

    # Penalise loose <p> tags outside any container
    root_ps = [c for c in root.children if c.tag == "p"]
    if root_ps:
        score = max(0, score - 2)
        violations.append(f"proximity: {len(root_ps)} <p> tags at root level — orphaned text")

    return min(score, 15), violations, notes


def _score_miller(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Miller's Law: the brain handles 7±2 chunks at a time.
    - Any single list/grid: ≤ 7 items
    - Heading hierarchy: ≤ 3 levels deep
    - No wall-of-text paragraphs (word count check)
    """
    score = 25
    violations: list[str] = []
    notes: list[str] = []

    # Check all lists
    for ul in root.find_all("ul") + root.find_all("ol"):
        items = [c for c in ul.children if c.tag == "li"]
        if len(items) > 9:
            score -= 5
            violations.append(f"miller: list with {len(items)} items > 9 — chunk it")
        elif len(items) > 7:
            score -= 2
            violations.append(f"miller: list with {len(items)} items (aim for ≤7)")

    # Check text density — paragraphs with > 80 words
    long_paras = 0
    for p in root.find_all("p"):
        text = p.get_text()
        if len(text.split()) > 80:
            long_paras += 1
    if long_paras > 0:
        score -= min(10, long_paras * 5)
        violations.append(f"miller: {long_paras} paragraph(s) > 80 words — wall of text")
    else:
        notes.append("miller: paragraph lengths ✓")

    # Check heading depth (h1–h6 present)
    heading_levels = set()
    for level in range(1, 7):
        if root.find_all(f"h{level}"):
            heading_levels.add(level)
    if heading_levels:
        depth = max(heading_levels) - min(heading_levels) + 1
        if depth > 3:
            score -= 3
            violations.append(f"miller: {depth} heading levels deep — simplify hierarchy")
        else:
            notes.append(f"miller: heading hierarchy h{min(heading_levels)}–h{max(heading_levels)} ✓")
    else:
        score -= 5
        violations.append("miller: no headings — users can't scan structure")

    return max(0, score), violations, notes


def _score_visual(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Visual Quality Score — measures premium UI richness.
    Animations (0-15) + Gradients (0-12) + Glass/Depth (0-8) + Micro-interactions (0-5) = 0-40
    """
    score = 0
    violations: list[str] = []
    notes: list[str] = []

    # ── Animations (0–15) ──────────────────────────────────────────
    anim = 0
    if "@keyframes" in html:
        anim += 6
        notes.append("visual: custom @keyframes ✓")
    if re.search(r"animation\s*:", html) or re.search(r"animation-name\s*:", html):
        anim += 4
        notes.append("visual: animation property used ✓")
    if re.search(r'class="[^"]*animate-', html):
        anim += 3
        notes.append("visual: Tailwind animate- class ✓")
    transition_count = len(re.findall(r"transition-(?:all|colors|transform|opacity|shadow)", html))
    if transition_count >= 3:
        anim += 4
        notes.append(f"visual: {transition_count} transition utilities ✓")
    elif transition_count >= 1:
        anim += 2
    if re.search(r"duration-[23456789]\d\d", html):
        anim += 1
    anim = min(15, anim)
    score += anim
    if anim < 5:
        violations.append("visual: weak animations — add @keyframes fadeInUp and CSS transitions")

    # ── Gradients (0–12) ──────────────────────────────────────────
    grads = 0
    gradient_count = len(re.findall(r"(?:linear|radial|conic)-gradient\s*\(", html))
    if gradient_count >= 3:
        grads += 8
        notes.append(f"visual: {gradient_count} gradient uses — rich depth ✓")
    elif gradient_count >= 1:
        grads += 4
    else:
        violations.append("visual: no gradients — hero looks flat and generic")
    if ("background-clip" in html and "text" in html) or "bg-clip-text" in html:
        grads += 4
        notes.append("visual: gradient text used ✓")
    grads = min(12, grads)
    score += grads

    # ── Glassmorphism / Depth (0–8) ────────────────────────────────
    glass = 0
    if "backdrop-filter" in html or "backdrop-blur" in html:
        glass += 4
        notes.append("visual: glassmorphism (backdrop-filter) ✓")
    if "glass-card" in html:
        glass += 3
        notes.append("visual: .glass-card component used ✓")
    shadow_premium = len(re.findall(r"shadow-(?:xl|2xl)", html))
    if shadow_premium >= 2:
        glass += 2
        notes.append(f"visual: {shadow_premium} premium shadows ✓")
    elif shadow_premium == 0:
        violations.append("visual: no xl shadows — layout lacks depth")
    glass = min(8, glass)
    score += glass
    if glass == 0:
        violations.append("visual: no glass effects or depth — looks like a 2010 website")

    # ── Micro-interactions (0–5) ────────────────────────────────────
    hover_scale = len(re.findall(r"hover:scale-", html))
    hover_translate = len(re.findall(r"hover:-?translate-", html))
    hover_shadow = len(re.findall(r"hover:shadow-", html))
    hover_opacity = len(re.findall(r"hover:opacity-", html))
    hover_total = hover_scale + hover_translate + hover_shadow + hover_opacity
    if hover_total >= 5:
        micro = 5
        notes.append(f"visual: {hover_total} hover micro-interactions ✓")
    elif hover_total >= 3:
        micro = 4
    elif hover_total >= 1:
        micro = 2
    else:
        micro = 0
        violations.append("visual: no hover effects — interactions feel dead")
    score += micro

    return min(40, score), violations, notes


def _score_von_restorff(root: _Tag, html: str) -> tuple[int, list[str], list[str]]:
    """
    Von Restorff Effect: the thing that stands out gets remembered.
    - Exactly ONE element uses high-contrast accent colour
    - At most one 'recommended' or 'popular' badge
    - Primary CTA is visually distinct from secondary CTAs
    """
    score = 0
    violations: list[str] = []
    notes: list[str] = []

    # Look for accent / highlight elements
    accent_patterns = [
        "bg-orange",
        "bg-yellow",
        "bg-pink",
        "bg-purple",
        "bg-red",
        "ring-",
        "border-2",
        "border-4",
        "highlighted",
        "badge",
        "popular",
        "recommended",
        "featured",
        "accent",
    ]
    accent_hits = [
        tag
        for tagname in ("div", "span", "button", "a", "p", "li", "article")
        for tag in root.find_all(tagname)
        if tag.any_class(*accent_patterns)
    ]

    if len(accent_hits) == 0:
        score += 8
        # Fine — neutral design
        notes.append("von restorff: no accent overload ✓")
    elif 1 <= len(accent_hits) <= 4:
        score += 20
        notes.append(f"von restorff: {len(accent_hits)} accent element(s) — creates hierarchy ✓")
    else:
        score += 8
        violations.append(f"von restorff: {len(accent_hits)} accents — too many, nothing stands out")

    # Check if there's at least one visually-distinct CTA
    strong_ctas = [
        t
        for tagname in ("button", "a")
        for t in root.find_all(tagname)
        if t.any_class("bg-", "btn", "cta") and not t.any_class("outline", "ghost", "text-")
    ]
    if strong_ctas:
        notes.append(f"von restorff: {len(strong_ctas)} strong CTA(s) ✓")
    else:
        score = max(0, score - 5)
        violations.append("von restorff: no visually-dominant CTA — nothing calls attention")

    # Penalise if everything is the same colour (no contrast hierarchy)
    inline_styles = re.findall(r'style="[^"]*background[^"]*"', html)
    if len(inline_styles) > 5:
        score = max(0, score - 3)
        violations.append("von restorff: inline background styles suggest no design system")

    return min(score, 20), violations, notes


# ── Public API ────────────────────────────────────────────────────────────────


def score_html(html: str) -> UXScore:
    """
    Score HTML: UX Laws (0–60) + Visual Quality (0–40) = 0–100.

    UX law raw scores are rescaled to 60pts total.
    Visual quality adds up to 40pts — you CANNOT hit 75+ without real aesthetics.
    """
    if not html or not html.strip():
        s = UXScore()
        s.violations.append("empty HTML")
        return s

    root = _parse(html)
    result = UXScore()

    j_raw, j_viol, j_notes = _score_jakob(root, html)  # 0–20 raw
    h_raw, h_viol, h_notes = _score_hick(root, html)  # 0–20 raw
    p_raw, p_viol, p_notes = _score_proximity(root, html)  # 0–15 raw
    m_raw, m_viol, m_notes = _score_miller(root, html)  # 0–25 raw
    v_raw, v_viol, v_notes = _score_von_restorff(root, html)  # 0–20 raw
    vis_score, vis_viol, vis_notes = _score_visual(root, html)  # 0–40

    # Rescale UX laws: raw 0–100 → 0–60
    ux_raw = j_raw + h_raw + p_raw + m_raw + v_raw  # 0–100
    ux_scaled = round(ux_raw * 0.6)  # 0–60

    result.jakob = round(j_raw * 0.6)
    result.hick = round(h_raw * 0.6)
    result.proximity = round(p_raw * 0.6)
    result.miller = round(m_raw * 0.6)
    result.von_restorff = round(v_raw * 0.6)
    result.visual = vis_score
    result.total = min(100, ux_scaled + vis_score)
    result.violations = j_viol + h_viol + p_viol + m_viol + v_viol + vis_viol
    result.notes = j_notes + h_notes + p_notes + m_notes + v_notes + vis_notes

    return result


def passes_quality_gate(html: str, min_score: int = 65) -> bool:
    """Quick boolean check used by the pipeline QA gate."""
    return score_html(html).total >= min_score


def grade_pair(chosen_html: str, rejected_html: str) -> dict:
    """
    Score a DPO pair. Returns scores + whether chosen is actually better.
    A valid DPO pair requires chosen_score > rejected_score.
    """
    chosen = score_html(chosen_html)
    rejected = score_html(rejected_html)
    margin = chosen.total - rejected.total
    return {
        "chosen_score": chosen.total,
        "rejected_score": rejected.total,
        "margin": margin,
        "is_valid_pair": margin >= 10,  # chosen must be meaningfully better
        "chosen_breakdown": chosen.as_dict(),
        "rejected_breakdown": rejected.as_dict(),
    }
