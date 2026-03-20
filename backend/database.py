"""
Thin SQLite wrapper – no ORM, just plain sqlite3 for simplicity.
All state for every scraped job lives in a single `jobs` table.
"""
import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = str(BASE_DIR / "data" / "jobs.db")


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(str(BASE_DIR / "data"), exist_ok=True)
    os.makedirs(str(BASE_DIR / "output"), exist_ok=True)
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                seek_id           TEXT    UNIQUE NOT NULL,
                title             TEXT,
                company           TEXT,
                location          TEXT,
                salary            TEXT,
                employment_type   TEXT,
                description       TEXT,
                url               TEXT,
                scraped_at        TEXT,

                ats_score         REAL,
                matched_keywords  TEXT,   -- JSON list
                missing_keywords  TEXT,   -- JSON list
                ats_reason        TEXT,
                work_rights_flag  INTEGER DEFAULT 0,

                status            TEXT DEFAULT 'new',
                -- new | scored | skipped | prepared | verified | applied

                resume_path       TEXT,
                cover_letter_path TEXT,
                tailored_json     TEXT,   -- full tailored profile JSON
                cover_letter_text TEXT,

                verified          INTEGER DEFAULT 0,
                applied_at        TEXT,
                notes             TEXT
            )
        """)
        # Add verified column to existing databases that predate this column
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN verified INTEGER DEFAULT 0")
        except Exception:
            pass
        con.commit()


# ── Write ──────────────────────────────────────────────────────────────────────

def upsert_job(job: dict) -> int:
    """Insert a new job; if seek_id already exists, skip it (return existing id)."""
    with _conn() as con:
        cur = con.execute("SELECT id FROM jobs WHERE seek_id = ?", (job["seek_id"],))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = con.execute("""
            INSERT INTO jobs (seek_id, title, company, location, salary,
                              employment_type, description, url, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            job["seek_id"], job["title"], job["company"], job["location"],
            job.get("salary", ""), job.get("employment_type", ""),
            job.get("description", ""), job["url"],
            datetime.utcnow().isoformat()
        ))
        con.commit()
        return cur.lastrowid


def save_score(job_id: int, score: float, matched: list, missing: list,
               reason: str, work_rights_flag: bool):
    status = "skipped" if work_rights_flag else ("scored" if score < 80 else "scored")
    with _conn() as con:
        con.execute("""
            UPDATE jobs SET
                ats_score        = ?,
                matched_keywords = ?,
                missing_keywords = ?,
                ats_reason       = ?,
                work_rights_flag = ?,
                status           = ?
            WHERE id = ?
        """, (
            score,
            json.dumps(matched),
            json.dumps(missing),
            reason,
            int(work_rights_flag),
            "skipped" if work_rights_flag else "scored",
            job_id
        ))
        con.commit()


def save_preparation(job_id: int, tailored_json: dict,
                     cover_letter_text: str,
                     resume_path: str, cover_letter_path: str):
    with _conn() as con:
        con.execute("""
            UPDATE jobs SET
                tailored_json     = ?,
                cover_letter_text = ?,
                resume_path       = ?,
                cover_letter_path = ?,
                status            = 'prepared'
            WHERE id = ?
        """, (
            json.dumps(tailored_json),
            cover_letter_text,
            resume_path,
            cover_letter_path,
            job_id
        ))
        con.commit()


def mark_verified(job_id: int):
    with _conn() as con:
        con.execute(
            "UPDATE jobs SET verified = 1, status = 'verified' WHERE id = ?",
            (job_id,)
        )
        con.commit()


def mark_applied(job_id: int):
    with _conn() as con:
        con.execute("""
            UPDATE jobs SET status = 'applied', applied_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), job_id))
        con.commit()


def update_status(job_id: int, status: str):
    with _conn() as con:
        con.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        con.commit()


def clear_all_jobs():
    with _conn() as con:
        con.execute("DELETE FROM jobs")
        con.commit()


# ── Read ───────────────────────────────────────────────────────────────────────

def get_all_jobs(status_filter: str = None) -> list:
    with _conn() as con:
        if status_filter:
            rows = con.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM jobs ORDER BY scraped_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_stats() -> dict:
    with _conn() as con:
        total   = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        ready   = con.execute("SELECT COUNT(*) FROM jobs WHERE status = 'ready'").fetchone()[0]
        applied = con.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0]
        skipped = con.execute("SELECT COUNT(*) FROM jobs WHERE status = 'skipped'").fetchone()[0]
    return {"total": total, "ready": ready, "applied": applied, "skipped": skipped}


def _row_to_dict(row) -> dict:
    d = dict(row)
    for key in ("matched_keywords", "missing_keywords", "tailored_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    return d
