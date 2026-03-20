"""
Seek Quick Apply autofill — human-like, anti-ban.

Anti-ban measures:
  - Random delays (1–4s) between every action
  - Human typing speed via type() with per-keystroke delay
  - Random mouse movements and scrolling before clicks
  - Persistent browser profile (cookies / session survive between runs)
  - Hard cap: warns if session exceeds MAX_APPLICATIONS_PER_SESSION

User still manually clicks Submit — system NEVER auto-submits.
"""
import asyncio
import random
import sys
import os
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

SEEK_LOGIN_URL = "https://www.seek.com.au/oauth/login"
_session_apply_count = 0


# ── Human-like helpers ──────────────────────────────────────────────────────────

async def _pause(min_s=0.8, max_s=2.5):
    """Random pause to mimic human hesitation."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def _human_type(page: Page, selector: str, text: str):
    """Type text with per-keystroke delay like a human."""
    try:
        el = await page.query_selector(selector)
        if el and await el.is_visible():
            await el.click()
            await _pause(0.2, 0.6)
            await el.type(text, delay=random.randint(40, 120))
            await _pause(0.3, 0.8)
            return True
    except Exception:
        pass
    return False


async def _human_click(page: Page, selector: str) -> bool:
    """Move mouse naturally then click."""
    try:
        el = await page.query_selector(selector)
        if el and await el.is_visible():
            box = await el.bounding_box()
            if box:
                # Move to a random point within the element
                x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
                y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)
                await page.mouse.move(x, y)
                await _pause(0.1, 0.4)
                await page.mouse.click(x, y)
                await _pause(0.5, 1.5)
                return True
    except Exception:
        pass
    return False


async def _scroll_naturally(page: Page):
    """Scroll down in a human-like pattern."""
    for _ in range(random.randint(1, 3)):
        await page.mouse.wheel(0, random.randint(150, 400))
        await asyncio.sleep(random.uniform(0.2, 0.6))


async def _try_fill(page: Page, selectors: list, value: str) -> bool:
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await _pause(0.2, 0.5)
                await el.fill("")
                await el.type(value, delay=random.randint(40, 100))
                await _pause(0.3, 0.7)
                return True
        except Exception:
            continue
    return False


async def _try_upload(page: Page, selectors: list, file_path: str) -> bool:
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.set_input_files(file_path)
                await _pause(1.5, 3.0)
                return True
        except Exception:
            continue
    return False


# ── Login ───────────────────────────────────────────────────────────────────────

async def _is_logged_in(page: Page) -> bool:
    try:
        await page.goto("https://www.seek.com.au", wait_until="domcontentloaded", timeout=20000)
        await _pause(1.5, 3.0)
        sign_in = await page.query_selector(
            '[data-automation="sign in"], [href*="/oauth/login"], button:has-text("Sign in")'
        )
        return sign_in is None
    except Exception:
        return False


async def _login(page: Page, log) -> bool:
    log("🔐  Logging in to Seek...")
    try:
        await page.goto(SEEK_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await _pause(2.0, 4.0)
        await _scroll_naturally(page)

        email_sel = 'input[name="email"], input[type="email"], #emailAddress'
        await page.wait_for_selector(email_sel, timeout=10000)
        await _human_type(page, email_sel, config.SEEK_EMAIL)

        # Two-step login: click Continue first
        for btn_sel in ['button:has-text("Continue")', 'button[type="submit"]']:
            btn = await page.query_selector(btn_sel)
            if btn and await btn.is_visible():
                await _human_click(page, btn_sel)
                await _pause(1.5, 3.0)
                break

        pwd_sel = 'input[name="password"], input[type="password"], #password'
        try:
            await page.wait_for_selector(pwd_sel, timeout=8000)
            await _human_type(page, pwd_sel, config.SEEK_PASSWORD)
        except Exception:
            log("⚠️  Password field not found — may already be on combined form.")

        await _pause(0.5, 1.0)
        for btn_sel in ['button[type="submit"]', 'button:has-text("Sign in")']:
            btn = await page.query_selector(btn_sel)
            if btn and await btn.is_visible():
                await _human_click(page, btn_sel)
                break

        await _pause(3.0, 5.0)

        if "seek.com.au" in page.url and "login" not in page.url:
            log("✅  Logged in.")
            return True
        else:
            log("⚠️  Login may have failed — please log in manually in the browser.")
            return False

    except Exception as e:
        log(f"❌  Login error: {e}")
        return False


# ── Cover letter generator ──────────────────────────────────────────────────────

def _build_cover_letter(job: dict, profile: dict) -> str:
    """Generate a professional cover letter from profile + job details."""
    name    = profile["personal"]["name"]
    title   = job.get("title", "this role")
    company = job.get("company", "your organisation")

    # Most recent role
    exp     = profile.get("experience", [{}])[0]
    recent_role    = exp.get("role", "Data Analyst Intern")
    recent_company = exp.get("company", "MCIE")

    # Education
    edu = profile.get("education", [{}])[0]
    degree = edu.get("degree", "Master of Business Analytics")
    uni    = edu.get("institution", "Deakin University")

    return f"""Dear Hiring Manager,

I am writing to express my strong interest in the {title} position at {company}. With a {degree} from {uni} and hands-on experience as a {recent_role} at {recent_company}, I am confident in my ability to contribute meaningfully to your team.

In my current role, I have designed and developed Power BI dashboards to monitor student data and KPIs, transformed and cleaned complex datasets (100+ tables) using SQL and Power Query, and built a multi-user data entry system using Python and Azure SQL Database. These experiences have given me a solid foundation in data analysis, reporting, and database management.

Previously at Ausbiz Consulting, I performed web scraping using Playwright and BeautifulSoup, conducted exploratory data analysis on job and candidate datasets, and contributed to building a RAG model pipeline. I also have experience delivering insights to non-technical stakeholders through clear visualisations and analytical reports.

I am proficient in Python, SQL, Power BI, Excel, and Azure, and I am passionate about using data to drive operational and strategic improvements. I am a fast learner who thrives in collaborative environments and takes ownership of my work.

I would welcome the opportunity to discuss how my skills align with your needs. Thank you for considering my application.

Yours sincerely,
{name}"""


# ── Form steps ──────────────────────────────────────────────────────────────────

async def _fill_personal(page: Page, profile: dict):
    personal  = profile["personal"]
    name_parts = personal["name"].split(" ", 1)
    first = name_parts[0]
    last  = name_parts[1] if len(name_parts) > 1 else ""

    await _try_fill(page,
        ['input[name="firstName"]', 'input[id*="first"]', 'input[placeholder*="First"]'], first)
    await _try_fill(page,
        ['input[name="lastName"]', 'input[id*="last"]', 'input[placeholder*="Last"]'], last)
    await _try_fill(page,
        ['input[name="email"]', 'input[type="email"]', 'input[id*="email"]'], personal["email"])
    await _try_fill(page,
        ['input[name="phone"]', 'input[type="tel"]', 'input[id*="phone"]',
         'input[placeholder*="Phone"]', 'input[placeholder*="phone"]'], personal["phone"])
    await _pause(0.5, 1.2)


async def _upload_resume(page: Page, resume_path: str) -> bool:
    # Try to click "Replace" / "Upload new" first
    for btn_text in ["Replace", "Upload new", "Change resume"]:
        btn = await page.query_selector(f'button:has-text("{btn_text}")')
        if btn and await btn.is_visible():
            await _human_click(page, f'button:has-text("{btn_text}")')
            await _pause(0.8, 1.5)
            break

    return await _try_upload(page, [
        'input[type="file"][accept*="pdf"]',
        'input[type="file"]',
        '[data-automation="resume-upload"] input',
        '[data-testid="resume-upload"] input',
    ], resume_path)


async def _fill_cover_letter(page: Page, text: str) -> bool:
    """Fill the cover letter textarea if present on this step."""
    for sel in [
        'textarea[name="coverLetter"]',
        'textarea[id*="cover"]',
        'textarea[placeholder*="cover"]',
        'textarea[aria-label*="cover" i]',
        '[data-automation="cover-letter"] textarea',
        '[data-testid="cover-letter"] textarea',
        'textarea',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await _pause(0.3, 0.6)
                await el.fill("")
                await el.type(text, delay=random.randint(20, 50))
                await _pause(0.5, 1.0)
                return True
        except Exception:
            continue
    return False


async def _answer_work_rights(page: Page):
    for sel in [
        'label:has-text("Yes")', 'input[value="Yes"]',
        'input[value="true"]', '[data-automation="work-rights-yes"]',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await _human_click(page, sel)
                return True
        except Exception:
            continue
    return False


async def _click_next(page: Page) -> bool:
    for sel in [
        'button:has-text("Next")', 'button:has-text("Continue")',
        'button[data-automation="next-btn"]',
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await _scroll_naturally(page)
                await _human_click(page, sel)
                await _pause(1.5, 3.0)
                return True
        except Exception:
            continue
    return False


async def _on_review_page(page: Page) -> bool:
    for sel in [
        'button:has-text("Submit")', 'button:has-text("Send application")',
        '[data-automation="review-step"]',
        'h2:has-text("Review")', 'h1:has-text("Review")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True
        except Exception:
            continue
    return False


# ── Main ────────────────────────────────────────────────────────────────────────

async def open_and_fill_application(job: dict, resume_pdf_path: str,
                                     cover_letter_text: str = "", profile: dict = None,
                                     on_progress=None) -> bool:
    """
    Opens a visible browser, logs in, navigates to the job, fills the
    Quick Apply form with human-like behaviour, then STOPS before Submit.

    The user reviews and clicks Submit manually.
    """
    global _session_apply_count

    def log(msg):
        print(msg)
        if on_progress:
            on_progress(msg)

    # Anti-ban: session limit warning
    _session_apply_count += 1
    if _session_apply_count > config.MAX_APPLICATIONS_PER_SESSION:
        log(f"⚠️  You have opened {_session_apply_count} applications this session.")
        log("    Consider taking a break to avoid triggering Seek's bot detection.")

    if not os.path.exists(resume_pdf_path):
        log(f"❌  Resume PDF not found: {resume_pdf_path}")
        return False

    async with async_playwright() as pw:
        browser_profile = str(Path(config.SEEK_SESSION_PATH).parent / "browser_profile")
        Path(browser_profile).mkdir(parents=True, exist_ok=True)

        context: BrowserContext = await pw.chromium.launch_persistent_context(
            user_data_dir=browser_profile,
            headless=False,
            args=["--start-maximized"],
            viewport=None,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # Login if needed
        logged_in = await _is_logged_in(page)
        if not logged_in:
            logged_in = await _login(page, log)
            if not logged_in:
                log("⚠️  Could not log in. Please log in manually — browser stays open.")
                await asyncio.sleep(90)
                await context.close()
                return False

        # Navigate to job page
        job_url = job.get("url", f"https://www.seek.com.au/job/{job.get('seek_id')}")
        log(f"\n🌐  Opening: {job.get('title')} @ {job.get('company')}")
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        await _pause(2.0, 4.0)
        await _scroll_naturally(page)
        await _pause(1.0, 2.0)

        # Click Apply / Quick Apply
        apply_selectors = [
            '[data-automation="job-detail-apply"]',
            'a[data-automation="job-detail-apply"]',
            'button:has-text("Quick apply")',
            'button:has-text("Apply")',
            'a:has-text("Quick apply")',
            'a:has-text("Apply now")',
        ]
        clicked = False
        for sel in apply_selectors:
            if await _human_click(page, sel):
                log("✅  Clicked Apply.")
                clicked = True
                break

        if not clicked:
            log("⚠️  Could not find Apply button — browser stays open for manual click.")
            return False

        await _pause(2.0, 4.0)

        # Detect external redirect
        if "seek.com.au" not in page.url:
            log(f"ℹ️  Redirected externally: {page.url}")
            log("    Please complete manually in the browser.")
            return False

        # Build cover letter once
        cover_text = cover_letter_text or _build_cover_letter(job, profile or {})
        log("📝  Filling application form...")

        # Multi-step form loop
        for step in range(8):
            await _pause(1.0, 2.0)
            await _scroll_naturally(page)

            await _fill_personal(page, profile)
            await _answer_work_rights(page)
            await _upload_resume(page, resume_pdf_path)
            await _fill_cover_letter(page, cover_text)

            if await _on_review_page(page):
                log("\n" + "=" * 55)
                log("🎯  FORM FILLED — PLEASE REVIEW IN BROWSER")
                log("    1. Check all details are correct.")
                log("    2. Click SUBMIT / SEND APPLICATION.")
                log("    3. Close the browser window to continue to next job.")
                log("=" * 55)

                # Wait for user to close the browser before moving to next job
                browser_closed = asyncio.Event()
                context.on("close", lambda: browser_closed.set())
                page.on("close", lambda: browser_closed.set())
                try:
                    await asyncio.wait_for(browser_closed.wait(), timeout=600)
                except asyncio.TimeoutError:
                    log("⏱️  10-min timeout — moving to next job.")
                return True

            advanced = await _click_next(page)
            if not advanced:
                log("    No Next button found — may be on final step.")
                break

        log("\n🎯  Form filling done. Close browser to continue to next job.")

        # Wait for browser close before returning
        browser_closed = asyncio.Event()
        context.on("close", lambda: browser_closed.set())
        try:
            await asyncio.wait_for(browser_closed.wait(), timeout=600)
        except asyncio.TimeoutError:
            pass
        return True
