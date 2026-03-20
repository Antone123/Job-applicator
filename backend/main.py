"""
FastAPI backend for the Job Applicator dashboard.

Endpoints:
  GET  /                          → serve dashboard HTML
  GET  /api/jobs                  → list jobs (optional ?status= filter)
  GET  /api/jobs/{id}             → single job details
  GET  /api/stats                 → dashboard stats
  POST /api/scan                  → trigger Seek scrape (background)
  GET  /api/scan/status           → current scan progress messages
  POST /api/jobs/{id}/prepare     → tailor resume + generate cover letter
  POST /api/jobs/{id}/apply       → open Playwright autofill
  POST /api/jobs/{id}/skip        → mark job as skipped
  GET  /files/{job_id}/resume     → serve tailored resume PDF
  GET  /files/{job_id}/cover      → serve cover letter PDF
"""
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from backend import database as db
from backend.resume_builder import build_resume_pdf
from backend.scraper import run_scrape

# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(title="Job Applicator")

FRONTEND_DIR = config.FRONTEND_DIR
OUTPUT_DIR   = config.OUTPUT_DIR
PROFILE_PATH = config.PROFILE_PATH

# Serve generated PDFs
os.makedirs(str(OUTPUT_DIR), exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


def _load_profile() -> dict:
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_base_resume() -> str:
    """Build the base resume PDF from profile.json once; reuse it for all applications."""
    path = config.BASE_RESUME_PATH
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        profile = _load_profile()
        build_resume_pdf(profile, {}, path)   # empty tailored = use original profile
        print(f"✅  Base resume built: {path}")
    return path


# Build base resume at startup
try:
    _ensure_base_resume()
except Exception as e:
    print(f"⚠️  Could not build base resume: {e}")


# ── Scan progress state ────────────────────────────────────────────────────────

scan_state = {
    "running": False,
    "messages": [],
    "last_stats": {}
}


def _scan_log(msg: str):
    scan_state["messages"].append(msg)
    # Keep only last 200 messages
    if len(scan_state["messages"]) > 200:
        scan_state["messages"] = scan_state["messages"][-200:]


def _scan_thread():
    """
    Run the Playwright scraper in a dedicated thread with its own event loop.
    On Windows, uvicorn's SelectorEventLoop cannot spawn subprocesses (Playwright needs this).
    We force ProactorEventLoop via the policy setter — more reliable on Python 3.12+.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _inner():
        scan_state["running"]  = True
        scan_state["messages"] = []
        profile = _load_profile()
        try:
            stats = await run_scrape(profile, on_progress=_scan_log)
            scan_state["last_stats"] = stats
        except Exception as e:
            _scan_log(f"❌  Scan failed: {e}")
        finally:
            scan_state["running"] = False

    try:
        loop.run_until_complete(_inner())
    finally:
        loop.close()


def _run_scan_background():
    """FastAPI background task: spin up the scraper thread."""
    t = threading.Thread(target=_scan_thread, daemon=True)
    t.start()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = FRONTEND_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Frontend not found. Make sure frontend/index.html exists.</h1>", status_code=500)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/jobs")
async def list_jobs(status: Optional[str] = None):
    jobs = db.get_all_jobs(status_filter=status)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/stats")
async def get_stats():
    return db.get_stats()


@app.get("/api/profile")
async def get_profile():
    return _load_profile()


@app.put("/api/profile")
async def save_profile(request: Request):
    profile = await request.json()
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(config.BASE_RESUME_PATH), exist_ok=True)
        build_resume_pdf(profile, {}, config.BASE_RESUME_PATH)
    except Exception as e:
        print(f"⚠️  Could not rebuild resume: {e}")
    return {"status": "saved"}


@app.get("/api/resume/download")
async def download_resume():
    profile = _load_profile()
    os.makedirs(os.path.dirname(config.BASE_RESUME_PATH), exist_ok=True)
    build_resume_pdf(profile, {}, config.BASE_RESUME_PATH)
    return FileResponse(
        config.BASE_RESUME_PATH,
        media_type="application/pdf",
        filename="Antone_Martin_Resume.pdf"
    )


@app.delete("/api/jobs")
async def clear_all_jobs():
    db.clear_all_jobs()
    return {"status": "cleared"}


@app.post("/api/scan")
async def start_scan(background_tasks: BackgroundTasks):
    if scan_state["running"]:
        return {"status": "already_running", "message": "Scan already in progress."}
    background_tasks.add_task(_run_scan_background)  # sync function, spawns its own thread
    return {"status": "started", "message": "Scan started. Check /api/scan/status for progress."}


@app.get("/api/scan/status")
async def scan_status():
    return {
        "running":  scan_state["running"],
        "messages": scan_state["messages"][-50:],   # last 50 log lines
        "stats":    scan_state["last_stats"]
    }


@app.post("/api/jobs/{job_id}/prepare")
async def prepare_application(job_id: int):
    """Tailor resume + generate cover letter for this job. Returns immediately with status."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "applied":
        return {"status": "already_applied"}

    profile = _load_profile()

    try:
        # 1. Tailor resume
        tailored = tailor_resume(job["description"], profile)

        # 2. Generate cover letter
        cover_text = generate_cover_letter(
            job["description"], profile,
            job.get("company", "the company"),
            job.get("title", "the role")
        )

        # 3. Build output paths
        job_out_dir = OUTPUT_DIR / str(job_id)
        job_out_dir.mkdir(parents=True, exist_ok=True)

        safe_title   = "".join(c if c.isalnum() or c in " -" else "_" for c in job.get("title", "role"))[:40]
        safe_company = "".join(c if c.isalnum() or c in " -" else "_" for c in job.get("company", "co"))[:30]
        base_name    = f"{safe_title}_{safe_company}".replace(" ", "_")

        resume_path = str(job_out_dir / f"Resume_{base_name}.pdf")
        cover_path  = str(job_out_dir / f"CoverLetter_{base_name}.pdf")

        # 4. Build PDFs
        build_resume_pdf(profile, tailored, resume_path)
        build_cover_letter_pdf(
            cover_text, profile,
            job.get("company", ""), job.get("title", ""),
            cover_path
        )

        # 5. Save to DB
        db.save_preparation(job_id, tailored, cover_text, resume_path, cover_path)

        return {
            "status":            "prepared",
            "key_changes":       tailored.get("key_changes", ""),
            "cover_letter_text": cover_text,
            "resume_url":        f"/output/{job_id}/{Path(resume_path).name}",
            "cover_url":         f"/output/{job_id}/{Path(cover_path).name}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preparation failed: {str(e)}")


@app.post("/api/jobs/{job_id}/apply")
async def apply_to_job(job_id: int):
    """Deprecated — apply is now done by opening the Seek URL directly."""
    raise HTTPException(status_code=410, detail="Use the Apply on Seek link in the dashboard.")


@app.post("/api/jobs/{job_id}/verify")
async def verify_job(job_id: int):
    """User has reviewed the resume + cover letter and approves them."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("prepared", "verified"):
        raise HTTPException(status_code=400, detail="Job must be prepared before verifying.")
    db.mark_verified(job_id)
    return {"status": "verified"}


@app.post("/api/jobs/{job_id}/skip")
async def skip_job(job_id: int):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.update_status(job_id, "skipped")
    return {"status": "skipped"}


@app.post("/api/jobs/{job_id}/mark_applied")
async def mark_applied_manually(job_id: int):
    """Mark a job as applied manually (user confirmed they submitted)."""
    db.mark_applied(job_id)
    return {"status": "applied"}


@app.get("/files/{job_id}/resume")
async def get_resume(job_id: int):
    job = db.get_job(job_id)
    if not job or not job.get("resume_path"):
        raise HTTPException(status_code=404, detail="Resume not found")
    path = job["resume_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Resume file missing from disk")
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


@app.get("/files/{job_id}/cover")
async def get_cover_letter(job_id: int):
    job = db.get_job(job_id)
    if not job or not job.get("cover_letter_path"):
        raise HTTPException(status_code=404, detail="Cover letter not found")
    path = job["cover_letter_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Cover letter file missing from disk")
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)
