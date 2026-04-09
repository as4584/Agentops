"""
Handshake Job Application Automation
Lex Santiago — NJIT Information Systems, Graduating May 2028

Launches a persistent Chromium browser (user signs in once, stays signed in).
For each job on Handshake:
  1. Reads the job description
  2. Tailors the cover letter via Ollama
  3. Fills the application form (GPA: 2.2 if required, blank if optional)
  4. Uploads a resume PDF
  5. Screenshots the confirmation
  6. Logs to SQLite via track_application()

Usage:
    python scripts/handshake_apply.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.utils import logger

# ---------------------------------------------------------------------------
# Candidate constants
# ---------------------------------------------------------------------------

CANDIDATE = {
    "name": "Alexander Santiago",
    "email": "as42519256@gmail.com",
    "phone": "",  # fill in if Handshake asks
    "school": "New Jersey Institute of Technology",
    "major": "Information Systems",
    "gpa": "2.2",
    "grad_month": "May",
    "grad_year": "2028",
    "linkedin": "linkedin.com/in/lexmakesit",
    "github": "github.com/as4584",
    "portfolio": "lexmakesit.com",
    "location": "Paterson, NJ",
}

RESUMES_DIR = Path("/mnt/c/Users/AlexS/Downloads")
PROFILE_DIR = Path("data/handshake_profile")  # persistent login state
SCREENSHOTS_DIR = Path("output/handshake_screenshots")
RESUME_PDF_DIR = Path("data/handshake_resumes")  # converted PDFs cached here

# Default resume for unknown companies
DEFAULT_RESUME = "Alexander_Santiago_Resume_Updated.docx"

# Company → tailored resume mapping
COMPANY_RESUME_MAP: dict[str, str] = {
    "epic": "Alexander_Santiago_Epic.docx",
    "earthcam": "Alexander_Santiago_EarthCam.docx",
    "fdm": "Alexander_Santiago_FDM.docx",
    "camares": "Alexander_Santiago_Camares.docx",
    "bel": "Alexander_Santiago_BEL.docx",
    "brand experience": "Alexander_Santiago_BEL.docx",
    "uci": "Alexander_Santiago_UCI.docx",
    "unique comp": "Alexander_Santiago_UCI.docx",
}

HANDSHAKE_JOBS_URL = "https://app.joinhandshake.com/job-search?page=1&per_page=25"


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------


def _pick_resume_docx(company: str) -> Path:
    """Return the best tailored resume docx path for a given company name."""
    company_lower = company.lower()
    for key, fname in COMPANY_RESUME_MAP.items():
        if key in company_lower:
            return RESUMES_DIR / fname
    return RESUMES_DIR / DEFAULT_RESUME


def _ensure_pdf(docx_path: Path) -> Path:
    """
    Return a local copy of the resume docx (Handshake accepts .docx directly).
    LibreOffice conversion is skipped — too fragile in WSL.
    """
    RESUME_PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUME_PDF_DIR / docx_path.name
    if not dest.exists():
        shutil.copy2(docx_path, dest)
        logger.info(f"[Handshake] Copied resume: {dest.name}")
    return dest


# ---------------------------------------------------------------------------
# LLM cover letter tailoring (Ollama)
# ---------------------------------------------------------------------------


def _tailor_cover_letter(company: str, role: str, jd_text: str, interactive: bool = False) -> str:
    """
    Generate a tailored cover letter.

    If interactive=True (recommended): prints the JD to the terminal so the user
    can paste it into Copilot chat and get a Sonnet-quality letter, then paste
    the result back. This is the preferred path — no API cost, full Sonnet quality.

    Falls back to the static template only if interactive=False and no LLM available.
    """
    if interactive:
        print("\n" + "=" * 60)
        print("COVER LETTER NEEDED")
        print(f"  Company : {company}")
        print(f"  Role    : {role}")
        print("=" * 60)
        print("Job description:")
        print("-" * 40)
        print(jd_text[:2000] if jd_text else "(no JD scraped — write a general letter)")
        print("-" * 40)
        print("\nAsk Copilot chat:")
        print(f'  "Write a cover letter for Lex Santiago applying to {company} for {role}. Use the JD above."')
        print("\nPaste the cover letter below.")
        print("When done, type a single '.' on a new line and press ENTER.\n")

        lines: list[str] = []
        while True:
            line = input()
            if line.strip() == ".":
                break
            lines.append(line)

        cover_letter = "\n".join(lines).strip()
        if cover_letter:
            return cover_letter
        logger.warning("[Handshake] No cover letter entered — using static fallback")

    # Static fallback
    from backend.skills.job_application.agent import generate_cover_letter

    keywords = [w for w in jd_text.lower().split() if len(w) > 5][:20]
    return generate_cover_letter(company, role, keywords)


# ---------------------------------------------------------------------------
# Form-filling helpers
# ---------------------------------------------------------------------------


async def _try_fill(page: Any, selector: str, value: str, timeout: int = 3000) -> bool:
    """Fill a field if it exists. Returns True on success."""
    try:
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.fill(value)
        return True
    except Exception:
        return False


async def _try_click(page: Any, selector: str, timeout: int = 5000) -> bool:
    """Click an element if it exists. Returns True on success."""
    try:
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.click()
        return True
    except Exception:
        return False


async def _fill_gpa_field(page: Any) -> None:
    """
    Fill GPA if the field is required (aria-required=true or has * label).
    Leave blank if optional.
    """
    # Selectors Handshake uses for GPA fields
    gpa_selectors = [
        "input[name*='gpa' i]",
        "input[placeholder*='gpa' i]",
        "input[aria-label*='gpa' i]",
        "input[id*='gpa' i]",
    ]
    for sel in gpa_selectors:
        try:
            field = page.locator(sel).first
            await field.wait_for(state="visible", timeout=2000)
            # Check if required
            required = await field.get_attribute("aria-required") or ""
            required_class = await field.get_attribute("required") or ""
            # Look for * in nearby label text
            label_text = ""
            try:
                field_id = await field.get_attribute("id") or ""
                if field_id:
                    label = page.locator(f"label[for='{field_id}']")
                    label_text = await label.text_content() or ""
            except Exception:
                pass

            is_required = (
                required.lower() == "true"
                or required_class == ""  # boolean required attr present
                or "*" in label_text
            )
            if is_required:
                await field.fill(CANDIDATE["gpa"])
                logger.info(f"[Handshake] GPA field (required) → {CANDIDATE['gpa']}")
            else:
                logger.info("[Handshake] GPA field (optional) → left blank")
            return
        except Exception:
            continue


async def _fill_standard_fields(page: Any) -> None:
    """Fill commonly known Handshake form fields."""
    fields = {
        "input[name*='grad' i][name*='year' i]": CANDIDATE["grad_year"],
        "input[placeholder*='graduation year' i]": CANDIDATE["grad_year"],
        "select[name*='grad' i][name*='year' i]": CANDIDATE["grad_year"],
        "input[name*='major' i]": CANDIDATE["major"],
        "input[placeholder*='major' i]": CANDIDATE["major"],
        "input[name*='phone' i]": CANDIDATE["phone"],
        "input[type='tel']": CANDIDATE["phone"],
        "input[name*='linkedin' i]": CANDIDATE["linkedin"],
        "input[placeholder*='linkedin' i]": CANDIDATE["linkedin"],
        "input[name*='github' i]": CANDIDATE["github"],
        "input[name*='portfolio' i]": CANDIDATE["portfolio"],
        "input[name*='website' i]": CANDIDATE["portfolio"],
    }
    for selector, value in fields.items():
        if value:  # skip empty phone, etc.
            await _try_fill(page, selector, value, timeout=1500)

    await _fill_gpa_field(page)


# ---------------------------------------------------------------------------
# Core application flow
# ---------------------------------------------------------------------------


async def _apply_to_job(
    page: Any,
    job_url: str,
    company: str,
    role: str,
    dry_run: bool = False,
    interactive: bool = False,
) -> dict[str, Any]:
    """
    Apply to a single job by clicking its card in the Handshake split-pane view.
    The page MUST already be on /job-search — we click cards, never navigate away.
    Returns a result dict with status and screenshot path.
    """
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "company": company,
        "role": role,
        "url": job_url,
        "status": "skipped",
        "screenshot": None,
        "cover_letter_used": False,
        "resume_used": None,
    }

    logger.info(f"[Handshake] → {company} | {role}")

    try:
        # Navigate directly — no card-click, no split-pane dependency
        await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)

        # Wait for the Apply button OR the upload modal to appear
        # (Handshake sometimes shows the apply modal pre-opened on direct URL load)
        modal_already_open = False
        try:
            await page.wait_for_selector(
                "button:has-text('Apply'), button:has-text('Upload new'), button:has-text('Submit Application')",
                timeout=10000,
            )
            # Check if modal is already open (Upload new or Submit visible)
            for modal_indicator in ["button:has-text('Upload new')", "button:has-text('Submit Application')"]:
                try:
                    await page.locator(modal_indicator).first.wait_for(state="visible", timeout=1000)
                    modal_already_open = True
                    logger.info(f"[Handshake] Apply modal already open ({modal_indicator})")
                    break
                except Exception:
                    pass
        except Exception:
            pass

        # --- CLICK APPLY BUTTON (only if modal not already open) ---
        apply_clicked = modal_already_open
        if not modal_already_open:
            for btn_sel in [
                "button:has-text('Easy Apply')",
                "button:has-text('Apply Now')",
                "button:has-text('Apply')",
                "[data-hook='apply-button']",
            ]:
                if await _try_click(page, btn_sel, timeout=6000):
                    apply_clicked = True
                    logger.info(f"[Handshake] Clicked apply button via: {btn_sel}")
                    break

        if not apply_clicked:
            result["status"] = "no_apply_button"
            logger.warning(f"[Handshake] No apply button found for: {job_url}")
            return result

        # Scrape job description (best-effort, after we know we're applying)
        jd_text = ""
        for jd_sel in ["[data-hook='job-description']", ".job-description", "main"]:
            try:
                el = page.locator(jd_sel).first
                jd_text = await el.text_content() or ""
                if len(jd_text) > 100:
                    break
            except Exception:
                continue

        # Wait for apply modal to fully open
        await page.wait_for_timeout(1000)

        if dry_run:
            result["status"] = "dry_run"
            safe = re.sub(r"[^\w]", "_", company)[:30]
            ss = SCREENSHOTS_DIR / f"{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_dryrun.png"
            await page.screenshot(path=str(ss))
            result["screenshot"] = str(ss)
            logger.info(f"[Handshake] Dry run screenshot: {ss.name}")
            # Close modal
            for close_sel in ["button[aria-label='Close']", "button[aria-label='close']", "button:has-text('Cancel')"]:
                if await _try_click(page, close_sel, timeout=1500):
                    break
            return result

        # --- RESUME UPLOAD ---
        resume_docx = _pick_resume_docx(company)
        resume_file = _ensure_pdf(resume_docx)
        result["resume_used"] = resume_file.name
        resume_uploaded = False

        # Strategy 1: hidden file input (most reliable across all modal types)
        for upload_sel in [
            "input[type='file'][accept*='pdf' i]",
            "input[type='file'][accept*='.doc' i]",
            "input[type='file']",
        ]:
            try:
                el = page.locator(upload_sel).first
                await el.wait_for(state="attached", timeout=3000)
                await el.set_input_files(str(resume_file))
                resume_uploaded = True
                logger.info(f"[Handshake] ✓ Resume via hidden input: {resume_file.name}")
                break
            except Exception:
                continue

        # Strategy 2: file chooser via "Upload new" button (fallback)
        if not resume_uploaded:
            try:
                async with page.expect_file_chooser(timeout=4000) as fc_info:
                    await _try_click(page, "button:has-text('Upload new')", timeout=3000)
                file_chooser = await fc_info.value
                await file_chooser.set_files(str(resume_file))
                resume_uploaded = True
                logger.info(f"[Handshake] ✓ Resume via file chooser: {resume_file.name}")
            except Exception as fc_err:
                logger.warning(f"[Handshake] Resume upload failed: {type(fc_err).__name__} — submitting anyway")

        await page.wait_for_timeout(800)

        # --- COVER LETTER (only if field exists) ---
        for cl_sel in [
            "textarea[name*='cover' i]",
            "textarea[placeholder*='cover letter' i]",
            "textarea[aria-label*='cover letter' i]",
        ]:
            try:
                cl_field = page.locator(cl_sel).first
                await cl_field.wait_for(state="visible", timeout=1000)
                cover_letter = _tailor_cover_letter(company, role, jd_text, interactive=interactive)
                await cl_field.fill(cover_letter)
                result["cover_letter_used"] = True
                logger.info("[Handshake] Cover letter auto-filled")
                break
            except Exception:
                continue

        # --- STANDARD FIELDS ---
        await _fill_standard_fields(page)
        await page.wait_for_timeout(500)

        # --- SUBMIT ---
        submitted = False
        for submit_sel in [
            "button:has-text('Submit Application')",
            "button[type='submit']:has-text('Submit')",
            "button:has-text('Submit')",
        ]:
            if await _try_click(page, submit_sel, timeout=5000):
                submitted = True
                logger.info(f"[Handshake] ✓ Applied: {company} — {role}")
                break

        await page.wait_for_timeout(2500)

        # Screenshot confirmation
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company = re.sub(r"[^\w]", "_", company)[:30]
        ss_path = SCREENSHOTS_DIR / f"{safe_company}_{ts}.png"
        await page.screenshot(path=str(ss_path), full_page=False)
        result["screenshot"] = str(ss_path)
        result["status"] = "applied" if submitted else "form_filled_no_submit"

    except Exception as exc:
        logger.error(f"[Handshake] Error on {job_url}: {exc}")
        result["status"] = f"error: {type(exc).__name__}"

    return result


# ---------------------------------------------------------------------------
# Job discovery
# ---------------------------------------------------------------------------


async def _scrape_job_listings(page: Any, max_jobs: int = 200) -> list[dict[str, str]]:
    """
    Navigate Handshake's job listings and collect job URLs, company names, and roles.
    Returns list of dicts: {url, company, role}.

    Handles both the old /stu/jobs paginated view and the new /explore SPA view
    (infinite scroll, category tabs).
    """
    jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"[Handshake] Navigating to jobs board: {HANDSHAKE_JOBS_URL}")
    await page.goto(HANDSHAKE_JOBS_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)  # extra time for SPA to hydrate
    logger.info(f"[Handshake] Jobs page URL after load: {page.url}")

    # Debug screenshot — tells us exactly what the browser sees
    debug_ss = SCREENSHOTS_DIR / f"debug_jobs_page_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    await page.screenshot(path=str(debug_ss))
    logger.info(f"[Handshake] Debug screenshot saved: {debug_ss}")
    logger.info(f"[Handshake] Page title: {await page.title()}")

    # If redirected to /explore or not on the job-search page, navigate via the sidebar link
    if "/job-search" not in page.url and "/stu/jobs" not in page.url:
        logger.info("[Handshake] Not on jobs list — clicking sidebar Jobs link")
        for jobs_nav_sel in [
            "a[href='/stu/jobs']",
            "a[href^='/stu/jobs']:not([href*='/stu/jobs/'])",
            "nav a:has-text('Jobs')",
            "aside a:has-text('Jobs')",
            "a:text-is('Jobs')",
        ]:
            if await _try_click(page, jobs_nav_sel, timeout=3000):
                logger.info(f"[Handshake] Clicked Jobs nav via: {jobs_nav_sel}")
                await page.wait_for_timeout(3000)
                logger.info(f"[Handshake] URL after nav: {page.url}")
                # Save a debug screenshot of the actual jobs listing page
                debug_ss2 = SCREENSHOTS_DIR / f"debug_jobs_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(debug_ss2))
                logger.info(f"[Handshake] Jobs list screenshot: {debug_ss2}")
                break

    # Log current URL so we know where we landed
    logger.info(f"[Handshake] Landed on: {page.url}")

    # Ordered selector strategies — first match wins per round
    card_selectors = [
        "a[href*='/job-search/']",
        "a[href*='/stu/jobs/']",
        "a[href*='/jobs/']",
        "[data-hook*='job'] a[href]",
        "article a[href]",
        "li a[href*='job']",
    ]

    scroll_round = 0
    while len(jobs) < max_jobs:
        scroll_round += 1
        logger.info(f"[Handshake] Scraping round {scroll_round} ({len(jobs)} collected so far)")

        cards: list[Any] = []
        used_sel = ""
        for sel in card_selectors:
            found = await page.locator(sel).all()
            if found:
                cards = found
                used_sel = sel
                break

        if cards:
            logger.info(f"[Handshake] Selector '{used_sel}' matched {len(cards)} elements")

        page_found = 0
        for card in cards:
            try:
                href = await card.get_attribute("href") or ""
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://app.joinhandshake.com" + href
                if href in seen_urls:
                    continue
                # Accept /job-search/123, /stu/jobs/123, /jobs/123
                if not re.search(r"(?:job-search|jobs)/\d+", href):
                    continue

                seen_urls.add(href)

                # Get parent card container for better role/company extraction
                try:
                    card_text = (
                        await card.evaluate(
                            "el => (el.closest('li') || el.closest('article') || el.closest('[class*=card]') || el.parentElement || el).textContent"
                        )
                        or ""
                    )
                except Exception:
                    card_text = await card.text_content() or ""
                lines = [ln.strip() for ln in card_text.strip().splitlines() if ln.strip()]
                # Handshake card text order: role title, company name, salary/type, location
                # Filter out lines that look like metadata (contain $, ·, /hr, ago, New, Remote)
                clean = [
                    line
                    for line in lines
                    if not any(
                        x in line for x in ["$", "·", "/hr", " ago", "New", "Promoted", "Remote", "Onsite", "Hybrid"]
                    )
                ]
                role = clean[0] if clean else (lines[0] if lines else "Unknown Role")
                company = clean[1] if len(clean) > 1 else (lines[1] if len(lines) > 1 else "Unknown Company")

                jobs.append({"url": href, "company": company, "role": role})
                page_found += 1
            except Exception:
                continue

        if page_found == 0 and scroll_round > 1:
            logger.info("[Handshake] No new jobs found after scroll — stopping")
            break

        if len(jobs) >= max_jobs:
            break

        # Try infinite scroll first
        prev_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2500)
        new_height = await page.evaluate("document.body.scrollHeight")

        if new_height == prev_height:
            # No new content — try pagination buttons
            next_clicked = False
            for next_sel in [
                "button[aria-label='Next page']",
                "a[aria-label='Next page']",
                "[data-hook='next-page']",
                "button:has-text('Next')",
            ]:
                if await _try_click(page, next_sel, timeout=3000):
                    next_clicked = True
                    await page.wait_for_timeout(2000)
                    break

            if not next_clicked:
                logger.info("[Handshake] Page height unchanged and no next button — done scraping")
                break

    logger.info(f"[Handshake] Discovered {len(jobs)} jobs total")
    return jobs[:max_jobs]


# ---------------------------------------------------------------------------
# Login check
# ---------------------------------------------------------------------------


async def _ensure_logged_in(page: Any) -> bool:
    """
    Navigate to Handshake and check if already logged in.
    If not, prompt the user to log in manually in the visible browser and wait.
    Returns True when logged in.
    """
    await page.goto("https://app.joinhandshake.com/job-search", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    current_url = page.url
    is_logged_in = (
        "joinhandshake.com" in current_url
        and "login" not in current_url
        and "sign_in" not in current_url
        and "sessions" not in current_url
    )

    if is_logged_in:
        logger.info("[Handshake] Already logged in")
        return True

    logger.info(f"[Handshake] Not logged in — current URL: {current_url}")
    print("\n" + "=" * 60)
    print("HANDSHAKE LOGIN REQUIRED")
    print("=" * 60)
    print("A browser window should be open on your screen.")
    print("Please:")
    print("  1. Log in to Handshake (app.joinhandshake.com)")
    print("  2. Complete any 2FA")
    print("  3. Make sure you can see the Jobs page")
    print("  4. Come back here and press ENTER")
    print("=" * 60)
    input("Press ENTER when logged in > ")

    await page.wait_for_timeout(1000)
    # Verify login worked
    final_url = page.url
    if "login" in final_url or "sign_in" in final_url or "sessions" in final_url:
        print("WARNING: Still looks like the login page. Continuing anyway...")
    return True


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


async def run_handshake_campaign(
    limit: int = 50,
    dry_run: bool = False,
    headed: bool = True,
    interactive: bool = False,
) -> list[dict[str, Any]]:
    """
    Full Handshake application campaign.

    Args:
        limit:       Max number of jobs to apply to.
        dry_run:     If True, screenshot only — no form submission.
        headed:      If True, show the browser window (required before first login).
        interactive: If True, pause per job to paste a Copilot/Sonnet cover letter.
                     Default False — auto-generates cover letter (or skips if field absent).
    """
    from playwright.async_api import async_playwright

    from backend.skills.job_application.agent import track_application

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        # Persistent context = stays logged in between runs
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR.resolve()),
            headless=not headed,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )

        page = await context.new_page()

        # Stealth: hide the webdriver flag
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await _ensure_logged_in(page)

        jobs = await _scrape_job_listings(page, max_jobs=limit)

        for i, job in enumerate(jobs, start=1):
            logger.info(f"[Handshake] Applying {i}/{len(jobs)}: {job['company']} — {job['role']}")
            result = await _apply_to_job(
                page,
                job_url=job["url"],
                company=job["company"],
                role=job["role"],
                dry_run=dry_run,
                interactive=interactive,
            )
            results.append(result)

            # Log to SQLite
            track_application(
                company=job["company"],
                role=job["role"],
                url=job["url"],
                status=result["status"],
                resume_used=result.get("resume_used") or "",
                notes=f"screenshot: {result.get('screenshot') or 'none'}",
            )

            # Brief pause between applications — skip if browser was closed
            try:
                await page.wait_for_timeout(1000)
            except Exception:
                logger.info("[Handshake] Browser closed — stopping campaign")
                break

        await context.close()

    applied = sum(1 for r in results if r["status"] == "applied")
    logger.info(f"[Handshake] Campaign complete — {applied}/{len(results)} applied")
    return results
