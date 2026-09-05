"""SQLite-backed async job queue with persistence across container restarts (v4.16).

Provides: submit (immediate job-id), status query, auto-retry, timeout,
and SQLite persistence so running/scheduled jobs survive container restarts.

v4.16 changes:
  - SQLite persistence layer (stdlib sqlite3, zero extra dependencies)
  - Jobs survive container restarts (loaded from DB on startup)
  - Auto-vacuum: delete finished jobs older than JOB_RETENTION_HOURS from DB
  - In-memory index for fast queries (DB is the source of truth)
"""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
import time
import uuid
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

DB_DIR = Path(os.getenv("JOB_DB_DIR", "/tmp"))  # v4.38: use /tmp for writable SQLite
DB_PATH = DB_DIR / "job_queue.db"

# ── Configuration ─────────────────────────────────────────────────────
MAX_RETRIES = int(os.getenv("JOB_MAX_RETRIES", "3"))
DEFAULT_TIMEOUT_SEC = int(os.getenv("JOB_DEFAULT_TIMEOUT_SEC", "300"))
MAX_JOBS = int(os.getenv("JOB_MAX_JOBS", "100"))
JOB_RETENTION_HOURS = int(os.getenv("JOB_RETENTION_HOURS", "24"))


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Job:
    id: str
    type: str
    params: dict
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    retries: int = 0


# ── In-memory index (fast queries) + persistent DB (source of truth) ──
_jobs: dict[str, Job] = {}
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════
#  SQLite persistence layer
# ═══════════════════════════════════════════════════════════════════════

def _get_db() -> sqlite3.Connection:
    """Get a thread-local SQLite connection with WAL mode for concurrent reads."""
    db = sqlite3.connect(str(DB_PATH), timeout=5.0,
                         detect_types=sqlite3.PARSE_DECLTYPES)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def _init_db():
    """Create tables and indexes if they don't exist. Idempotent."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = _get_db()
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL NOT NULL DEFAULT 0.0,
                result TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                retries INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_finished ON jobs(finished_at)")
        db.commit()
    finally:
        db.close()


def _job_to_row(job: Job) -> dict:
    return {
        "id": job.id, "type": job.type,
        "params": json.dumps(job.params, ensure_ascii=False),
        "status": job.status.value,
        "progress": job.progress,
        "result": json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "retries": job.retries,
    }


def _row_to_job(row: tuple) -> Job:
    """Convert a DB row tuple to a Job object."""
    (job_id, job_type, params_json, status, progress, result_json,
     error, created_at, started_at, finished_at, retries) = row

    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        params = {}

    try:
        result = json.loads(result_json) if result_json else None
    except json.JSONDecodeError:
        result = result_json  # raw string

    return Job(
        id=job_id, type=job_type, params=params,
        status=JobStatus(status), progress=progress,
        result=result, error=error,
        created_at=created_at, started_at=started_at,
        finished_at=finished_at, retries=retries,
    )


def _save_job(job: Job):
    """Persist a job to SQLite (upsert). Called after every state change."""
    row = _job_to_row(job)
    db = _get_db()
    try:
        db.execute("""
            INSERT OR REPLACE INTO jobs
            (id, type, params, status, progress, result, error, created_at, started_at, finished_at, retries)
            VALUES (:id, :type, :params, :status, :progress, :result, :error, :created_at, :started_at, :finished_at, :retries)
        """, row)
        db.commit()
    finally:
        db.close()


def _load_jobs_from_db() -> dict[str, Job]:
    """Load all non-expired jobs from SQLite on startup."""
    if not DB_PATH.exists():
        return {}

    db = _get_db()
    try:
        # Load pending + running jobs (always) + recently finished jobs
        cutoff = time.time() - JOB_RETENTION_HOURS * 3600
        rows = db.execute("""
            SELECT id, type, params, status, progress, result, error,
                   created_at, started_at, finished_at, retries
            FROM jobs
            WHERE status IN ('pending', 'running')
               OR (status IN ('done', 'failed', 'timeout') AND finished_at > ?)
            ORDER BY created_at DESC
        """, (cutoff,)).fetchall()
        return {r[0]: _row_to_job(r) for r in rows}
    finally:
        db.close()


def _vacuum_db():
    """Remove expired finished jobs from SQLite."""
    cutoff = time.time() - JOB_RETENTION_HOURS * 3600
    db = _get_db()
    try:
        deleted = db.execute("""
            DELETE FROM jobs
            WHERE status IN ('done', 'failed', 'timeout')
              AND finished_at < ?
        """, (cutoff,)).rowcount
        if deleted > 0:
            db.commit()
    finally:
        db.close()


def submit_job(job_type: str, params: dict) -> Job:
    """Create a job, persist to DB, and return immediately with its ID.

    Jobs survive container restarts via SQLite persistence.
    """
    job = Job(id=uuid.uuid4().hex[:12], type=job_type, params=params)
    with _lock:
        _jobs[job.id] = job
        # Evict oldest done/failed jobs if over capacity
        if len(_jobs) > MAX_JOBS:
            finished = [(jid, j) for jid, j in _jobs.items()
                        if j.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.TIMEOUT)]
            finished.sort(key=lambda x: x[1].finished_at or 0)
            for jid, _ in finished[:len(_jobs) - MAX_JOBS]:
                del _jobs[jid]

    _save_job(job)  # Persist immediately
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        # Try loading from DB (e.g., job was created before restart)
        job = _load_single_job(job_id)
        if job:
            with _lock:
                _jobs[job_id] = job  # cache in memory
    return job


def _load_single_job(job_id: str) -> Job | None:
    """Load a single job from DB (fallback for pre-restart jobs)."""
    if not DB_PATH.exists():
        return None
    db = _get_db()
    try:
        row = db.execute("""
            SELECT id, type, params, status, progress, result, error,
                   created_at, started_at, finished_at, retries
            FROM jobs WHERE id = ?
        """, (job_id,)).fetchone()
        if row:
            return _row_to_job(row)
    finally:
        db.close()
    return None


def list_jobs(limit: int = 20) -> list[Job]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]


def _update(job_id: str, **kwargs):
    """Update job state in memory and persist to DB."""
    with _lock:
        j = _jobs.get(job_id)
        if j:
            for k, v in kwargs.items():
                setattr(j, k, v)
    # Persist after memory update
    if j:
        _save_job(j)


async def run_job(job_id: str, coro_factory: Callable[[Job], Any],
                 timeout: float = DEFAULT_TIMEOUT_SEC):
    """Execute a job with retry + timeout. State persisted to SQLite on every change."""
    job = get_job(job_id)
    if not job:
        return

    _update(job_id, status=JobStatus.RUNNING, started_at=time.time())

    for attempt in range(1 + MAX_RETRIES):
        try:
            result = await asyncio.wait_for(coro_factory(job), timeout=timeout)
            _update(job_id, status=JobStatus.DONE, result=result,
                     finished_at=time.time(), progress=1.0)
            return
        except asyncio.TimeoutError:
            _update(job_id, status=JobStatus.TIMEOUT,
                     error=f"Timed out after {timeout}s (attempt {attempt + 1})",
                     finished_at=time.time())
            return
        except Exception as e:
            if attempt >= MAX_RETRIES:
                _update(job_id, status=JobStatus.FAILED,
                         error=f"{type(e).__name__}: {e} (after {attempt + 1} attempts)",
                         finished_at=time.time())
                return
            await asyncio.sleep(2 ** attempt)  # exponential backoff
            _update(job_id, retries=attempt + 1)


def set_progress(job_id: str, progress: float):
    _update(job_id, progress=min(max(progress, 0.0), 1.0))


def cleanup_old_jobs():
    """Remove finished jobs older than JOB_RETENTION_HOURS from memory and DB."""
    cutoff = time.time() - JOB_RETENTION_HOURS * 3600
    with _lock:
        stale = [jid for jid, j in _jobs.items()
                 if j.finished_at and j.finished_at < cutoff
                 and j.status != JobStatus.RUNNING]
        for jid in stale:
            del _jobs[jid]

    _vacuum_db()  # Also clean DB
    return len(stale)


def job_stats() -> dict:
    """Return queue statistics."""
    with _lock:
        by_status = {}
        for j in _jobs.values():
            by_status[j.status.value] = by_status.get(j.status.value, 0) + 1
        return {
            "total": len(_jobs),
            "max_capacity": MAX_JOBS,
            "by_status": by_status,
            "retention_hours": JOB_RETENTION_HOURS,
            "persistence": "sqlite",
            "db_path": str(DB_PATH),
            "db_exists": DB_PATH.exists(),
        }


# ═══════════════════════════════════════════════════════════════════════
#  Startup: load jobs from DB and mark running jobs as failed (restart)
# ═══════════════════════════════════════════════════════════════════════

def init_queue():
    """Initialize the job queue: create DB, load persisted jobs.

    PENDING jobs are preserved (will be picked up on next submit).
    RUNNING jobs from before restart are marked as TIMEOUT (lost execution).
    """
    _init_db()

    loaded = _load_jobs_from_db()
    restarted = 0
    with _lock:
        for job_id, job in loaded.items():
            if job.status == JobStatus.RUNNING:
                # Was running when container stopped — mark as timeout
                job.status = JobStatus.TIMEOUT
                job.error = f"Job lost due to container restart at {time.time()}"
                job.finished_at = time.time()
                _save_job(job)
                restarted += 1
            _jobs[job_id] = job

    if loaded:
        import logging
        logger = logging.getLogger("pipeline.job_queue")
        logger.info(
            f"Loaded {len(loaded)} jobs from {DB_PATH} "
            f"({restarted} running jobs marked as TIMEOUT)"
        )

    return len(loaded)


# Initialize on module import
_init_db()  # ensure tables exist
_loaded_count = _load_jobs_from_db()
with _lock:
    for _job_id, _job in _loaded_count.items():
        if _job.status == JobStatus.RUNNING:
            _job.status = JobStatus.TIMEOUT
            _job.error = f"Job lost due to container restart"
            _job.finished_at = time.time()
            _save_job(_job)
        _jobs[_job_id] = _job
