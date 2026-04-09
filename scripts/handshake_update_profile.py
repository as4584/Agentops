#!/usr/bin/env python3
"""
scripts/handshake_update_profile.py — Update Lex's Handshake profile.

Uses inline editing modals on https://app.joinhandshake.com/profiles/xgb9rw.

Usage:
    python scripts/handshake_update_profile.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Profile data — sourced from Alexander_Santiago_All_Skills.md
# ---------------------------------------------------------------------------

PROFILE = {
    "headline": "Multi-agent AI systems | custom LLM training (94.9%) | K8s home lab",  # max 75 chars
    "bio": (
        "Sophomore at NJIT (Info Systems) building production AI. "
        "Custom 3B LLM router (94.9%), C router 200x faster, Rust 54.6x compression. "
        "Freelance AI dev for IDS and Pro Body For Life. "
        "K8s home lab, 5 deployments. "
        "Stack: Python, TypeScript, Rust, C."
    ),
    "website": "https://lexmakesit.com",
    "linkedin": "https://linkedin.com/in/lexmakesit",
    "github": "https://github.com/as4584",
    "skills": [
        "Python", "TypeScript", "JavaScript", "React", "Next.js",
        "FastAPI", "Node.js", "SQL", "PostgreSQL", "SQLite",
        "Docker", "Kubernetes", "Git", "GitHub Actions",
        "Machine Learning", "LLMs", "LangGraph", "Rust", "C", "Lua",
        "REST APIs", "Vercel", "DigitalOcean", "Linux", "Bash",
        "Agile", "Test-Driven Development", "Tailwind CSS",
    ],
    "experience": [
        {
            "title": "Freelance AI & Web Developer",
            "org": "LexMakesIt (Self-Employed)",
            "start_month": "September",
            "start_year": "2024",
            "end": "Present",
            "description": (
                "Cold-called local NJ businesses to sell an AI receptionist product built with FastAPI, "
                "Twilio, GPT-4, RAG, Redis, and PostgreSQL. Landed two paying clients: "
                "Innovation Development Solutions (national consulting firm) and Pro Body For Life (fitness brand). "
                "Designed and deployed Next.js websites to Vercel for both. "
                "AI Receptionist has active waitlist demand — held back only by infrastructure scaling costs."
            ),
        },
    ],
    "projects": [
        {
            "name": "Agentop — Multi-Agent AI Platform",
            "url": "https://github.com/as4584",
            "description": (
                "Production-grade local multi-agent platform: 11 AI agents, 47 tools (13 native + 26 MCP + 8 browser), "
                "custom 3B LLM router achieving 94.9% routing accuracy — beats all 7B models by 33+ points. "
                "3-tier routing: C pre-filter (<0.01ms) → lex-v2 LLM → Python fallback. "
                "Stack: FastAPI, LangGraph, Ollama, Next.js, SQLite, Kubernetes, Doppler."
            ),
        },
        {
            "name": "TurboQuant — 54.6x Embedding Compression (Rust)",
            "url": "https://github.com/as4584",
            "description": (
                "Implemented arXiv:2504.19874 in Rust with PyO3 Python bindings. "
                "Random rotation + scalar quantization achieves 54.6x speedup vs Python baseline and 8x compression. "
                "Used in Agentop's knowledge vector store."
            ),
        },
        {
            "name": "AI Receptionist — Production SaaS",
            "url": "https://github.com/as4584",
            "description": (
                "Fully deployed AI phone receptionist: FastAPI + Twilio + GPT-4 + RAG + Redis + PostgreSQL. "
                "Deployed on DigitalOcean with Caddy reverse proxy. "
                "Active demand from NJ businesses, waitlist ready to subscribe."
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

MODAL_SEL = "dialog, [role='dialog'], [data-testid*='modal'], [class*='Modal'], [class*='modal']"


async def _fill_if_visible(page, selector: str, value: str, timeout: int = 3000) -> bool:
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.fill(value)
        return True
    except Exception:
        return False


async def _click_if_visible(page, selector: str, timeout: int = 4000) -> bool:
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.click()
        return True
    except Exception:
        return False


async def _wait_for_modal(page, timeout: int = 8000):
    """Wait for any modal/dialog to appear and return its locator."""
    try:
        modal = page.locator(MODAL_SEL).first
        await modal.wait_for(state="visible", timeout=timeout)
        return modal
    except Exception:
        return None


async def _close_modal(page) -> None:
    """Close any open modal via Save button.

    Handshake hides the Save button (display:none / zero bounding box) when
    the form is PRISTINE.  After we clear-then-fill all fields the form becomes
    dirty and Handshake animates the Save button into view.
    We iterate every matching button (using .nth) so we don't miss a
    portal-rendered or last-in-DOM copy.
    """
    for sel in [
        # Try ACTIVE-DIALOG-scoped Save first — avoids clicking a Save from a hidden modal
        "[role='dialog'][data-enter] button:has-text('Save')",
        "button:has-text('Save')",
        "[role='dialog'] button:has-text('Save')",
        "button[type='submit']",
    ]:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            print(f"  [close] {sel}: count={count}", flush=True)
            # Try each match from last to first — the last one tends to be the
            # actual footer Save button, not a hidden accessibility copy.
            for i in range(count - 1, -1, -1):
                btn = loc.nth(i)
                vis = await btn.is_visible()
                ena = await btn.is_enabled()
                print(f"  [close]   nth({i}) vis={vis} ena={ena}", flush=True)
                if vis and ena:
                    await btn.click(timeout=8000)
                    await page.wait_for_timeout(3000)  # wait for API save
                    # Use [data-enter] to check only ACTIVE dialogs.
                    # Handshake pre-renders 6-7 hidden [role='dialog'] elements;
                    # using plain [role='dialog'] causes strict mode violations.
                    still_open = await page.locator("[role='dialog'][data-enter]").count() > 0
                    print(f"  [close] modal still open after click: {still_open}", flush=True)
                    if not still_open:
                        await page.wait_for_timeout(500)
                        return
        except Exception as e:
            print(f"  [close] error with {sel}: {e}", flush=True)
    # Fallback: Escape
    print("  [close] fallback Escape", flush=True)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(1000)


async def _goto_profile(page) -> None:
    """Navigate (back) to profile page — guarantees clean state after a modal."""
    await page.goto("https://app.joinhandshake.com/profiles/xgb9rw",
                    wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)


async def _dump_modal_fields(page) -> list[dict]:
    """Dump all input/textarea fields inside the open modal for debugging."""
    try:
        return await page.eval_on_selector_all(
            "[role='dialog'] input, [role='dialog'] textarea, [role='dialog'] select",
            "els => els.map(e => ({tag: e.tagName.toLowerCase(), name: e.name||'', "
            "id: e.id||'', placeholder: e.placeholder||'', type: e.type||'', "
            "ariaLabel: e.getAttribute('aria-label')||'', value: e.value||''}))",
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Section updaters — all use inline modals on /profiles/xgb9rw
# ---------------------------------------------------------------------------

async def _update_overview(page) -> None:
    """Click main 'Edit' button, fill bio modal."""
    print("\n→ Overview (bio/headline)", flush=True)
    # Click the main "Edit" button (aria-label="Edit Profile")
    edit_btn = page.locator("button[aria-label='Edit Profile']").first
    try:
        await edit_btn.wait_for(state="visible", timeout=6000)
        await edit_btn.click()
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  ✗ couldn't open edit modal: {e}", flush=True)
        return

    fields = await _dump_modal_fields(page)
    print(f"  Modal fields: {fields}", flush=True)
    await page.screenshot(path="output/handshake_screenshots/modal_overview.png")

    # Headline — name='headline' confirmed from DOM dump.
    # IMPORTANT: clear the field FIRST so React fires onChange even if the
    # value is already correct.  Handshake hides the Save button for pristine
    # forms, so we must make the form dirty before trying to save.
    filled = False
    for sel in ["input[name='headline']", "input[name*='headline' i]",
                "input[placeholder*='headline' i]", "input[placeholder*='tagline' i]",
                "input[aria-label*='headline' i]", "input[name*='tagline' i]"]:
        try:
            inp = page.locator(sel).first
            await inp.wait_for(state="visible", timeout=2000)
            await inp.fill("")  # clear → form becomes dirty
            await page.wait_for_timeout(100)
            await inp.fill(PROFILE["headline"])
            print(f"  headline filled ({sel})", flush=True)
            filled = True
            break
        except Exception:
            pass
    if not filled:
        print("  ⚠ headline field not found", flush=True)

    # Wait for React to process the onChange → this re-enables the Save button
    await page.wait_for_timeout(800)
    await page.screenshot(path="output/handshake_screenshots/modal_overview_after_fill.png")
    print("  screenshot: modal_overview_after_fill.png", flush=True)

    await _close_modal(page)
    await _goto_profile(page)  # clean reload ensures modal is gone


async def _update_about(page) -> None:
    """Click + next to About section and fill in the bio."""
    print("\n→ About (bio)", flush=True)
    # Use the exact data-hook from the DOM dump — this is the "Add summary" button
    clicked = False
    for sel in [
        "button[data-hook='profile-section-SUMMARY-add']",
        "button[aria-label='Add summary']",
        "button[aria-label*='summary' i]",
        "button[aria-label*='Add about' i]",
        "button[aria-label*='Edit about' i]",
    ]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=2000):
                await el.click()
                await page.wait_for_timeout(1500)
                clicked = True
                print(f"  opened via {sel}", flush=True)
                break
        except Exception:
            pass

    if not clicked:
        # Wider fallback: find button near the About heading (not the main Edit Profile button)
        result = await page.evaluate("""
            () => {
                const selectors = [
                    'button[aria-label="Add summary"]',
                    'button[name*="SUMMARY"]',
                    '[data-hook*="SUMMARY"] button',
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el) { el.click(); return s; }
                }
                return null;
            }
        """)
        if result:
            await page.wait_for_timeout(1500)
            clicked = True
            print(f"  opened via JS ({result})", flush=True)

    if not clicked:
        print("  ✗ About + button not found", flush=True)
        return

    # Debug: dump ALL textareas to find the bio field location
    all_ta = await page.eval_on_selector_all(
        "textarea",
        "els => els.map(e => ({name: e.name, id: e.id, placeholder: e.placeholder, "
        "inDialog: !!e.closest('[role=dialog]')}))",
    )
    print(f"  All textareas: {all_ta}", flush=True)
    fields = await _dump_modal_fields(page)
    print(f"  Modal fields: {fields}", flush=True)
    await page.screenshot(path="output/handshake_screenshots/modal_about.png")

    filled = False
    # Try inside dialog first, then anywhere on page
    for sel in [
        "[role='dialog'] textarea",
        "[data-hook='section-editor-modal-EDITOR'] textarea",
        "textarea[name*='bio' i]", "textarea[name*='about' i]", "textarea[name*='summary' i]",
        "textarea[placeholder*='about' i]", "textarea[placeholder*='bio' i]",
        "textarea[placeholder*='describe' i]",
        "[contenteditable='true']",
    ]:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=2000)
            await el.fill("")  # clear first → form becomes dirty
            await page.wait_for_timeout(100)
            await el.fill(PROFILE["bio"])
            print(f"  bio filled ({sel})", flush=True)
            filled = True
            break
        except Exception:
            pass
    if not filled:
        print("  ⚠ bio field not found", flush=True)

    await page.wait_for_timeout(500)
    await page.screenshot(path="output/handshake_screenshots/modal_about_after_fill.png")
    print("  screenshot: modal_about_after_fill.png", flush=True)
    await _close_modal(page)
    await _goto_profile(page)


async def _add_link(page, url_value: str, link_type: str, link_label: str) -> None:
    """Add a link via the Edit Profile modal (links section).

    After the first link is saved, there is NO standalone 'Add a link' button
    on the profile page — links live inside the main Edit Profile modal.
    We open Edit Profile, fill name + URL, and save.
    """
    print(f"\n→ Add link: {link_type}", flush=True)

    # Open modal — standalone button before any links, then data-hook DIV after
    opened = False
    for btn_sel in [
        "[data-hook='external-link-add-header']",
        "button:has-text('Add a link')",
        "button[aria-label='Edit Profile']",
        "button[data-hook='profile-main-info-edit']",
    ]:
        try:
            el = page.locator(btn_sel).first
            if await el.count() > 0 and await el.is_visible(timeout=2000):
                await el.click()
                await page.wait_for_timeout(1500)
                if await page.locator("[role='dialog'][data-enter]").count() > 0:
                    opened = True
                    print(f"  modal opened via {btn_sel}", flush=True)
                    break
        except Exception:
            pass

    if not opened:
        print(f"  ✗ couldn't open profile edit modal for {link_type}", flush=True)
        return

    # If modal has no link-name input, click 'Add a link' inside the modal
    if await page.locator("input[name='name']").count() == 0:
        for inner_sel in [
            "[role='dialog'] button:has-text('Add a link')",
            "[data-enter] button:has-text('Add a link')",
        ]:
            try:
                el = page.locator(inner_sel).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    await el.click()
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                pass

    fields = await _dump_modal_fields(page)
    print(f"  Modal fields (count={len(fields)})", flush=True)
    await page.screenshot(path=f"output/handshake_screenshots/modal_link_{link_type}.png")

    # Fill the REQUIRED link name (e.g., "Personal Website", "GitHub", "LinkedIn")
    for sel in ["input[name='name']", "input[placeholder*='LinkedIn, GitHub' i]",
                "input[placeholder*='link name' i]", "input[aria-label*='link name' i]"]:
        try:
            inp = page.locator(sel).first
            await inp.wait_for(state="visible", timeout=2000)
            await inp.fill("")
            await page.wait_for_timeout(100)
            await inp.fill(link_label)
            print(f"  name filled ({sel})", flush=True)
            break
        except Exception:
            pass

    # Fill URL field — clear first to make the form dirty
    filled = False
    for sel in ["input[name='externalUrl']", "input[type='url']",
                "input[placeholder*='url' i]", "input[placeholder*='http' i]",
                "input[aria-label*='url' i]", "input[name*='url' i]"]:
        try:
            inp = page.locator(sel).first
            await inp.wait_for(state="visible", timeout=2000)
            await inp.fill("")
            await page.wait_for_timeout(100)
            await inp.fill(url_value)
            print(f"  url filled ({sel})", flush=True)
            filled = True
            break
        except Exception:
            pass
    if not filled:
        print(f"  ⚠ url input not found for {link_type}", flush=True)

    await _close_modal(page)
    await _goto_profile(page)


async def _update_links(page) -> None:
    """Add website, GitHub, LinkedIn links."""
    for url_val, label, label_str in [
        (PROFILE["website"], "website", "Personal Website"),
        (PROFILE["github"], "github", "GitHub"),
        (PROFILE["linkedin"], "linkedin", "LinkedIn"),
    ]:
        await _add_link(page, url_val, label, label_str)
        await page.wait_for_timeout(500)


async def _update_skills(page) -> None:
    """Click Skills pencil icon, add skills one by one."""
    print("\n→ Skills", flush=True)
    # Data-hook is 'profile-section-SKILL-add' (or aria-label='Edit skills')
    skills_btn = None
    for sel in [
        "button[data-hook='profile-section-SKILL-add']",
        "button[aria-label='Edit skills']",
        "button[data-hook='profile-section-SKILLS-add']",
    ]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=3000):
                skills_btn = el
                break
        except Exception:
            pass
    if not skills_btn:
        print("  ✗ skills button not found", flush=True)
        return
    try:
        await skills_btn.click()
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  ✗ couldn't open skills modal: {e}", flush=True)
        return

    fields = await _dump_modal_fields(page)
    print(f"  Modal fields: {fields}", flush=True)
    await page.screenshot(path="output/handshake_screenshots/modal_skills.png")

    # First clear any wrongly added skills by clicking their remove (×) buttons
    removed = 0
    while True:
        try:
            remove_btns = page.locator(
                "[role='dialog'] button[aria-label*='Remove' i], "
                "[role='dialog'] button[aria-label*='Delete' i], "
                "[role='dialog'] [data-hook*='remove' i] button"
            )
            cnt = await remove_btns.count()
            if cnt == 0:
                break
            await remove_btns.first.click()
            await page.wait_for_timeout(300)
            removed += 1
        except Exception:
            break
    if removed:
        print(f"  cleared {removed} existing skills", flush=True)

    # Find the skill input
    skill_input = None
    for sel in ["input#profile-skills", "input[id='profile-skills']",
                "input[placeholder*='skill' i]", "input[aria-label*='skill' i]",
                "input[placeholder*='Search' i]", "[role='dialog'] input[type='search']",
                "dialog input[type='text']", "[role='dialog'] input[type='text']"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                skill_input = sel
                break
        except Exception:
            pass

    if skill_input is None:
        print("  ⚠ skill input not found", flush=True)
        await _close_modal(page)
        return

    for skill in PROFILE["skills"]:
        try:
            inp = page.locator(skill_input).first
            await inp.wait_for(state="visible", timeout=3000)
            await inp.fill(skill)
            await page.wait_for_timeout(700)
            # Pick from dropdown
            picked = False
            for opt_sel in [f"[role='option']:has-text('{skill}')",
                            f"li:has-text('{skill}')",
                            "[role='option']:first-child",
                            "li:first-child"]:
                try:
                    opt = page.locator(opt_sel).first
                    if await opt.is_visible(timeout=1200):
                        await opt.click()
                        picked = True
                        break
                except Exception:
                    pass
            if not picked:
                await page.keyboard.press("Enter")
            print(f"  + {skill}", flush=True)
            await page.wait_for_timeout(300)
        except Exception as e:
            print(f"  ✗ {skill}: {e}", flush=True)

    await _close_modal(page)
    await _goto_profile(page)


async def _update_experience(page) -> None:
    """Click + next to Work experience, fill the modal."""
    print("\n→ Work experience", flush=True)

    # Try data-hook first (exact selector from Playwright traceback), then aria-label variants
    clicked = False
    for sel in [
        "button[data-hook='profile-section-WORKEXPERIENCE-add']",
        "button[aria-label='Add work experience']",
        "section:has-text('Work experience') button[aria-label*='Add' i]",
        "button[aria-label*='Add work' i]",
        "button[aria-label*='Add experience' i]",
    ]:
        try:
            el = page.locator(sel).first
            count = await page.locator(sel).count()
            if count == 0:
                continue
            # Scroll into view so it can become interactive
            await el.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(800)
            vis = await el.is_visible()
            enabled = await el.is_enabled()
            print(f"  [exp] {sel}: vis={vis} enabled={enabled}", flush=True)
            if vis:
                if enabled:
                    await el.click(timeout=8000)
                else:
                    # HTML `disabled` attribute — use JS click which bypasses it
                    print("  [exp] button disabled → JS click fallback", flush=True)
                    await page.evaluate(
                        "sel => document.querySelector(sel)?.click()",
                        sel,
                    )
                await page.wait_for_timeout(1500)
                clicked = True
                break
        except Exception as e:
            print(f"  [exp] {sel}: {e}", flush=True)

    if not clicked:
        # Last-resort: click any + button near "Work experience" text via JS
        result = await page.evaluate("""
            () => {
                const headings = [...document.querySelectorAll('h2, h3, [role="heading"]')];
                const h = headings.find(x => /work experience/i.test(x.textContent));
                if (!h) return 'no-heading';
                const section = h.closest('section') || h.parentElement?.parentElement;
                const btn = section?.querySelector('button');
                if (btn) { btn.click(); return 'clicked'; }
                return 'no-button';
            }
        """)
        print(f"  [exp] JS fallback result: {result}", flush=True)
        if result == "clicked":
            await page.wait_for_timeout(1500)
            clicked = True

    if not clicked:
        print("  ✗ couldn't open Work experience modal", flush=True)
        return

    fields = await _dump_modal_fields(page)
    print(f"  Modal fields: {fields}", flush=True)
    await page.screenshot(path="output/handshake_screenshots/modal_experience.png")

    exp = PROFILE["experience"][0]

    # Title
    for sel in ["input[placeholder*='title' i]", "input[aria-label*='title' i]",
                "input[name*='title' i]", "input[placeholder*='position' i]",
                "input[placeholder*='role' i]"]:
        if await _fill_if_visible(page, sel, exp["title"], 2000):
            print(f"  title filled", flush=True)
            break

    # Employer / company
    for sel in ["input[placeholder*='employer' i]", "input[placeholder*='company' i]",
                "input[aria-label*='employer' i]", "input[name*='employer' i]",
                "input[name*='company' i]", "input[placeholder*='organization' i]"]:
        if await _fill_if_visible(page, sel, exp["org"], 2000):
            await page.wait_for_timeout(600)
            await page.keyboard.press("Escape")  # dismiss autocomplete
            print(f"  employer filled", flush=True)
            break

    # Description
    for sel in ["textarea[placeholder*='description' i]", "textarea[aria-label*='description' i]",
                "textarea[name*='description' i]", "dialog textarea", "[role='dialog'] textarea"]:
        if await _fill_if_visible(page, sel, exp["description"], 2000):
            print(f"  description filled", flush=True)
            break

    await _close_modal(page)
    await _goto_profile(page)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run():
    from playwright.async_api import async_playwright

    PROFILE_DIR = Path("data/handshake_profile")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_URL = "https://app.joinhandshake.com/profiles/xgb9rw"
    OUT = Path("output/handshake_screenshots")
    OUT.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR.resolve()),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        print(f"Going to {PROFILE_URL}", flush=True)
        await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if "login" in page.url or "sign_in" in page.url:
            print("\nNot logged in. Log in then press ENTER.")
            input("> ")
            await page.wait_for_timeout(1000)

        print(f"Loaded: {page.url}", flush=True)
        await page.screenshot(path=str(OUT / "profile_before.png"))
        print("Screenshot: profile_before.png", flush=True)

        await _update_overview(page)
        await _update_about(page)
        await _update_links(page)
        await _update_skills(page)
        await _update_experience(page)

        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "profile_after.png"))
        print("\n✓ Profile update complete — profile_after.png", flush=True)
        print(f"  View: {PROFILE_URL}", flush=True)

        await page.wait_for_timeout(2000)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(run())
