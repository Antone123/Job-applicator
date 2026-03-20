"""
Seek job scraper — local keyword scoring only (no AI API calls).

Flow:
  1. Search Seek for target queries
  2. Filter: skip senior roles, over-salary, work-rights-required
  3. Score each job locally by keyword matching against Antone's skill set
  4. Jobs with score >= ATS_THRESHOLD → status "ready" (Apply button appears)
  5. Jobs below threshold → status "scored" (visible but no Apply button)
"""
import asyncio
import os
import random
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Page

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from backend.database import upsert_job, save_score, update_status, get_job

# ── Antone's full skill set for local matching ──────────────────────────────────

_OUR_SKILLS = {
    # Programming
    "python", "sql", "r", "web scraping", "beautifulsoup", "playwright",
    "selenium", "browser automation", "vba", "macros",
    # Visualization
    "power bi", "tableau", "excel", "pivot tables", "dashboard",
    "data visualization", "visualization", "reporting",
    # ML / Analytics
    "machine learning", "eda", "exploratory data analysis", "predictive analytics",
    "feature engineering", "supervised", "analytics", "insights", "kpi",
    "trend analysis", "data analysis",
    # Database / ETL
    "sql server", "azure sql", "azure", "data modelling", "data cleaning",
    "etl", "dashboard integration", "power query", "data quality",
    # Business
    "business analysis", "operational analytics", "process optimisation",
    "stakeholder communication", "stakeholder", "presentation",
    # Other tools
    "rag", "lms", "sharepoint", "data entry",
}

# All tech / role keywords to scan for in job descriptions
_SCAN_TERMS = [
    "python", "sql", "r", "power bi", "tableau", "excel", "azure", "aws",
    "machine learning", "eda", "etl", "data modelling", "data cleaning",
    "dashboard", "reporting", "analytics", "visualization", "stakeholder",
    "business analysis", "predictive", "feature engineering",
    "spark", "hadoop", "databricks", "snowflake", "dbt", "looker", "sas",
    "scala", "java", "javascript", "docker", "git", "jira", "sharepoint",
    "power query", "vba", "macros", "pivot", "selenium", "playwright",
    "web scraping", "automation", "data quality", "kpi", "insight",
    "sql server", "azure sql", "lms", "access", "communication",
    "data entry", "data analyst", "business analyst",
]


def _score_local(job_description: str) -> dict:
    """
    Score the job against Antone's skill set using local keyword matching.
    No API calls — instant and free.
    """
    desc = job_description.lower()

    # Find which scan terms appear in this job description
    job_wants = list({t for t in _SCAN_TERMS if t in desc})

    if not job_wants:
        return {
            "score": 55,
            "matched_keywords": ["analytics", "data", "reporting"],
            "missing_keywords": [],
            "requires_pr_citizen": _check_work_rights(desc),
            "reason": "General analyst role — moderate match based on profile.",
        }

    matched = [t for t in job_wants if t in _OUR_SKILLS]
    missing = [t for t in job_wants if t not in _OUR_SKILLS]

    score = int(len(matched) / len(job_wants) * 100)

    # Bonus for core skills (Python, SQL, Power BI)
    core_hits = sum(1 for k in ["python", "sql", "power bi"] if k in matched)
    score = min(100, score + core_hits * 3)

    return {
        "score": score,
        "matched_keywords": matched[:12],
        "missing_keywords": missing[:6],
        "requires_pr_citizen": _check_work_rights(desc),
        "reason": f"Matched {len(matched)} of {len(job_wants)} technical requirements.",
    }


# ── Filters ─────────────────────────────────────────────────────────────────────

def _is_senior_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in config.SENIOR_ROLE_KEYWORDS)


def _check_work_rights(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in config.WORK_RIGHTS_PHRASES)


def _parse_salary(s: str) -> dict:
    if not s:
        return {}
    s = s.lower().replace(",", "").replace("–", "-").replace("—", "-")
    is_daily = any(w in s for w in ["per day", "/day", "daily", "day rate"])
    nums = re.findall(r"\$?\s*(\d+(?:\.\d+)?)\s*(k)?", s)
    values = [float(n) * (1000 if k else 1) for n, k in nums if float(n) >= 150 or (is_daily and float(n) >= 100)]
    if not values:
        return {}
    lo, hi = min(values), max(values)
    if is_daily or hi < 2000:
        return {"daily_min": lo, "daily_max": hi}
    return {"annual_min": lo, "annual_max": hi}


def _is_over_salary(salary_str: str) -> bool:
    if not salary_str or salary_str.strip().lower() in ("", "competitive", "negotiable"):
        return False
    p = _parse_salary(salary_str)
    if not p:
        return False
    return (p.get("annual_min", 0) > config.MAX_SALARY_ANNUAL or
            p.get("daily_min", 0) > config.MAX_SALARY_DAILY)


# ── Seek helpers ─────────────────────────────────────────────────────────────────

def _build_search_url(query: str, page: int = 1) -> str:
    slug = query.strip().replace(" ", "-")
    url = f"https://www.seek.com.au/{slug}-jobs/in-Melbourne-VIC?dateRange=14"
    if page > 1:
        url += f"&page={page}"
    return url


async def _delay():
    await asyncio.sleep(random.uniform(config.SCRAPER_DELAY_MIN, config.SCRAPER_DELAY_MAX))


async def _human_scroll(page: Page):
    """Scroll down slightly to mimic human browsing."""
    await page.mouse.wheel(0, random.randint(200, 600))
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def _wait_for_jobs(page: Page) -> bool:
    for sel in [
        '[data-card-type="JobCard"]',
        'article[data-automation="normalJob"]',
        '[data-testid="job-card"]',
        'article',
    ]:
        try:
            await page.wait_for_selector(sel, timeout=10000)
            return True
        except Exception:
            continue
    return False


async def _extract_job_cards(page: Page) -> list:
    cards = []
    for sel in [
        '[data-card-type="JobCard"]',
        'article[data-automation="normalJob"]',
        '[data-testid="job-card"]',
    ]:
        cards = await page.query_selector_all(sel)
        if cards:
            break

    jobs = []
    for card in cards:
        try:
            link_el = await card.query_selector(
                'a[data-automation="jobTitle"], h3 a, [data-testid="job-title"] a, a[href*="/job/"]'
            )
            if not link_el:
                continue
            title = (await link_el.inner_text()).strip()
            href = await link_el.get_attribute("href") or ""
            if not href.startswith("http"):
                href = "https://www.seek.com.au" + href
            id_match = re.search(r"/job/(\d+)", href)
            if not id_match:
                continue
            seek_id = id_match.group(1)

            company_el = await card.query_selector(
                '[data-automation="jobCompany"], [data-testid="job-card-company-name"]'
            )
            company = (await company_el.inner_text()).strip() if company_el else "Unknown"

            loc_el = await card.query_selector(
                '[data-automation="jobLocation"], [data-testid="job-card-location"]'
            )
            location = (await loc_el.inner_text()).strip() if loc_el else "Melbourne VIC"

            sal_el = await card.query_selector(
                '[data-automation="jobSalary"], [data-testid="job-card-salary"]'
            )
            salary = (await sal_el.inner_text()).strip() if sal_el else ""

            type_el = await card.query_selector(
                '[data-automation="jobWorkType"], [data-testid="job-card-work-type"]'
            )
            employment_type = (await type_el.inner_text()).strip() if type_el else ""

            # Only include Quick Apply jobs
            quick_apply_el = await card.query_selector(
                '[data-automation="quick-apply"], [data-testid="quick-apply"], '
                'button:has-text("Quick apply"), a:has-text("Quick apply"), '
                '[aria-label*="Quick apply"], span:has-text("Quick apply")'
            )
            if not quick_apply_el:
                continue

            jobs.append({
                "seek_id": seek_id, "title": title, "company": company,
                "location": location, "salary": salary,
                "employment_type": employment_type,
                "url": f"https://www.seek.com.au/job/{seek_id}",
                "description": "",
            })
        except Exception:
            continue
    return jobs


async def _fetch_description(page: Page, url: str) -> str:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await _delay()
        await _human_scroll(page)
        for sel in [
            '[data-automation="jobAdDetails"]',
            '[data-testid="job-description"]',
            '#job-description',
        ]:
            el = await page.query_selector(sel)
            if el:
                return (await el.inner_text()).strip()
        body = await page.query_selector("main")
        if body:
            return (await body.inner_text()).strip()[:5000]
    except Exception as e:
        return f"[Description unavailable: {e}]"
    return ""


# ── Main entry ───────────────────────────────────────────────────────────────────

async def run_scrape(profile: dict, on_progress=None) -> dict:
    def log(msg: str):
        print(msg)
        if on_progress:
            on_progress(msg)

    stats = {"new_jobs": 0, "ready": 0, "skipped": 0}

    queries   = config.SEARCH_QUERIES[:1] if config.TEST_MODE else config.SEARCH_QUERIES
    max_pages = 1 if config.TEST_MODE else config.MAX_PAGES_PER_QUERY

    if config.TEST_MODE:
        log("🧪  TEST MODE — 1 query · 1 page · 1 job")

    async with async_playwright() as pw:
        browser_profile = str(Path(config.SEEK_SESSION_PATH).parent / "browser_profile")
        Path(browser_profile).mkdir(parents=True, exist_ok=True)

        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=browser_profile,
                headless=False,
                args=["--start-maximized"],
                viewport=None,
            )
        except Exception:
            browser  = await pw.chromium.launch(headless=False)
            context  = await browser.new_context()

        page = context.pages[0] if context.pages else await context.new_page()
        await page.set_extra_http_headers({"Accept-Language": "en-AU,en;q=0.9"})

        # ── Step 1: Scrape search results ────────────────────────────────────
        all_stubs = []
        for query in queries:
            for pg in range(1, max_pages + 1):
                url = _build_search_url(query, pg)
                log(f"🔍  Searching: '{query}' page {pg}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await _delay()
                    await _human_scroll(page)
                    if not await _wait_for_jobs(page):
                        log("    No job cards found on this page.")
                        break
                    cards = await _extract_job_cards(page)
                    log(f"    Found {len(cards)} listings.")
                    all_stubs.extend(cards)
                except Exception as e:
                    log(f"    ⚠️  Error: {e}")
                await _delay()

        # Deduplicate
        seen, unique = set(), []
        for j in all_stubs:
            if j["seek_id"] not in seen:
                seen.add(j["seek_id"])
                unique.append(j)
        log(f"\n📋  Unique listings: {len(unique)}")

        # ── Step 2: Filter + fetch description + score ───────────────────────
        to_score = []
        for i, job in enumerate(unique):
            if config.TEST_MODE and len(to_score) >= config.TEST_LIMIT:
                log(f"🧪  TEST MODE limit reached ({config.TEST_LIMIT})")
                break

            if _is_senior_role(job["title"]):
                log(f"    ⏭️  Senior — skip: {job['title']}")
                continue
            if job["salary"] and _is_over_salary(job["salary"]):
                log(f"    ⏭️  Over salary — skip: {job['title']}")
                continue

            log(f"\n📄  [{i+1}/{len(unique)}] {job['title']} @ {job['company']}")
            job["description"] = await _fetch_description(page, job["url"])

            if not job["description"] or len(job["description"]) < 50:
                log("    ⚠️  Description too short — skip")
                continue

            if _check_work_rights(job["description"]):
                log("    🚫  Requires PR/citizenship — skip")
                job_id = upsert_job(job)
                save_score(job_id, 0, [], [], "Requires PR/citizenship", True)
                stats["skipped"] += 1
                continue

            existing = get_job_by_seek_id(job["seek_id"])
            if existing and existing.get("status") in ("ready", "applied"):
                log("    ↩️  Already processed — skip")
                continue

            job_id = upsert_job(job)

            # ── Local keyword score (no API) ──────────────────────────────
            result = _score_local(job["description"])
            score  = result["score"]
            status = "ready" if score >= config.ATS_THRESHOLD else "scored"

            save_score(
                job_id,
                score,
                result["matched_keywords"],
                result["missing_keywords"],
                result["reason"],
                False,
            )
            update_status(job_id, status)

            flag = "✅" if score >= config.ATS_THRESHOLD else "🟡"
            log(f"    {flag}  Score: {score}% → {status}")

            if status == "ready":
                stats["ready"] += 1
            stats["new_jobs"] += 1

            await _delay()

        await context.close()

    log(
        f"\n✅  Scan complete — "
        f"New: {stats['new_jobs']} | Ready to apply: {stats['ready']} | Skipped: {stats['skipped']}"
    )
    return stats


def get_job_by_seek_id(seek_id: str):
    """Look up an existing job by seek_id to avoid reprocessing."""
    import sqlite3
    try:
        con = sqlite3.connect(config.DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM jobs WHERE seek_id = ?", (seek_id,)).fetchone()
        con.close()
        return dict(row) if row else None
    except Exception:
        return None
