import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"
BACKEND_DIR  = BASE_DIR / "backend"

# ── Credentials ───────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SEEK_EMAIL     = os.getenv("SEEK_EMAIL", "")
SEEK_PASSWORD  = os.getenv("SEEK_PASSWORD", "")

# ── Seek search settings ───────────────────────────────────────────────────────
SEARCH_QUERIES = [
    # Junior / entry-level targeted
    "junior data analyst",
    "junior business analyst",
    "entry level data analyst",
    "graduate data analyst",
    "graduate analyst",

    # Broad role titles (Seek search catches entry-level within these)
    "data analyst",
    "business analyst",
    "reporting analyst",
    "visualisation analyst",
    "analytics analyst",

    # Domain-specific analyst roles
    "supply chain analyst",
    "logistics analyst",
    "operations analyst",

    # Tool / skill focused
    "SQL analyst",
    "Power BI analyst",
    "Python analyst",
]

SEARCH_LOCATION   = "Melbourne VIC"
MAX_PAGES_PER_QUERY = 2          # pages of results to scrape per query
JOBS_PER_PAGE       = 22         # Seek shows ~22 jobs per page

# ── Test mode ──────────────────────────────────────────────────────────────────
TEST_MODE  = True   # set False for full scans
TEST_LIMIT = 2      # max jobs to prepare when TEST_MODE is on

# ── Application settings ───────────────────────────────────────────────────────
ATS_THRESHOLD = 70               # minimum local keyword match score to show Apply button

# Salary limits – skip jobs explicitly above these
MAX_SALARY_ANNUAL = 90_000       # per annum (AUD)
MAX_SALARY_DAILY  = 400          # per day (AUD)

# Anti-ban: max applications per session (user still clicks Submit each time)
MAX_APPLICATIONS_PER_SESSION = 10

# Senior role filter – skip titles containing these words
SENIOR_ROLE_KEYWORDS = [
    "senior", "sr.", "sr ", "lead ", "principal", "head of",
    "manager", "director", "vp ", "vice president", "chief",
    "staff analyst", "architect", "associate director", "general manager",
    "specialist iii", "level iii", "level 3",
]

# Work rights filter – jobs containing these phrases are flagged and skipped
WORK_RIGHTS_PHRASES = [
    "australian citizen",
    "permanent resident",
    "pr or citizen",
    "citizen or pr",
    "citizenship required",
    "must be a citizen",
    "must hold australian citizenship",
    "security clearance",
]

# ── Scraper timing ─────────────────────────────────────────────────────────────
SCRAPER_DELAY_MIN = 2.0          # seconds between requests (min)
SCRAPER_DELAY_MAX = 5.0          # seconds between requests (max)

# ── File paths ─────────────────────────────────────────────────────────────────
DB_PATH           = str(DATA_DIR / "jobs.db")
PROFILE_PATH      = str(DATA_DIR / "profile.json")
SEEK_SESSION_PATH = str(DATA_DIR / "seek_session.json")

# ── Base resume (built once from profile, reused for all applications) ──────────
BASE_RESUME_PATH = str(OUTPUT_DIR / "base_resume" / "Antone_Martin_Resume.pdf")
