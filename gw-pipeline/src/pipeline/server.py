"""FastAPI server exposing Astropy pipeline as REST endpoints.

Provides: FITS cutout, WCS queries, source detection, SNR analysis.
"""
from __future__ import annotations
import json
import os
import re
import socket
from pathlib import Path
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
import httpx
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from .fits_core import read_fits, fits_cutout, wcs_info, sky_to_pixel, FITSError
from .source_extraction import detect_sources, detect_extended_sources, compute_snr_map
from .thumbnail_cache import cache_key, get_cached, set_cache, cache_stats
# v4.32: DL Anomaly Classifier temporarily disabled
# from .anomaly_classifier import classify_anomalies
from .dl_inference import (
    classify_galaxy_morphology,
    classify_source_type,
    enhance_anomaly_detection,
    get_model_status as dl_get_model_status,
    warmup_models as dl_warmup_models,
    GalaxyMorphologyResult,
    SourceTypeResult,
    AnomalyEnhancementResult,
)
from .dl_inference import (
    classify_galaxy_morphology,
    classify_source_type,
    enhance_anomaly_detection,
    get_model_status as dl_get_model_status,
    run_concurrency_diagnostic as dl_concurrency_test,  # v4.29
)
# v4.35: RBAC middleware (Fix #1)
from .rbac import RBACMiddleware, get_role_quota
# v4.35: MongoDB audit (Fix #6)
from .audit_mongo import (
    write_audit_entry, check_alerts, query_audit_logs,
    get_audit_stats, get_recent_alerts,
)
# v4.37: Security + Operations routes
from .routes_v437 import register_routes
# v4.38: Engineering + Quality routes (Fixes #3, #4, #6)
from .routes_v438 import register_routes as register_routes_v438
# v4.38: FITS upload + vision (Fix #5)
from .fits_upload import register_upload_routes
# R6.44: Observability routes (font error monitoring + A/B test dashboard)
from .routes_v444 import register_routes as register_routes_v444
# R6.46: AB history + alert endpoints
from .routes_v446 import register_routes as register_routes_v446
from .routes_v447 import register_routes as register_routes_v447
# R6.49: Alert routing audit log endpoints
from .routes_v449 import register_routes_v449
from .routes_v449_hips import register_routes as register_routes_v449_hips
from .routes_v450 import register_routes_v450

class DLClassifyRequest(BaseModel):
    """Request body for DL model inference endpoints (v4.18)."""
    filename: str = Field(..., min_length=1, description="FITS filename in the data directory")

class DLAnomalyEnhanceRequest(BaseModel):
    """Request body for DL-enhanced anomaly detection (v4.18)."""
    filename: str = Field(..., min_length=1, description="FITS filename")
    anomaly_type: str = Field(..., pattern=r"^(spike|dip|pattern_break|wcs_mismatch)$", description="Anomaly type: spike, dip, pattern_break, or wcs_mismatch")
    rule_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence from rule classifier")

class SourceDetectionRequest(BaseModel):
    """Request body for POST /pipeline/sources — async source detection."""
    filename: str = Field(..., min_length=1, description="FITS filename in the data directory")
    fwhm: float = Field(3.0, ge=1.0, le=20.0, description="FWHM in pixels")
    snr_threshold: float = Field(5.0, ge=1.0, le=50.0, description="SNR threshold")

app = FastAPI(
    title="GW Astropy Pipeline",
    description="FITS processing, WCS transforms, and source extraction for gravitational wave astronomy",
    version="0.1.0",
)

# v4.35: Register RBAC middleware (Fix #1)
app.add_middleware(RBACMiddleware)
# v4.37: Register security + operations routes
register_routes(app)
# R6.44: Register observability routes (font errors + A/B dashboard)
register_routes_v444(app)
# R6.46: Register AB history + alert routes
register_routes_v446(app)
register_routes_v447(app)
register_routes_v449(app)
register_routes_v449_hips(app)
# R6.50: Audit retention + full-text search + PDF signature verification
register_routes_v450(app)

# R6.27f: Register HiPS cutout proxy (with disk cache) — frontend uses this
# instead of direct alasky.cds.unistra.fr access (which the cloudflared tunnel
# browser can't reliably reach).
try:
    # R6.27f: ensure /app/src is on sys.path so `from pipeline.routes.hips`
    # works regardless of uvicorn launch cwd (uvicorn may launch from /app).
    # __file__ is /app/src/pipeline/server.py, so dirname(dirname(__file__)) is /app/src
    import os as _os
    import sys as _sys
    _PIPELINE_SRC = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _PIPELINE_SRC not in _sys.path:
        _sys.path.insert(0, _PIPELINE_SRC)
    from pipeline.routes.hips import router as hips_router
    app.include_router(hips_router, prefix="/pipeline", tags=["hips"])
    import logging as _logging
    _logging.getLogger("pipeline.startup").info("hips router loaded: %s", [r.path for r in hips_router.routes])
except Exception as e:
    import logging
    logging.getLogger("pipeline.startup").warning(f"hips router not loaded: {e}")

# R6.61.c: CSP violation reporter (frontend cspMonitor.ts POSTs here).
try:
    from pipeline.routes.security import router as security_router
    app.include_router(security_router, prefix="/pipeline", tags=["security"])
    import logging as _logging_sec
    _logging_sec.getLogger("pipeline.startup").info("security router loaded: %s", [r.path for r in security_router.routes])
except Exception as e:
    import logging as _logging_sec
    _logging_sec.getLogger("pipeline.startup").warning(f"security router not loaded: {e}")

@app.on_event("startup")
async def startup_init():
    """Initialize persistent subsystems on server start (v4.16)."""
    import logging
    log = logging.getLogger("pipeline.startup")

    # Initialize job queue persistence (SQLite)
    try:
        loaded = init_queue()
        log.info(f"Job queue initialized: {loaded} jobs loaded from {_JOB_DB_PATH}")

    except Exception as e:
        log.warning(f"Job queue init failed (non-fatal): {e}")
    # Warm up DL models
    try:
        dl_status = dl_warmup_models()
        log.info(f"DL models: onnx={dl_status['onnx_available']}, "
                 f"loaded={dl_status['models_loaded']}, "
                 f"failed={dl_status['models_failed']}")
        if dl_status.get('note'):
            log.info(f"DL note: {dl_status['note']}")
    except Exception as e:
        log.warning(f"DL model warmup failed (non-fatal): {e}")

    # Warm up DL models (v4.18)
    try:
        dl_status = dl_warmup_models()
        log.info(f"DL models: onnx={dl_status['onnx_available']}, "
                 f"loaded={dl_status['models_loaded']}, "
                 f"failed={dl_status['models_failed']}")
        if dl_status.get('note'):
            log.info(f"DL note: {dl_status['note']}")
    except Exception as e:
        log.warning(f"DL model warmup failed (non-fatal): {e}")

    # Log pool configuration
    log.info(
        f"Thread pools: light={_LIGHT_WORKERS} workers, "
        f"heavy={_HEAVY_WORKERS} workers (CPU={_CPU_COUNT}), "
        f"max_file={_MAX_FILE_MB}MB"
    )

# ── Request timing middleware (v4.12) ────────────────────────────
import time as _time
from collections import defaultdict

_timing_stats: dict = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0, "times": []})
_TIMING_WINDOW = 100  # keep last N durations per endpoint for percentile calc

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    t0 = _time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((_time.perf_counter() - t0) * 1000, 1)
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)

    # Record stats (lightweight, per-endpoint)
    route = request.url.path
    s = _timing_stats[route]
    s["count"] += 1
    s["total_ms"] += elapsed_ms
    s["max_ms"] = max(s["max_ms"], elapsed_ms)
    s["times"].append(elapsed_ms)
    if len(s["times"]) > _TIMING_WINDOW:
        s["times"].pop(0)
    return response

@app.get("/pipeline/stats")
async def timing_stats():
    """Per-endpoint execution timing (p50, p99, count, max, avg)."""
    import numpy as np
    endpoints = {}
    for route, s in sorted(_timing_stats.items()):
        times = sorted(s["times"])
        if not times:
            continue
        arr = np.array(times)
        endpoints[route] = {
            "count": s["count"],
            "avg_ms": round(s["total_ms"] / s["count"], 1),
            "max_ms": round(s["max_ms"], 1),
            "p50_ms": round(float(np.percentile(arr, 50)), 1),
            "p99_ms": round(float(np.percentile(arr, 99)), 1),
        }
    return {"endpoints": endpoints, "window": _TIMING_WINDOW}

@app.get("/pipeline/pool-stats")
async def pool_stats_endpoint():
    """Thread pool and admission-control statistics (v4.16).

    Shows dual-pool utilization: light (WCS/header) and heavy (thumbnail/source detection).
    Includes per-tier admission control info for file-size-based gating.
    """
    return {
        "light_pool": {
            "max_workers": _LIGHT_WORKERS,
            "active": _pool_stats["light_active"],
            "total_completed": _pool_stats["light_total"],
        },
        "heavy_pool": {
            "max_workers": _HEAVY_WORKERS,
            "active": _pool_stats["heavy_active"],
            "total_completed": _pool_stats["heavy_total"],
            "queued": _pool_stats["heavy_queued"],
            "rejected_size": _pool_stats["heavy_rejected_size"],
        },
        "admission_tiers": {
            "small": f"<{_SMALL_FILE_BYTES // (1024**2)}MB → {_heavy_total_slots} concurrent slots",
            "medium": f"{_SMALL_FILE_BYTES // (1024**2)}–{_MEDIUM_FILE_BYTES // (1024**2)}MB → {max(1, _heavy_total_slots // 2)} slots",
            "large": f">{_MEDIUM_FILE_BYTES // (1024**2)}MB → {max(1, _heavy_total_slots // 4)} slots",
            "max_file_mb": _MAX_FILE_MB,
        },
        "cpu_count": _CPU_COUNT,
        "dl_inference": {
            "max_concurrent": _DL_MAX_CONCURRENT,
            "timeout_sec": _DL_INFERENCE_TIMEOUT_SEC,
            "min_free_memory_mb": _DL_MIN_FREE_MEMORY_MB,
            "current_free_memory_mb": round(_get_free_memory_mb(), 0),
            "stats": dict(_dl_inference_stats),
            "gpl_models_excluded": os.environ.get("GW_EXCLUDE_GPL_MODELS", "false").lower() == "true",
        },
    }

# ═══════════════════════════════════════════════════════════════════════
# Thread pools — dual-pool architecture (v4.16)
# ═══════════════════════════════════════════════════════════════════════
# LIGHT pool: WCS queries, header reads, metadata — always responsive (2 workers)
# HEAVY pool: thumbnail gen, source detection, cutout — gated by file size
#
# File-size admission control prevents large FITS from starving small ones:
#   < 50 MB  → uses up to heavy_max workers (full concurrency)
#   50-200 MB → limited to heavy_max // 2 workers
#   > 200 MB  → limited to max(1, heavy_max // 4) workers
#   > MAX_FILE_MB → rejected (HTTP 413)
#
# Override with env vars:
#   FITS_LIGHT_WORKERS  (default: 2)
#   FITS_HEAVY_WORKERS  (default: cpu_count, max 16)
#   FITS_MAX_FILE_MB    (default: 500)
# ═══════════════════════════════════════════════════════════════════════
import threading as _threading
import datetime as _datetime

_CPU_COUNT = max(1, (os.cpu_count() or 4))

_LIGHT_WORKERS = int(os.getenv("FITS_LIGHT_WORKERS", "2"))
_HEAVY_WORKERS = min(int(os.getenv("FITS_HEAVY_WORKERS", str(_CPU_COUNT))), 16)
_MAX_FILE_MB = int(os.getenv("FITS_MAX_FILE_MB", "500"))

# File-size admission thresholds (v4.16: env-configurable)
_SMALL_FILE_MB = int(os.getenv("FITS_SMALL_FILE_MB", "50"))
_MEDIUM_FILE_MB = int(os.getenv("FITS_MEDIUM_FILE_MB", "200"))
_SMALL_FILE_BYTES = _SMALL_FILE_MB * 1024 * 1024
_MEDIUM_FILE_BYTES = _MEDIUM_FILE_MB * 1024 * 1024
_MAX_FILE_BYTES = _MAX_FILE_MB * 1024 * 1024

# Thumbnail-specific size limit (defaults to FITS_MAX_FILE_MB)
_THUMBNAIL_MAX_MB = int(os.getenv("THUMBNAIL_MAX_FILE_MB", str(_MAX_FILE_MB)))
_THUMBNAIL_MAX_BYTES = _THUMBNAIL_MAX_MB * 1024 * 1024

# LLM proxy timeouts (v4.16: env-configurable for DeepSeek latency)
_LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT_SEC", "15.0"))
_LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT_SEC", "120.0"))
_LLM_TOTAL_TIMEOUT = float(os.getenv("LLM_TOTAL_TIMEOUT_SEC", "180.0"))
_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# ── LLM quota tracking (v4.23) ──
_LLM_DAILY_QUOTA = int(os.getenv("LLM_DAILY_QUOTA", "500"))
_llm_quota_date = _datetime.date.today()
_llm_daily_count = {}  # v4.38: per-user counter (Dict[str,int], was global int 0)
_llm_quota_lock = _threading.Lock()

# v4.34: Session-based quota tracking (Fix #3)
_SESSION_QUOTAS: "Dict[str, int]" = {}
_SESSION_QUOTA_LIMIT = int(os.getenv("LLM_SESSION_QUOTA", "100"))
_SESSION_QUOTA_WARN_PCT = float(os.getenv("LLM_SESSION_QUOTA_WARN_PCT", "0.8"))

def _llm_check_quota(session_id: str = None, user_id: str = None):  # v4.38: per-user
    """Check and roll daily quota. Returns dict with allowed/remaining/daily_count/quota.

    v4.34: Supports optional session_id for per-user quota tracking.
    """
    global _llm_daily_count, _llm_quota_date
    with _llm_quota_lock:
        today = _datetime.date.today()
        if today != _llm_quota_date:
            _llm_quota_date = today
            _llm_daily_count = {}  # v4.38: per-user counter (Dict[str,int], was global int 0)
            _SESSION_QUOTAS.clear()  # Reset session quotas daily
        key = user_id or "__anon__"
        user_count = _llm_daily_count.get(key, 0)
        user_allowed = user_count < _LLM_DAILY_QUOTA
        result = {
            "allowed": user_allowed,
            "remaining": max(0, _LLM_DAILY_QUOTA - user_count),
            "daily_count": user_count,
            "quota": _LLM_DAILY_QUOTA,
            "user_id": key,
        }
        # v4.34: Per-session quota
        if session_id:
            session_count = _SESSION_QUOTAS.get(session_id, 0)
            session_allowed = session_count < _SESSION_QUOTA_LIMIT
            result["session_allowed"] = session_allowed
            result["session_count"] = session_count
            result["session_quota"] = _SESSION_QUOTA_LIMIT
            result["session_warning"] = session_count >= _SESSION_QUOTA_LIMIT * _SESSION_QUOTA_WARN_PCT
            # Session quota overrides global for "allowed" decision
            if not session_allowed:
                result["allowed"] = False
        return result

def _llm_record_request(session_id: str = None, user_id: str = None):
    """Increment daily LLM request counter. Thread-safe.

    v4.38: Per-user tracking — increments only the requesting user's counter.
    """
    global _llm_daily_count
    with _llm_quota_lock:
        key = user_id or "__anon__"
        _llm_daily_count[key] = _llm_daily_count.get(key, 0) + 1
        if session_id:
            _SESSION_QUOTAS[session_id] = _SESSION_QUOTAS.get(session_id, 0) + 1

# v4.34: Compliance audit logging (Fix #4)
_COMPLIANCE_LEVEL = os.getenv("COMPLIANCE_LEVEL", "moderate")  # strict | moderate | relaxed
_COMPLIANCE_LOG_DIR = os.getenv("COMPLIANCE_LOG_DIR", "/app/logs")

def _audit_compliance_log(user_input: str, session_id: str, action: str, extra: dict = None):
    """Log data sent to third-party API for compliance auditing."""
    try:
        import os as _os_audit
        log_dir = _os_audit.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
        if not _os_audit.exists(log_dir):
            _os_audit.makedirs(log_dir, exist_ok=True)
        log_path = _os_audit.join(log_dir, "compliance_audit.log")
        entry = {
            "timestamp": _datetime.datetime.utcnow().isoformat() + "Z",
            "session_id": session_id or "unknown",
            "action": action,
            "input_length": len(user_input) if user_input else 0,
            "compliance_level": _COMPLIANCE_LEVEL,
        }
        if extra:
            entry.update(extra)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Compliance logging is best-effort

def _detect_sensitive_coordinates(text: str) -> list:
    """Detect potential unpublished survey coordinates in user input."""
    import re as _re_sens
    sensitive = []
    # Full-precision coordinates (>4 decimal places suggests unpublished data)
    high_prec = _re_sens.findall(r'\b\d{1,3}\.\d{5,}\b', text)
    if high_prec:
        sensitive.append(f"High-precision coordinates detected: {len(high_prec)} value(s)")
    return sensitive

# Dual thread pools
_light_executor = ThreadPoolExecutor(max_workers=_LIGHT_WORKERS, thread_name_prefix="fits-light")
_heavy_executor = ThreadPoolExecutor(max_workers=_HEAVY_WORKERS, thread_name_prefix="fits-heavy")

# R6.26: log the startup memory budget so /status and /health can reflect it
try:
    from memory_budget import print_budget_report as _mem_report
    _mem_report()
except Exception as _e:
    import logging as _lg
    _lg.getLogger(__name__).warning("memory_budget.print_budget_report failed: %s", _e)

# Heavy-pool admission semaphores — per-tier concurrency limits
_heavy_total_slots = _HEAVY_WORKERS
_heavy_small_slots  = asyncio.Semaphore(_heavy_total_slots)
_heavy_medium_slots = asyncio.Semaphore(max(1, _heavy_total_slots // 2))
_heavy_large_slots  = asyncio.Semaphore(max(1, _heavy_total_slots // 4))

# Pool statistics (best-effort, no lock for counters)
_pool_stats_lock = _threading.Lock()
_pool_stats = {
    "light_active": 0, "light_total": 0,
    "heavy_active": 0, "heavy_total": 0,
    "heavy_rejected_size": 0, "heavy_queued": 0,
}

# Thumbnail generation semaphore — limits concurrent thumbnail MISS generation
_thumbnail_sem = asyncio.Semaphore(max(2, _HEAVY_WORKERS // 4))

# R6.26: DL inference concurrency is now memory-budget-aware.
# DL_MAX_CONCURRENT_INFERENCE env var still wins (ops escape hatch); otherwise
# memory_budget.get_max_concurrent_inferences() reads the container cgroup
# limit and divides by per-model size (~150 MB) and CPU count to derive a safe cap.
try:
    from memory_budget import get_max_concurrent_inferences as _mem_dl_cap
    _DL_MAX_CONCURRENT = int(os.getenv("DL_MAX_CONCURRENT_INFERENCE", _mem_dl_cap()))
except Exception:
    # Fallback to legacy hardcoded value if memory_budget fails to import
    _DL_MAX_CONCURRENT = int(os.getenv("DL_MAX_CONCURRENT_INFERENCE", "3"))
_dl_inference_sem = asyncio.Semaphore(_DL_MAX_CONCURRENT)
_DL_INFERENCE_TIMEOUT_SEC = int(os.getenv("DL_INFERENCE_TIMEOUT_SEC", "30"))
# Memory threshold: reject DL requests if less than this many MB free
_DL_MIN_FREE_MEMORY_MB = int(os.getenv("DL_MIN_FREE_MEMORY_MB", "200"))

# v4.27: DL inference statistics (best-effort, lock-free counters)
_dl_inference_stats = {
    "total_requests": 0,
    "completed": 0,
    "queued": 0,
    "timed_out": 0,
    "oom_rejected": 0,
    "gpl_excluded": 0,
}
_dl_inference_lock = _threading.Lock()

def _get_free_memory_mb() -> float:
    """Get available system memory in MB. Cross-platform (Linux/Windows/macOS)."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except ImportError:
        pass
    # Fallback: try /proc/meminfo on Linux
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024
    except Exception:
        pass
    # Final fallback: assume enough memory
    return float("inf")

async def _run_dl_inference(filepath: Path, func, *args):
    """Run a DL inference task with concurrency control and timeout (v4.27).

    - Acquires DL inference semaphore (max 3 concurrent)
    - Checks available memory before admitting
    - Wraps _run_heavy() with asyncio.wait_for() timeout
    - Tracks inference statistics
    """
    with _dl_inference_lock:
        _dl_inference_stats["total_requests"] += 1

    # Memory check before admission
    free_mb = _get_free_memory_mb()
    if free_mb < _DL_MIN_FREE_MEMORY_MB:
        with _dl_inference_lock:
            _dl_inference_stats["oom_rejected"] += 1
        raise HTTPException(
            503,
            f"DL inference unavailable: insufficient memory "
            f"({free_mb:.0f}MB free, need {_DL_MIN_FREE_MEMORY_MB}MB). "
            f"Try again later or reduce concurrent requests."
        )

    # Acquire semaphore (queue if all slots busy)
    with _dl_inference_lock:
        if _dl_inference_sem.locked():
            _dl_inference_stats["queued"] += 1

    async with _dl_inference_sem:
        try:
            result = await asyncio.wait_for(
                _run_heavy(filepath, func, *args),
                timeout=_DL_INFERENCE_TIMEOUT_SEC,
            )
            with _dl_inference_lock:
                _dl_inference_stats["completed"] += 1
            return result
        except asyncio.TimeoutError:
            with _dl_inference_lock:
                _dl_inference_stats["timed_out"] += 1
            raise HTTPException(
                504,
                f"DL inference timed out after {_DL_INFERENCE_TIMEOUT_SEC}s. "
                f"The model may be overloaded or the FITS file too large. "
                f"Retry with fewer concurrent requests."
            )

def _get_file_size_mb(filepath: Path) -> float:
    try:
        return filepath.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0

def _check_file_size_limit(filepath: Path) -> None:
    """Reject files > _MAX_FILE_MB before they enter the thread pool."""
    try:
        size_bytes = filepath.stat().st_size
        if size_bytes > _MAX_FILE_BYTES:
            mb = size_bytes / (1024 * 1024)
            raise HTTPException(
                413,
                f"FITS file too large for real-time processing: {mb:.0f} MB "
                f"(max {_MAX_FILE_MB} MB). Use the cutout API with a smaller "
                f"region or process this file offline."
            )
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(404, f"Cannot access file: {e}")

async def _run_light(func, *args):
    """Run a lightweight FITS operation (WCS, header, metadata) in the light pool."""
    loop = asyncio.get_running_loop()
    with _pool_stats_lock:
        _pool_stats["light_active"] += 1
        _pool_stats["light_total"] += 1
    try:
        return await loop.run_in_executor(_light_executor, func, *args)
    finally:
        with _pool_stats_lock:
            _pool_stats["light_active"] -= 1

async def _run_heavy(filepath: Path, func, *args):
    """Run a heavy FITS operation with file-size admission control."""
    _check_file_size_limit(filepath)
    size_bytes = filepath.stat().st_size

    if size_bytes < _SMALL_FILE_BYTES:
        sem = _heavy_small_slots
    elif size_bytes < _MEDIUM_FILE_BYTES:
        sem = _heavy_medium_slots
    else:
        sem = _heavy_large_slots

    with _pool_stats_lock:
        _pool_stats["heavy_queued"] += 1
    await sem.acquire()
    with _pool_stats_lock:
        _pool_stats["heavy_queued"] -= 1
        _pool_stats["heavy_active"] += 1
        _pool_stats["heavy_total"] += 1

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_heavy_executor, func, *args)
    finally:
        sem.release()
        with _pool_stats_lock:
            _pool_stats["heavy_active"] -= 1

FITS_DIR = Path(os.getenv("FITS_DATA_DIR", "/app/data"))

ALLOWED_EXTENSIONS = {'.fits', '.fit', '.fits.gz', '.fit.gz', '.fits.fz'}

FITS_MAGIC = b"SIMPLE  ="

def _check_wcs_integrity(filepath: Path) -> tuple[bool, list[str]]:
    """Validate WCS header completeness for astronomical use.

    Checks required WCS keywords are present and semantically valid.
    Returns (is_valid, list_of_issues).

    A FITS file without valid WCS can still be opened for inspection,
    but should be flagged before entering source detection or coordinate
    transforms that require sky coordinates.
    """
    issues = []
    try:
        from astropy.io import fits
        from astropy.wcs import WCS

        with fits.open(str(filepath), memmap=True) as hdul:
            for hdu in hdul:
                if hdu.data is not None and hdu.is_image:
                    header = hdu.header
                    break
            else:
                return False, ["No image HDU found"]

        # Required WCS keywords (FITS standard §2.1)
        required = {
            "NAXIS": "Number of axes",
            "NAXIS1": "X-axis dimension",
            "NAXIS2": "Y-axis dimension",
            "CTYPE1": "Coordinate type (e.g., 'RA---TAN')",
            "CTYPE2": "Coordinate type (e.g., 'DEC--TAN')",
            "CRPIX1": "Reference pixel X",
            "CRPIX2": "Reference pixel Y",
            "CRVAL1": "Reference value (RA) at CRPIX",
            "CRVAL2": "Reference value (DEC) at CRPIX",
        }

        for keyword, desc in required.items():
            if keyword not in header:
                issues.append(f"Missing {keyword}: {desc}")

        # CD matrix or CDELT
        has_cd = "CD1_1" in header and "CD1_2" in header and "CD2_1" in header and "CD2_2" in header
        has_cdelt = "CDELT1" in header and "CDELT2" in header
        if not has_cd and not has_cdelt:
            issues.append("Missing CD matrix (CD1_1/CD1_2/CD2_1/CD2_2) or CDELT1/CDELT2 for pixel scale")

        # Semantic checks
        if "NAXIS1" in header and header["NAXIS1"] <= 1:
            issues.append(f"NAXIS1={header['NAXIS1']} is too small for astronomical image")
        if "NAXIS2" in header and header["NAXIS2"] <= 1:
            issues.append(f"NAXIS2={header['NAXIS2']} is too small for astronomical image")
        if "CRVAL1" in header and (header["CRVAL1"] < 0 or header["CRVAL1"] > 360):
            issues.append(f"CRVAL1={header['CRVAL1']} is outside valid RA range [0, 360]")

        # Try to construct WCS object (catches non-standard but valid headers)
        if not issues:
            try:
                w = WCS(header)
                if not w.has_celestial:
                    issues.append("WCS has no celestial component (cannot transform pixel ↔ sky)")
            except Exception as e:
                issues.append(f"WCS construction failed: {e}")

        return len(issues) == 0, issues

    except Exception as e:
        return False, [f"WCS validation error: {e}"]

def _check_fits_integrity(filepath: Path) -> None:
    """Raise HTTPException(422) if the file is not a valid FITS binary.

    Checks (v4.16):
      1. Minimum file size (>= 2880 bytes = one FITS block)
      2. Decompression bomb protection (gzip: compressed ratio <= 100:1, max 2 GB)
      3. FITS magic bytes (SIMPLE  =) in the first 80 characters
      4. At least one HDU with image data (via astropy quick-open)
      5. WCS header completeness — flagged but NOT rejected (allows inspection
         of files with broken WCS while warning the user)
    """
    MAX_UNCOMPRESSED = 2 * 1024**3  # 2 GB hard limit on uncompressed FITS data
    MAX_COMPRESSION_RATIO = 100     # reject files compressing more than 100:1

    try:
        size = filepath.stat().st_size
        if size < 2880:
            raise HTTPException(422, f"FITS file too small: {size} bytes (min 2880)")

        # ── Decompression bomb protection ──
        is_gz = filepath.suffix.lower() == '.gz'
        if is_gz:
            # Peek at gzip ISIZE (last 4 bytes = uncompressed size mod 2^32)
            with open(filepath, 'rb') as fh:
                fh.seek(-4, 2)  # last 4 bytes
                isize_bytes = fh.read(4)
                uncompressed_est = int.from_bytes(isize_bytes, 'little')
            if uncompressed_est > MAX_UNCOMPRESSED:
                raise HTTPException(
                    413, f"FITS file too large after decompression: ~{uncompressed_est/1e9:.1f} GB (max 2 GB)")
            if size > 0 and uncompressed_est / size > MAX_COMPRESSION_RATIO:
                raise HTTPException(
                    413, f"Suspicious compression ratio ({uncompressed_est/size:.0f}:1) — possible decompression bomb")
            # Read decompressed header for magic-byte check
            import gzip
            with gzip.open(filepath, 'rb') as gh:
                header_bytes = gh.read(80)
        else:
            with open(filepath, "rb") as fh:
                header_bytes = fh.read(80)

        header_str = header_bytes.decode("ascii", errors="replace")
        if not header_str.startswith("SIMPLE  ="):
            raise HTTPException(
                422,
                f"Not a valid FITS file: missing 'SIMPLE  =' header "
                f"(got: {header_str[:30].strip()})",
            )
        # Quick astropy verify (memmap mode — no full data load)
        from astropy.io import fits
        with fits.open(filepath, memmap=True) as hdul:
            hdul.verify("exception")  # strict: raise on any standard violation
            has_data = any(
                hdu.data is not None and hdu.is_image and hdu.data.size > 0
                for hdu in hdul
            )
            if not has_data:
                raise HTTPException(422, "FITS file contains no image data")

        # ── WCS integrity check (v4.16: flagged, not rejected) ──
        # Performed after basic integrity but does NOT raise on failure.
        # Files with broken WCS can still be opened for visual inspection.
        # The wcs_ok flag is exposed via /pipeline/files?check_integrity=true
        # and /pipeline/file/integrity endpoints.

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(404, "FITS file not found")
    except Exception as e:
        raise HTTPException(422, f"Corrupt or invalid FITS file: {e}")

def _safe_path(filename: str, check_fits: bool = False) -> Path:
    resolved = (FITS_DIR / filename).resolve()
    if not str(resolved).startswith(str(FITS_DIR.resolve())):
        raise HTTPException(403, "Access denied: path traversal detected")
    # Check extension whitelist (skip for directory paths used in listing)
    suf = resolved.suffix.lower()
    if suf and suf not in ALLOWED_EXTENSIONS:
        # Also check double extensions like .fits.gz
        double_suf = ''.join(resolved.suffixes[-2:]).lower() if len(resolved.suffixes) >= 2 else ''
        if double_suf not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Invalid file type: {resolved.suffix} (allowed: .fits, .fit)")
    # Binary integrity check — prevents corrupt FITS from blocking the pipeline
    if check_fits:
        _check_fits_integrity(resolved)
    return resolved

@app.get("/health")
async def health():
    """Deep health check — verifies FITS I/O and cache status, not just port liveness."""
    fits_ok = False
    fits_sample = None
    fits_error = None
    try:
        # Pick first available .fits file for a real read test
        for ext in (".fits", ".fit"):
            candidates = sorted(FITS_DIR.rglob(f"*{ext}"))
            if candidates:
                fits_sample = str(candidates[0].relative_to(FITS_DIR))
                # Quick-open test (memmap — no full data load)
                from astropy.io import fits as afits
                with afits.open(str(candidates[0]), memmap=True) as hdul:
                    hdul.verify("exception")
                    fits_ok = any(hdu.data is not None for hdu in hdul)
                break
    except Exception as e:
        fits_error = str(e)[:200]

    return {
        "status": "ok" if fits_ok else "degraded",
        "fits_dir": str(FITS_DIR),
        "fits_dir_exists": FITS_DIR.exists(),
        "fits_test": {
            "ok": fits_ok,
            "sample": fits_sample,
            "error": fits_error,
        },
        "thread_pool": {
            "max_workers": _HEAVY_WORKERS,
            "cpu_count": _CPU_COUNT,
        },
        "thumbnail_cache": cache_stats(),
    }

@app.get("/pipeline/fits/info")
async def fits_info(filename: str = Query(..., description="FITS filename in data directory")):
    """Get FITS header and WCS metadata."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        loop = asyncio.get_running_loop()
        result = await _run_light(read_fits, str(filepath))
        result.pop("data", None)  # Don't return raw data array
        wcs = await _run_light(wcs_info, str(filepath))
        result["wcs"] = wcs
        return result
    except FITSError as e:
        raise HTTPException(400, str(e))

@app.get("/pipeline/wcs")
async def wcs_query(
    filename: str = Query(...),
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
):
    """Convert sky coordinates to pixel coordinates via WCS."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        return await _run_light(sky_to_pixel, filepath, ra, dec)
    except FITSError as e:
        raise HTTPException(400, str(e))

@app.get("/pipeline/wcs/info")
async def wcs_metadata(filename: str = Query(...)):
    """Get WCS metadata: pixel scale, projection, footprint."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        return await _run_light(wcs_info, filepath)
    except FITSError as e:
        raise HTTPException(400, str(e))

@app.post("/pipeline/cutout")
async def cutout(
    filename: str = Query(...),
    ra: float = Query(..., ge=0, le=360),
    dec: float = Query(..., ge=-90, le=90),
    size_arcmin: float = Query(5.0, ge=0.1, le=60.0),
):
    """Extract a sky-coordinate cutout from a FITS image."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        result = await _run_heavy(filepath, fits_cutout, filepath, ra, dec, size_arcmin)
        result.pop("cutout_data", None)
        result["cutout_data_shape"] = result.get("cutout_shape")
        return result
    except FITSError as e:
        raise HTTPException(400, str(e))

@app.get("/pipeline/sources")
async def source_detection(
    filename: str = Query(...),
    threshold_snr: float = Query(5.0, ge=1.0, le=50.0),
    fwhm_pix: float = Query(3.0, ge=1.0, le=20.0),
):
    """Detect point sources using DAOStarFinder."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        return await _run_heavy(filepath, detect_sources, filepath, threshold_snr, fwhm_pix)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/pipeline/sources/extended")
async def extended_source_detection(
    filename: str = Query(...),
    nsig: float = Query(3.0, ge=1.0, le=20.0),
):
    """Detect extended/blended sources via image segmentation."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        return await _run_heavy(filepath, detect_extended_sources, filepath, nsig)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/pipeline/snr")
async def snr_analysis(filename: str = Query(...), heatmap: bool = Query(False, description="Include base64 PNG heatmap")):
    """Compute SNR map statistics for image quality assessment."""
    filepath = _safe_path(filename, check_fits=True)
    try:
        return await _run_heavy(filepath, compute_snr_map, filepath, heatmap)
    except Exception as e:
        raise HTTPException(400, str(e))

def _quick_check_allzero(filepath: Path) -> bool:
    """Quick-check whether a FITS file contains only zero-valued pixels.

    Uses memory-map for efficiency — only reads the data array header, not full pixels.
    Returns True if all-zero (defective), False if data is valid or cannot verify.
    """
    try:
        from astropy.io import fits
        with fits.open(str(filepath), memmap=True) as hdul:
            for hdu in hdul:
                if hdu.data is not None and hdu.is_image:
                    import numpy as np
                    shape = hdu.data.shape
                    if len(shape) >= 2:
                        # Sample: top-left corner + center block
                        sample = hdu.data[:min(100, shape[0]),
                                          :min(100, shape[1])]
                        cy, cx = shape[0] // 2, shape[1] // 2
                        center = hdu.data[cy:min(cy+5, shape[0]),
                                          cx:min(cx+5, shape[1])]
                        if np.all(sample == 0) and np.all(center == 0):
                            return True
                    return False
    except Exception:
        return False  # cannot verify — don't flag

# ── Band configuration (v4.16) ─────────────────────────────────────
# All configurable bands across surveys. Each band maps to a
# filename pattern for auto-detection.
BAND_CONFIG = {
    # DSS2 optical
    "DSS2-Blue":  {"survey": "DSS2", "wavelength": "optical", "description": "DSS2 Blue plate (IIIaJ)"},
    "DSS2-Green": {"survey": "DSS2", "wavelength": "optical", "description": "DSS2 Green pseudo (IIIaF)"},
    "DSS2-Red":   {"survey": "DSS2", "wavelength": "optical", "description": "DSS2 Red plate (IIIaF+RG610)"},
    # 2MASS near-infrared
    "2MASS-J": {"survey": "2MASS", "wavelength": "near-IR", "description": "2MASS J-band (1.25 μm)"},
    "2MASS-H": {"survey": "2MASS", "wavelength": "near-IR", "description": "2MASS H-band (1.65 μm)"},
    "2MASS-K": {"survey": "2MASS", "wavelength": "near-IR", "description": "2MASS Ks-band (2.16 μm)"},
    # WISE mid-infrared
    "WISE-W1": {"survey": "allWISE", "wavelength": "mid-IR", "description": "WISE W1 (3.4 μm)"},
    "WISE-W2": {"survey": "allWISE", "wavelength": "mid-IR", "description": "WISE W2 (4.6 μm)"},
    "WISE-W4": {"survey": "allWISE", "wavelength": "mid-IR", "description": "WISE W4 (22 μm)"},
    # LEGACY optical
    "LEGACY-g": {"survey": "LEGACY", "wavelength": "optical", "description": "DECaLS/LS g-band"},
    "LEGACY-r": {"survey": "LEGACY", "wavelength": "optical", "description": "DECaLS/LS r-band"},
    "LEGACY-i": {"survey": "LEGACY", "wavelength": "optical", "description": "DECaLS/LS i-band"},
    "LEGACY-z": {"survey": "LEGACY", "wavelength": "optical", "description": "DECaLS/LS z-band"},
    # Radio
    "NVSS-1.4G": {"survey": "NVSS", "wavelength": "radio", "description": "NVSS 1.4 GHz continuum"},
    # CMB
    "AliCPT-150G": {"survey": "AliCPT-1", "wavelength": "mm-wave", "description": "AliCPT 150 GHz"},
    # Planck CMB (v4.31)
    "Planck-030G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 30 GHz"},
    "Planck-044G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 44 GHz"},
    "Planck-070G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 70 GHz"},
    "Planck-100G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 100 GHz"},
    "Planck-143G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 143 GHz"},
    "Planck-217G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 217 GHz"},
    "Planck-353G": {"survey": "Planck", "wavelength": "mm-wave", "description": "Planck 353 GHz"},
}

_SURVEY_ORDER = ["AliCPT-1", "Planck", "DSS2", "2MASS", "allWISE", "LEGACY", "NVSS"]
def _sort_surveys(surveys: set) -> list:
    """Sort surveys by priority: AliCPT-1 first, Planck second, then others."""
    def key(s):
        try: return _SURVEY_ORDER.index(s)
        except ValueError: return 99
    return sorted(surveys, key=key)

def _extract_band(filename: str) -> str | None:
    """Extract band name from a FITS filename using BAND_CONFIG keys.

    Multi-band surveys (2MASS, LEGACY, WISE): band is the last
    underscore-delimited token before .fits/.fit (e.g. '_h.fits' -> h-band).

    Single-band surveys (NVSS, AliCPT): band determined by survey dir alone.

    DSS2: band embedded in filename as 'DSS2-Red', 'DSS2-Blue', etc.
    """
    name = filename.replace(chr(92), '/')
    parts = name.split('/')
    if len(parts) < 2:
        return None
    survey_dir = parts[0]
    fname = parts[-1]
    upper = fname.upper()

    # Extract the last token before extension, stripped of digits
    base = upper.rsplit('.', 1)[0]  # remove .fits/.fit
    last_token = base.rsplit('_', 1)[-1]  # last _ segment

    # Survey → band key lookup table for single-band surveys
    SINGLE_BAND = {
        'NVSS': 'NVSS-1.4G',
        'ALICPT-1': 'AliCPT-150G',
        'PLANCK': 'Planck-143G',
    }

    # Survey → suffix mapping for multi-band surveys
    BAND_SUFFIX = {
        'DSS2':    {'BLUE': 'DSS2-Blue', 'GREEN': 'DSS2-Green', 'RED': 'DSS2-Red'},
        '2MASS':   {'H': '2MASS-H', 'J': '2MASS-J', 'K': '2MASS-K'},
        'ALLWISE': {'W1': 'WISE-W1', 'W2': 'WISE-W2', 'W4': 'WISE-W4'},
        'LEGACY':  {'G': 'LEGACY-g', 'R': 'LEGACY-r', 'I': 'LEGACY-i', 'Z': 'LEGACY-z'},
    }

    survey_key = survey_dir.upper()
    if survey_key in SINGLE_BAND:
        return SINGLE_BAND[survey_key]
    if survey_key in BAND_SUFFIX:
        suffix_map = BAND_SUFFIX[survey_key]
        # Try last_token first, then search full filename
        if last_token in suffix_map:
            return suffix_map[last_token]
        for suffix, band_key in suffix_map.items():
            if suffix in upper:
                return band_key
    return None

@app.get("/pipeline/bands")
async def list_bands():
    """Return all configured bands with survey, wavelength, and description.

    Use this to build frontend band-filter dropdowns and color maps.
    Supports ~15 bands across 6 surveys.
    """
    return {
        "bands": BAND_CONFIG,
        "count": len(BAND_CONFIG),
        "surveys": _sort_surveys(set(b["survey"] for b in BAND_CONFIG.values())),
        "wavelengths": sorted(set(b["wavelength"] for b in BAND_CONFIG.values())),
    }

@app.get("/pipeline/files")
async def list_files(
    survey: str = None,
    band: str = None,
    check_integrity: bool = Query(False,
        description="Quick-check for all-zero defective FITS (e.g., LEGACY export errors)"),
):
    """List available FITS files. Filter by survey and/or band.

    Band filter accepts any configured band key (e.g. 'DSS2-Red', '2MASS-K').
    Use /pipeline/bands to list all available band keys.
    """
    if band and band not in BAND_CONFIG:
        raise HTTPException(400, f"Unknown band '{band}'. Use /pipeline/bands to list valid bands.")
    """List available FITS files in the data directory. Optional survey filter.

    When check_integrity=true, samples each file for all-zero pixel data
    and flags known LEGACY export defects with `defective: true`.
    Frontend should filter/hide defective files from the file browser.
    """
    if survey:
        try:
            _safe_path(survey)
        except HTTPException:
            raise HTTPException(400, "Invalid survey name")
        if any(c in survey for c in ('..', '~')):
            raise HTTPException(400, "Invalid survey name")
    if band and survey and BAND_CONFIG[band]["survey"] != survey:
        raise HTTPException(400, f"Band '{band}' does not belong to survey '{survey}'")
    if not FITS_DIR.exists():
        return {"files": [], "directory": str(FITS_DIR)}

    files = []
    pattern = "**/*.fits" if not survey else f"{survey}/**/*.fits"
    for f in FITS_DIR.glob(pattern):
        rel = f.relative_to(FITS_DIR)
        entry = {"name": str(rel).replace(chr(92), '/'), "size_bytes": f.stat().st_size}
        detected_band = _extract_band(entry["name"])
        if detected_band:
            entry["band"] = detected_band
            entry["wavelength"] = BAND_CONFIG[detected_band]["wavelength"]
        if check_integrity:
            entry["defective"] = _quick_check_allzero(f)
        files.append(entry)
    for f in FITS_DIR.glob(pattern.replace(".fits", ".fit")):
        rel = f.relative_to(FITS_DIR)
        entry = {"name": str(rel).replace(chr(92), '/'), "size_bytes": f.stat().st_size}
        detected_band = _extract_band(entry["name"])
        if detected_band:
            entry["band"] = detected_band
            entry["wavelength"] = BAND_CONFIG[detected_band]["wavelength"]
        if check_integrity:
            entry["defective"] = _quick_check_allzero(f)
        files.append(entry)
    files.sort(key=lambda x: x["name"])
    # Apply band filter (post-glob filter — more flexible than filename glob)
    if band:
        files = [f for f in files if f.get("band") == band]
    surveys = list(set(f["name"].split("/")[0] for f in files if "/" in f["name"]))

    result = {
        "files": files, "surveys": _sort_surveys(surveys),
        "directory": str(FITS_DIR), "count": len(files),
    }
    if check_integrity:
        defective_count = sum(1 for f in files if f.get("defective"))
        result["defective_count"] = defective_count
        result["defective_note"] = (
            "Files flagged 'defective' contain only zero-valued pixels — "
            "likely a LEGACY survey export error. Re-download from "
            "legacysurvey.org/viewer using the RA/Dec in the filename. "
            "See docs/legacy-re-export-sop.md for step-by-step instructions."
        )
    return result

@app.get("/pipeline/file/integrity")
async def check_file_integrity(filename: str = Query(...,
        description="Check if a specific FITS file is all-zero (defective) and validate WCS")):
    """Per-file integrity check: all-zero detection + WCS header validation (v4.16).

    Returns:
      - defective: true if pixel data is all-zero (LEGACY export defect)
      - wcs_ok: true if WCS header is complete for astronomical use
      - wcs_issues: list of specific WCS problems found (empty if wcs_ok)
    """
    filepath = _safe_path(filename)
    if not filepath.exists():
        raise HTTPException(404, f"File not found: {filename}")
    is_defective = _quick_check_allzero(filepath)
    wcs_ok, wcs_issues = _check_wcs_integrity(filepath)
    result = {
        "filename": filename,
        "defective": is_defective,
        "wcs_ok": wcs_ok,
        "wcs_issues": wcs_issues,
    }
    if is_defective:
        result["action"] = "Re-download from legacysurvey.org/viewer — see docs/legacy-re-export-sop.md"
    elif not wcs_ok:
        result["action"] = (
            "WCS header is incomplete or invalid. The file can still be viewed, "
            "but source detection and coordinate transforms may fail. "
            "Consider regenerating with valid WCS using astropy or the original telescope pipeline."
        )
    return result

@app.get("/pipeline/thumbnail")
async def thumbnail(filename: str = Query(...), size: int = Query(200, ge=32, le=1024)):
    """Generate preview PNG from FITS with percentile stretch. Uses disk cache."""
    import io, numpy as np
    from astropy.io import fits
    from PIL import Image as PILImage
    from fastapi.responses import Response

    # --- cache lookup ---
    key = cache_key(filename, size)
    cached = get_cached(key)
    if cached:
        etag = f'"{key}"'
        _log_thumbnail.debug("Cache hit", extra={"file": filename, "size": size})
        return Response(content=cached, media_type='image/png',
                        headers={'X-Cache': 'HIT', 'ETag': etag,
                                 'Cache-Control': 'public, max-age=604800, stale-while-revalidate=86400'})

    # --- generate thumbnail (CPU-bound, rate-limited by semaphore) ---
    # v4.12: semaphore gate — at most N concurrent generations (cache hits bypass)
    await _thumbnail_sem.acquire()
    filepath = _safe_path(filename, check_fits=True)
    if not filepath.exists():
        raise HTTPException(404, f"Not found: {filename}")
    # Use memmap for large files, direct read for small ones
    if filepath.stat().st_size > _THUMBNAIL_MAX_BYTES:
        raise HTTPException(413,
            f"File too large for thumbnail: {filepath.stat().st_size / (1024**2):.0f} MB "
            f"(max {_THUMBNAIL_MAX_MB} MB). Set THUMBNAIL_MAX_FILE_MB env var to adjust.")
    use_memmap = filepath.stat().st_size > 5 * 1024 * 1024  # >5MB
    with fits.open(str(filepath), memmap=use_memmap) as hdul:
        # Try primary HDU first (covers 99% of files), fall back to scan
        data = None
        if hdul[0].data is not None:
            data = hdul[0].data.astype(np.float64)
        else:
            for hdu in hdul:
                if hdu.data is not None:
                    data = hdu.data.astype(np.float64)
                    break
        if data is None:
            raise HTTPException(400, "No image data")
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    # Validate: detect all-zero data (e.g., LEGACY export errors)
    if np.all(data == 0):
        raise HTTPException(422, f"FITS file contains only zero values (possible export error): {filename}")
    # Downsample large images before percentile for speed (stride-2 = 1/4 the points)
    if data.size > 2_000_000:  # > ~1400x1400
        flat = data[::2, ::2]
        flat = flat[flat != 0] if np.any(flat != 0) else flat
    else:
        flat = data[data != 0] if np.any(data != 0) else data
    if len(flat) == 0:
        flat = data.ravel()
    # LEGACY survey has very faint sources — use wider stretch
    is_legacy = 'LEGACY' in filename.upper()
    vmin = np.percentile(flat, 0.5 if is_legacy else 5)
    vmax = np.percentile(flat, 99.5)
    if vmax <= vmin:
        vmax = vmin + 1
    stretched = np.clip((data - vmin) / (vmax - vmin), 0, 1)
    stretched = (stretched * 255).astype(np.uint8)
    img = PILImage.fromarray(stretched)
    # NEAREST is faster than LANCZOS for thumbnail sizes — quality difference negligible at 120px
    resize_filter = PILImage.NEAREST if size <= 200 else PILImage.LANCZOS
    img = img.resize((size, size), resize_filter)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    png_data = buf.getvalue()

    # --- write cache ---
    set_cache(key, png_data)
    _thumbnail_sem.release()

    _log_thumbnail.info("Thumbnail generated (cache MISS)",
                        extra={"file": filename, "size": size,
                               "file_size_mb": round(filepath.stat().st_size / (1024**2), 1)})

    etag = f'"{key}"'
    return Response(content=png_data, media_type='image/png',
                    headers={'X-Cache': 'MISS', 'ETag': etag,
                             'Cache-Control': 'public, max-age=604800, stale-while-revalidate=86400'})

# ── Cache pre-warming ────────────────────────────────────────────────
_warmup_state: dict = {"running": False, "total": 0, "done": 0, "errors": 0}

@app.get("/pipeline/cache/warmup-status")
async def warmup_status():
    """Return the current pre-warming job status."""
    return _warmup_state

@app.post("/pipeline/cache/warmup")
async def warmup_cache(
    size: int = Query(200, ge=32, le=1024),
    max_files: int = Query(0, ge=0, le=5000, description="0 = all files"),
    background: bool = Query(True),
):
    """Pre-warm the thumbnail cache by generating previews for all (or N) FITS files.

    Runs asynchronously via the CPU thread pool so the request returns immediately.
    Use GET /pipeline/cache/warmup-status to track progress.
    """
    import asyncio
    import numpy as np
    from astropy.io import fits
    from PIL import Image as PILImage

    if _warmup_state["running"]:
        return {"status": "already_running", "state": _warmup_state}

    # Collect file list (fast — no I/O inside the thread)
    fits_files: list[str] = []
    for ext in (".fits", ".fit"):
        for fp in FITS_DIR.rglob(f"*{ext}"):
            rel = str(fp.relative_to(FITS_DIR)).replace("\\", "/")
            fits_files.append(rel)
    fits_files.sort()
    total = len(fits_files)
    if max_files > 0 and max_files < total:
        fits_files = fits_files[:max_files]
        total = len(fits_files)

    if total == 0:
        return {"status": "no_files", "fits_dir": str(FITS_DIR)}

    _warmup_state.update({"running": True, "total": total, "done": 0, "errors": 0})

    async def _generate():
        """Generate thumbnails for all collected files, catching per-file errors."""
        loop = asyncio.get_event_loop()
        for i, filename in enumerate(fits_files):
            try:
                key = cache_key(filename, size)
                if get_cached(key) is not None:
                    _warmup_state["done"] += 1
                    continue  # already cached — skip
                filepath = FITS_DIR / filename
                if not filepath.exists() or filepath.stat().st_size < 2880:
                    _warmup_state["errors"] += 1
                    continue
                # Offload CPU-heavy generation to thread pool
                await _run_heavy(Path(filepath), _generate_one, str(filepath), filename, size, key)
                _warmup_state["done"] += 1
            except Exception:
                _warmup_state["errors"] += 1
        _warmup_state["running"] = False

    def _generate_one(filepath: str, filename: str, size: int, key: str):
        """Generate and cache a single thumbnail (runs in thread pool)."""
        import io
        from astropy.io import fits as afits
        from PIL import Image as PILImage_2
        import numpy as np_local

        filepath_p = Path(filepath)
        if filepath_p.stat().st_size > _THUMBNAIL_MAX_BYTES:
            return  # skip files exceeding thumbnail size limit
        use_memmap = filepath_p.stat().st_size > 5 * 1024 * 1024
        with afits.open(filepath, memmap=use_memmap) as hdul:
            data = None
            if hdul[0].data is not None:
                data = hdul[0].data.astype(np_local.float64)
            else:
                for hdu in hdul:
                    if hdu.data is not None:
                        data = hdu.data.astype(np_local.float64)
                        break
            if data is None:
                return
        data = np_local.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        if np_local.all(data == 0):
            return
        if data.size > 2_000_000:
            flat = data[::2, ::2]
            flat = flat[flat != 0] if np_local.any(flat != 0) else flat
        else:
            flat = data[data != 0] if np_local.any(data != 0) else data
        if len(flat) == 0:
            flat = data.ravel()
        is_legacy = 'LEGACY' in filename.upper()
        vmin = np_local.percentile(flat, 0.5 if is_legacy else 5)
        vmax = np_local.percentile(flat, 99.5)
        if vmax <= vmin:
            vmax = vmin + 1
        stretched = np_local.clip((data - vmin) / (vmax - vmin), 0, 1)
        stretched = (stretched * 255).astype(np_local.uint8)
        img = PILImage_2.fromarray(stretched)
        resize_filter = PILImage_2.NEAREST if size <= 200 else PILImage_2.LANCZOS
        img = img.resize((size, size), resize_filter)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        set_cache(key, buf.getvalue())

    if background:
        asyncio.create_task(_generate())
        return {"status": "started", "state": _warmup_state}
    else:
        await _generate()
        return {"status": "complete", "state": _warmup_state}

# ── Async job queue endpoints (v4.12) ────────────────────────────────
from .job_queue import submit_job, get_job, list_jobs, run_job, set_progress, JobStatus, init_queue, job_stats, DB_PATH as _JOB_DB_PATH
from .pipeline_logging import get_logger, log_task

# Structured loggers (v4.16)
_log_thumbnail = get_logger("thumbnail")
_log_sources = get_logger("source_detect")
_log_llm = get_logger("llm")
_log_fits = get_logger("fits_io")

@app.post("/pipeline/jobs/source-detection")
async def submit_source_detection_job(req: SourceDetectionRequest):
    """Submit an async source-detection job. Returns job_id immediately."""
    job = submit_job("source_detection", req.model_dump())
    asyncio.create_task(run_job(job.id, _run_source_detection, timeout=300))
    return {"job_id": job.id, "status": job.status, "type": job.type}

async def _run_source_detection(job):
    set_progress(job.id, 0.1)
    filepath = _safe_path(job.params["filename"], check_fits=True)
    set_progress(job.id, 0.3)
    loop = asyncio.get_running_loop()
    result = await _run_heavy(
        Path(filepath), detect_sources,
        str(filepath), job.params.get("snr_threshold", 5.0), job.params.get("fwhm", 3.0))
    set_progress(job.id, 1.0)
    return result

@app.get("/pipeline/jobs/stats")
async def job_queue_stats():
    """Job queue statistics including persistence status (v4.16)."""
    return job_stats()

@app.get("/pipeline/jobs/{job_id}")
async def query_job(job_id: str):
    """Query job status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "result": job.result if job.status == JobStatus.DONE else None,
        "error": job.error,
        "retries": job.retries,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

@app.get("/pipeline/jobs")
async def list_all_jobs(limit: int = Query(20, ge=1, le=100)):
    """List recent jobs."""
    jobs = list_jobs(limit)
    return {
        "count": len(jobs),
        "jobs": [{
            "job_id": j.id, "type": j.type, "status": j.status,
            "progress": j.progress, "error": j.error, "retries": j.retries,
        } for j in jobs],
    }

@app.get("/pipeline/merge-rgb")
async def merge_rgb(
    r_file: str = Query(None, description="Red channel FITS filename (fits mode)"),
    g_file: str = Query(None, description="Green channel FITS filename (fits mode)"),
    b_file: str = Query(None, description="Blue channel FITS filename (fits mode)"),
    size: int = Query(512, ge=64, le=2048, description="Output image size in pixels"),
    stretch: str = Query("percentile", description="Stretch method: percentile, asinh, log"),
    # R6.7b: per-channel stretch override (defaults to global `stretch`).
    r_stretch: str = Query(None, description="Red channel stretch (overrides stretch)"),
    g_stretch: str = Query(None, description="Green channel stretch (overrides stretch)"),
    b_stretch: str = Query(None, description="Blue channel stretch (overrides stretch)"),
    # R6.7b2: per-channel percentile bounds + gamma correction.
    r_q_low: float = Query(None, description="Red channel lower percentile (overrides q_low)"),
    r_q_high: float = Query(None, description="Red channel upper percentile (overrides q_high)"),
    g_q_low: float = Query(None, description="Green channel lower percentile"),
    g_q_high: float = Query(None, description="Green channel upper percentile"),
    b_q_low: float = Query(None, description="Blue channel lower percentile"),
    b_q_high: float = Query(None, description="Blue channel upper percentile"),
    r_gamma: float = Query(1.0, ge=0.3, le=3.0, description="Red channel gamma correction"),
    g_gamma: float = Query(1.0, ge=0.3, le=3.0, description="Green channel gamma"),
    b_gamma: float = Query(1.0, ge=0.3, le=3.0, description="Blue channel gamma"),
    q_low: float = Query(1.0, ge=0.1, le=20.0, description="Lower percentile for stretch"),
    q_high: float = Query(99.0, ge=80.0, le=99.9, description="Upper percentile for stretch"),
    fmt: str = Query("png", description="Output format: png (raster) or pdf (vector, for publication)"),
    # R6.28: HiPS mode for per-channel RGB cut. When mode='hips', frontend
    # supplies 3 HiPS IDs (e.g. 'allWISE/W4', 'allWISE/W2', 'allWISE/W1') and
    # ra/dec/size, backend fetches raw FITS per channel and applies the same
    # per-channel cut/stretch pipeline. This is what makes RGB composites
    # actually respond to per-channel contrast (DS9 standard behavior).
    mode: str = Query("fits", description="'fits' (local FITS, R6.7b+) or 'hips' (raw FITS from CDS, R6.28+)"),
    r_hips: str = Query(None, description="Red channel HiPS ID, e.g. 'allWISE/W4'"),
    g_hips: str = Query(None, description="Green channel HiPS ID, e.g. 'allWISE/W2'"),
    b_hips: str = Query(None, description="Blue channel HiPS ID, e.g. 'allWISE/W1'"),
    ra: float = Query(None, description="RA in degrees (hips mode)"),
    dec: float = Query(None, description="Dec in degrees (hips mode)"),
    dither: bool = Query(True, description="R6.28: Floyd-Steinberg dither before 8-bit quantize (hips mode)"),
):
    """Merge three FITS files (R/G/B) into a single color image for Aladin/Firefly overlay.

    Each input FITS is independently stretched to [0,255] using the chosen method,
    then combined as R, G, B channels into a 24-bit PNG.

    Modes (R6.28):
      - fits (default): local FITS files (r_file/g_file/b_file). Used by
        /pipeline/merge-rgb for stitched local FITS RGB.
      - hips (R6.28): raw FITS fetched from CDS hips2fits?format=fits per
        channel. Used by frontend Hi-Q mode for per-channel cut (DS9-style).

    Supports DSS2 (Blue/Green/Red), LEGACY (g/r/i or z), 2MASS (j/h/k), allWISE (W1/W2/W4).

    Returns: PNG (raster) or PDF (vector with embedded image) based on fmt parameter.
    """
    import io, numpy as np
    from astropy.io import fits
    from PIL import Image as PILImage
    from fastapi.responses import Response

    # R6.7b: per-channel stretch (overrides global stretch).
    # R6.7b2: per-channel percentile + gamma.
    r_stretch = r_stretch or stretch
    g_stretch = g_stretch or stretch
    b_stretch = b_stretch or stretch
    r_q_low = r_q_low if r_q_low is not None else q_low
    r_q_high = r_q_high if r_q_high is not None else q_high
    g_q_low = g_q_low if g_q_low is not None else q_low
    g_q_high = g_q_high if g_q_high is not None else q_high
    b_q_low = b_q_low if b_q_low is not None else q_low
    b_q_high = b_q_high if b_q_high is not None else q_high

    channels = []
    channel_labels = []
    channel_stretches = {"R": r_stretch, "G": g_stretch, "B": b_stretch}
    channel_q_low = {"R": r_q_low, "G": g_q_low, "B": b_q_low}
    channel_q_high = {"R": r_q_high, "G": g_q_high, "B": b_q_high}
    channel_gamma = {"R": r_gamma, "G": g_gamma, "B": b_gamma}

    # R6.28: HiPS mode — fetch raw FITS from CDS hips2fits?format=fits per channel.
    # Per-channel cut/stretch/dither is applied in float32 space, then composited
    # as RGB PNG. This is the same pipeline as R6.27k's /pipeline/hips-float but
    # composited across 3 channels.
    if mode == "hips":
        if not all([r_hips, g_hips, b_hips, ra is not None, dec is not None]):
            raise HTTPException(400, "hips mode requires r_hips, g_hips, b_hips, ra, dec")
        import io as _io
        from astropy.io import fits as _fits
        from PIL import Image as _PILImage
        import httpx as _httpx

        HIPS_CUTOUT_BASE_HIPS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
        fov = 3 * (size / 400)

        def _fetch_hips_fits(hips_id: str) -> np.ndarray:
            url = f"{HIPS_CUTOUT_BASE_HIPS}?hips={hips_id}&ra={ra}&dec={dec}&fov={fov:.4f}&width={size}&height={size}&stretch=linear&format=fits"
            with _httpx.Client(timeout=30, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
            with _fits.open(_io.BytesIO(r.content)) as hdul:
                data = hdul[0].data
                if data is None:
                    for hdu in hdul:
                        if hdu.data is not None:
                            data = hdu.data
                            break
                if data is None:
                    raise HTTPException(502, f"No image HDU in {hips_id} FITS")
            return np.asarray(data, dtype=np.float32)

        def _process_channel(data: np.ndarray, ch_stretch: str, ch_q_low: float, ch_q_high: float, ch_gamma: float) -> np.ndarray:
            data = np.flipud(data)  # FITS bottom-left → image top-left
            data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
            flat = data.ravel()
            nonzero = flat[flat != 0]
            if len(nonzero) > 0:
                flat = nonzero
            vmin = np.percentile(flat, ch_q_low) if ch_q_low is not None else np.percentile(flat, 1.0)
            vmax = np.percentile(flat, ch_q_high) if ch_q_high is not None else np.percentile(flat, 99.0)
            if vmax <= vmin:
                vmax = vmin + 1
            if ch_stretch == "asinh":
                scale = (vmax - vmin) / 2.0
                scaled = np.arcsinh((data - vmin) / scale) / np.arcsinh(1.0)
                stretched = np.clip(scaled, 0, 1)
            elif ch_stretch == "log":
                scaled = np.clip((data - vmin) / (vmax - vmin), 1e-6, None)
                stretched = np.log10(1 + 999 * scaled) / 3.0
                stretched = np.clip(stretched, 0, 1)
            elif ch_stretch == "sqrt":
                stretched = np.sqrt(np.clip((data - vmin) / (vmax - vmin), 0, 1))
            else:  # linear / percentile
                stretched = np.clip((data - vmin) / (vmax - vmin), 0, 1)
            if ch_gamma != 1.0:
                stretched = np.power(stretched, ch_gamma)

            # Floyd-Steinberg dither (1-LSB error diffusion)
            if dither:
                px = stretched * 255
                h, w = px.shape
                out = np.zeros_like(px, dtype=np.float32)
                for y in range(h):
                    for x in range(w):
                        old = px[y, x]
                        new = round(float(old))
                        out[y, x] = new
                        err = old - new
                        if x + 1 < w:
                            px[y, x + 1] += err * 7 / 16
                        if y + 1 < h:
                            if x > 0:
                                px[y + 1, x - 1] += err * 3 / 16
                            px[y + 1, x] += err * 5 / 16
                            if x + 1 < w:
                                px[y + 1, x + 1] += err * 1 / 16
                return np.clip(out, 0, 255).astype(np.uint8)
            return np.clip(stretched * 255, 0, 255).astype(np.uint8)

        for label, hips_id in [("R", r_hips), ("G", g_hips), ("B", b_hips)]:
            data = _fetch_hips_fits(hips_id)
            ch_stretch = channel_stretches[label]
            ch_q_low = channel_q_low[label] if channel_q_low[label] is not None else 1.0
            ch_q_high = channel_q_high[label] if channel_q_high[label] is not None else 99.0
            ch_gamma = channel_gamma[label]
            ch = _process_channel(data, ch_stretch, ch_q_low, ch_q_high, ch_gamma)
            img = _PILImage.fromarray(ch)
            if img.size != (size, size):
                img = img.resize((size, size), _PILImage.LANCZOS)
            channels.append(np.array(img))
            channel_labels.append(f"{label}={hips_id}")

        rgb = np.stack(channels, axis=-1)
        rgb_img = _PILImage.fromarray(rgb, mode='RGB')
        buf = _io.BytesIO()
        rgb_img.save(buf, format='PNG', optimize=True)
        buf.seek(0)
        out_data = buf.getvalue()
        return Response(
            content=out_data,
            media_type='image/png',
            headers={
                'X-Merge-Mode': 'hips',
                'X-Merge-Channels': ", ".join(channel_labels),
                'X-Merge-Dither': 'true' if dither else 'false',
                'Cache-Control': 'public, max-age=3600',
            },
        )

    for label, filename in [("R", r_file), ("G", g_file), ("B", b_file)]:
        ch_stretch = channel_stretches[label]
        ch_q_low = channel_q_low[label]
        ch_q_high = channel_q_high[label]
        ch_gamma = channel_gamma[label]
        if filename is None:
            raise HTTPException(400, f"{label} channel FITS filename required in fits mode (use mode=hips for CDS HiPS)")
        filepath = _safe_path(filename, check_fits=True)
        if not filepath.exists():
            raise HTTPException(404, f"{label} channel not found: {filename}")

        use_memmap = filepath.stat().st_size > 5 * 1024 * 1024
        with fits.open(str(filepath), memmap=use_memmap) as hdul:
            data = None
            if hdul[0].data is not None:
                data = hdul[0].data.astype(np.float64)
            else:
                for hdu in hdul:
                    if hdu.data is not None:
                        data = hdu.data.astype(np.float64)
                        break
            if data is None:
                raise HTTPException(400, f"No image data in {label} channel: {filename}")

        # FITS uses bottom-left origin; flip vertically for image convention (top-left)
        data = np.flipud(data)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

        # Downsample for percentile calculation
        if data.size > 2_000_000:
            flat = data[::2, ::2]
        else:
            flat = data
        flat = flat.ravel()

        # Remove zeros for better percentile calculation (background often = 0)
        nonzero = flat[flat != 0]
        if len(nonzero) > 0:
            flat = nonzero

        if ch_stretch == "asinh":
            # R6.7b2: per-channel percentile + gamma for rebalancing
            # channels with very different backgrounds (e.g., W4 vs W1).
            vmin = np.percentile(flat, ch_q_low)
            vmax = np.percentile(flat, ch_q_high)
            if vmax <= vmin:
                vmax = vmin + 1
            scale = (vmax - vmin) / 2.0
            scaled = np.arcsinh((data - vmin) / scale) / np.arcsinh(1.0)
            stretched = np.clip(scaled, 0, 1)
            if ch_gamma != 1.0:
                stretched = np.power(stretched, ch_gamma)
        elif ch_stretch == "log":
            vmin = np.percentile(flat, ch_q_low)
            vmax = np.percentile(flat, ch_q_high)
            if vmax <= vmin:
                vmax = vmin + 1
            scaled = (data - vmin) / (vmax - vmin)
            scaled = np.clip(scaled, 1e-6, None)
            stretched = np.log10(1 + 999 * scaled) / 3.0
            stretched = np.clip(stretched, 0, 1)
            if ch_gamma != 1.0:
                stretched = np.power(stretched, ch_gamma)
        else:  # percentile (default, ch_stretch != asinh/log)
            vmin = np.percentile(flat, ch_q_low)
            vmax = np.percentile(flat, ch_q_high)
            if vmax <= vmin:
                vmax = vmin + 1
            stretched = np.clip((data - vmin) / (vmax - vmin), 0, 1)
            if ch_gamma != 1.0:
                stretched = np.power(stretched, ch_gamma)

        stretched = (stretched * 255).astype(np.uint8)
        # Resize to target size using PIL (handles different source dimensions)
        img = PILImage.fromarray(stretched)
        img = img.resize((size, size), PILImage.LANCZOS)
        channels.append(np.array(img))
        channel_labels.append(f"{label}={filename.split('/')[-1].replace('.fits','')[-20:]}")

    # Stack channels into RGB image
    rgb = np.stack(channels, axis=-1)  # (H, W, 3)
    rgb_img = PILImage.fromarray(rgb, mode='RGB')
    buf = io.BytesIO()

    if fmt == "pdf":
        # PDF export for publication — embed high-res image at full resolution
        # Use PIL's native PDF saver (no extra dependencies)
        rgb_img.save(buf, format='PDF', resolution=150.0,
                     title=f'RGB Merge: {", ".join(channel_labels)}',
                     author='GravitationalWave Pipeline')
        media_type = 'application/pdf'
    else:
        rgb_img.save(buf, format='PNG', optimize=True)
        media_type = 'image/png'

    buf.seek(0)
    out_data = buf.getvalue()

    return Response(
        content=out_data,
        media_type=media_type,
        headers={
            'X-Merge-Channels': ", ".join(channel_labels),
            'X-Merge-Stretch': stretch,
            'X-Merge-R-Stretch': r_stretch,
            'X-Merge-G-Stretch': g_stretch,
            'X-Merge-B-Stretch': b_stretch,
            'Cache-Control': 'public, max-age=3600',
        },
    )

# ── DSS2 Auto-Color Fusion ──────────────────────────────────
@app.get("/pipeline/dss2-color")
async def dss2_color(
    ra: float = Query(..., ge=0, le=360, description="Right Ascension in degrees"),
    dec: float = Query(..., ge=-90, le=90, description="Declination in degrees"),
    size: int = Query(512, ge=64, le=2048, description="Output image size in pixels"),
    stretch: str = Query("percentile", description="Stretch method: percentile, asinh, log"),
):
    """Auto-detect DSS2 Blue/Green/Red FITS files by RA/Dec and merge into a single color PNG.

    Searches for DSS2 files matching the given coordinates, automatically pairs
    Blue/Green/Red channels, and returns an RGB composite image.

    This implements the advisor's request: DSS2 three channels fused into one color output.
    """
    import io, re, numpy as np
    from astropy.io import fits
    from PIL import Image as PILImage
    from fastapi.responses import Response

    if not FITS_DIR.exists():
        raise HTTPException(404, "FITS data directory not found")

    dss2_dir = FITS_DIR / "DSS2"
    if not dss2_dir.exists():
        raise HTTPException(404, "No DSS2 survey data found")

    all_dss2 = sorted(list(dss2_dir.glob("*.fits")) + list(dss2_dir.glob("*.fit")))
    if not all_dss2:
        raise HTTPException(404, "No DSS2 FITS files found")

    # Find closest-matching file triplet by RA/Dec proximity
    best_ra = None
    best_dec = None
    best_dist = float('inf')

    for f in all_dss2:
        m = re.match(
            r'Dataset_DSS2_RA_([\d.]+)_Dec_([\d.]+)_FOV_',
            f.name,
        )
        if m:
            fra = float(m.group(1))
            fdec = float(m.group(2))
            dra = min(abs(fra - ra), 360 - abs(fra - ra))
            ddec = abs(fdec - dec)
            dist = (dra ** 2 + ddec ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_ra = fra
                best_dec = fdec

    if best_ra is None:
        raise HTTPException(404, "Could not parse DSS2 filenames for coordinate matching")

    prefix = f"Dataset_DSS2_RA_{best_ra}_Dec_{best_dec}"

    def _find_band(band_suffix: str):
        for f in all_dss2:
            if f.name.startswith(prefix) and band_suffix in f.name:
                return f
        return None

    r_file = _find_band("DSS2-Red")
    g_file = _find_band("DSS2-Green")
    b_file = _find_band("DSS2-Blue")

    if not r_file or not g_file or not b_file:
        missing = []
        if not r_file: missing.append("Red")
        if not g_file: missing.append("Green")
        if not b_file: missing.append("Blue")
        raise HTTPException(
            404,
            f"DSS2 color merge requires all three bands. Missing: {', '.join(missing)}. "
            f"Found {len(all_dss2)} DSS2 files, closest at RA={best_ra}, Dec={best_dec}.",
        )

    # Read and stretch each channel
    channels = []
    channel_labels = []
    for label, filepath in [("R", r_file), ("G", g_file), ("B", b_file)]:
        use_memmap = filepath.stat().st_size > 5 * 1024 * 1024
        with fits.open(str(filepath), memmap=use_memmap) as hdul:
            data = None
            if hdul[0].data is not None:
                data = hdul[0].data.astype(np.float64)
            else:
                for hdu in hdul:
                    if hdu.data is not None:
                        data = hdu.data.astype(np.float64)
                        break
            if data is None:
                raise HTTPException(400, f"No image data in {label} channel")

        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

        if data.size > 2_000_000:
            flat = data[::2, ::2].ravel()
        else:
            flat = data.ravel()
        nonzero = flat[flat != 0]
        if len(nonzero) > 0:
            flat = nonzero

        if stretch == "asinh":
            vmin = np.percentile(flat, 1.0)
            vmax = np.percentile(flat, 99.0)
            if vmax <= vmin:
                vmax = vmin + 1
            scale = (vmax - vmin) / 2.0
            scaled = np.arcsinh((data - vmin) / scale) / np.arcsinh(1.0)
            stretched = np.clip(scaled, 0, 1)
        elif stretch == "log":
            vmin = np.percentile(flat, 1.0)
            vmax = np.percentile(flat, 99.0)
            if vmax <= vmin:
                vmax = vmin + 1
            scaled = (data - vmin) / (vmax - vmin)
            scaled = np.clip(scaled, 1e-6, None)
            stretched = np.log10(1 + 999 * scaled) / 3.0
            stretched = np.clip(stretched, 0, 1)
        else:
            vmin = np.percentile(flat, 1.0)
            vmax = np.percentile(flat, 99.0)
            if vmax <= vmin:
                vmax = vmin + 1
            stretched = np.clip((data - vmin) / (vmax - vmin), 0, 1)

        stretched = (stretched * 255).astype(np.uint8)
        img = PILImage.fromarray(stretched)
        img = img.resize((size, size), PILImage.LANCZOS)
        channels.append(np.array(img))
        channel_labels.append(f"{label}={filepath.name[-30:]}")

    rgb = np.stack(channels, axis=-1)
    rgb_img = PILImage.fromarray(rgb, mode='RGB')
    buf = io.BytesIO()
    rgb_img.save(buf, format='PNG', optimize=True)
    buf.seek(0)

    out_data = buf.getvalue()

    # ── Persistent cache: save to disk for future requests ──
    import hashlib
    cache_key = hashlib.sha256(
        f"dss2-{best_ra:.4f}-{best_dec:.4f}-{size}-{stretch}".encode()
    ).hexdigest()[:16]
    cache_dir = Path(os.getenv("THUMBNAIL_CACHE_DIR", "/app/thumbnail_cache")) / "rgb"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}.png"
    try:
        cache_path.write_bytes(out_data)
    except OSError:
        pass  # best-effort cache write

    return Response(
        content=out_data,
        media_type='image/png',
        headers={
            'X-DSS2-RA': str(best_ra),
            'X-DSS2-Dec': str(best_dec),
            'X-Merge-Channels': ", ".join(channel_labels),
            'X-Merge-Stretch': stretch,
            'ETag': f'"{cache_key}"',
            'Cache-Control': 'public, max-age=86400, stale-while-revalidate=604800',
        },
    )

# ── Batch DSS2 Color Merge (v4.12) ───────────────────────────────────
class BatchDss2Request(BaseModel):
    coordinates: list[dict] = Field(..., min_length=1, max_length=50,
        description="List of {ra, dec} objects")

@app.post("/pipeline/dss2-color-batch")
async def dss2_color_batch(
    req: BatchDss2Request,
    size: int = Query(512, ge=64, le=2048),
    stretch: str = Query("percentile"),
):
    """Submit a batch DSS2 color-merge job. Returns job_id immediately.

    Each {ra, dec} in coordinates is processed asynchronously.
    Use GET /pipeline/jobs/{job_id} to query progress.
    """
    from .job_queue import submit_job, run_job, set_progress, get_job

    job = submit_job("dss2_batch", {
        "coordinates": req.coordinates,
        "size": size,
        "stretch": stretch,
    })

    async def _run_batch(j):
        import io, re, numpy as np
        from astropy.io import fits
        from PIL import Image as PILImage
        coords = j.params["coordinates"]
        total = len(coords)
        results = []
        dss2_dir = FITS_DIR / "DSS2"
        all_files = sorted(list(dss2_dir.glob("*.fits")) + list(dss2_dir.glob("*.fit")))

        for idx, coord in enumerate(coords):
            ra, dec = float(coord["ra"]), float(coord["dec"])
            # Find closest coordinate match
            best_ra, best_dec, best_dist = None, None, float("inf")
            for f in all_files:
                m = re.match(r'Dataset_DSS2_RA_([\d.]+)_Dec_([\d.]+)_FOV_', f.name)
                if m:
                    fra, fdec = float(m.group(1)), float(m.group(2))
                    dra = min(abs(fra - ra), 360 - abs(fra - ra))
                    ddec = abs(fdec - dec)
                    dist = (dra**2 + ddec**2)**0.5
                    if dist < best_dist:
                        best_dist, best_ra, best_dec = dist, fra, fdec
            if best_ra is None:
                results.append({"ra": ra, "dec": dec, "error": "No DSS2 match"})
                continue

            prefix = f"Dataset_DSS2_RA_{best_ra}_Dec_{best_dec}"
            channels = []
            for band in ["DSS2-Red", "DSS2-Green", "DSS2-Blue"]:
                found = None
                for f in all_files:
                    if f.name.startswith(prefix) and band in f.name:
                        found = f; break
                if not found:
                    results.append({"ra": ra, "dec": dec, "error": f"Missing {band}"})
                    channels = []; break
                use_memmap = found.stat().st_size > 5*1024*1024
                with fits.open(str(found), memmap=use_memmap) as hdul:
                    data = hdul[0].data if hdul[0].data is not None else None
                    if data is None:
                        for hdu in hdul:
                            if hdu.data is not None: data = hdu.data.astype(np.float64); break
                data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
                flat = data[::2,::2].ravel() if data.size > 2_000_000 else data.ravel()
                nz = flat[flat != 0]
                if len(nz) > 0: flat = nz
                vmin = np.percentile(flat, 1.0); vmax = np.percentile(flat, 99.0)
                if vmax <= vmin: vmax = vmin + 1
                stretched = (np.clip((data - vmin)/(vmax - vmin), 0, 1) * 255).astype(np.uint8)
                img = PILImage.fromarray(stretched).resize((size, size), PILImage.LANCZOS)
                channels.append(np.array(img))
            if len(channels) == 3:
                rgb = np.stack(channels, axis=-1)
                buf = io.BytesIO()
                PILImage.fromarray(rgb, mode='RGB').save(buf, format='PNG', optimize=True)
                # Save to persistent cache
                import hashlib
                ck = hashlib.sha256(f"dss2-{best_ra:.4f}-{best_dec:.4f}-{size}-{stretch}".encode()).hexdigest()[:16]
                cd = Path(os.getenv("THUMBNAIL_CACHE_DIR", "/app/thumbnail_cache")) / "rgb"
                cd.mkdir(parents=True, exist_ok=True)
                try: (cd / f"{ck}.png").write_bytes(buf.getvalue())
                except OSError: pass
                results.append({"ra": ra, "dec": dec, "matched_ra": best_ra, "matched_dec": best_dec, "ok": True})
            set_progress(j.id, (idx + 1) / total)
        return {"results": results, "total": total}

    asyncio.create_task(run_job(job.id, _run_batch, timeout=600))
    return {"job_id": job.id, "status": job.status, "total": len(req.coordinates)}

@app.get("/pipeline/dss2-color-list")
async def dss2_color_list():
    """List all DSS2 coordinate sets that have complete R/G/B triplets for color merging."""
    import re
    from collections import defaultdict

    if not FITS_DIR.exists():
        raise HTTPException(404, "FITS data directory not found")

    dss2_dir = FITS_DIR / "DSS2"
    if not dss2_dir.exists():
        return {"triplets": [], "count": 0}

    all_dss2 = sorted(list(dss2_dir.glob("*.fits")) + list(dss2_dir.glob("*.fit")))

    groups: dict = defaultdict(dict)
    for f in all_dss2:
        m = re.match(
            r'Dataset_DSS2_RA_([\d.]+)_Dec_([\d.]+)_FOV_([\d.]+)_Width_(\d+)_Height_(\d+)_DSS2-(Red|Green|Blue)\.fits?',
            f.name,
        )
        if m:
            ra_s, dec_s, fov, w, h, band = m.groups()
            key = f"RA={ra_s}_Dec={dec_s}"
            rel = str(f.relative_to(FITS_DIR)).replace('\\', '/')
            groups[key][band] = rel
            groups[key]['_meta'] = {
                'ra': float(ra_s),
                'dec': float(dec_s),
                'fov': float(fov),
                'width': int(w),
                'height': int(h),
            }

    triplets = []
    for key, bands in sorted(groups.items()):
        if 'Red' in bands and 'Green' in bands and 'Blue' in bands:
            triplets.append({
                'ra': bands['_meta']['ra'],
                'dec': bands['_meta']['dec'],
                'fov': bands['_meta']['fov'],
                'r_file': bands['Red'],
                'g_file': bands['Green'],
                'b_file': bands['Blue'],
            })

    return {"triplets": triplets, "count": len(triplets)}

# ── LLM Proxy ──────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_PROXY_URL", "https://api.deepseek.com/v1/chat/completions")
# Auto-fallback: if proxy host is unresolvable (e.g. Linux without host.docker.internal), use direct API
if "host.docker.internal" in DEEPSEEK_API_URL:
    try:
        socket.getaddrinfo("host.docker.internal", 8899)
    except socket.gaierror:
        DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ── AI Agent (v4.33) ─────────────────────────────────────────
from .agent import AgentLoop, AgentConfig, FactVerifier, get_tool_registry as _get_agent_tools
from .agent import _MAX_TOOL_ROUNDS, _TOOL_RESULT_MAX_CHARS, _AGENT_TOTAL_TIMEOUT
from .local_llm import get_local_llm
from .output_guard import scan_output

# v4.35: Audit MongoDB persistence (Fix #6)
from .audit_mongo import (
    write_audit_entry, check_alerts, query_audit_logs,
    get_audit_stats, get_recent_alerts,
)

_agent_loop: "AgentLoop | None" = None

def _get_agent() -> "AgentLoop":
    """Lazy-init the AgentLoop singleton."""
    global _agent_loop
    if _agent_loop is None:
        _agent_loop = AgentLoop()
    return _agent_loop

_LLM_SYSTEM_PROMPT = """You are the GravitationalWave AI Assistant, an expert system for gravitational-wave electromagnetic counterpart astronomy.

Your knowledge domain:
- Multi-band astronomical observations (NVSS, FIRST, WISE, ZTF, DSS2, LEGACY, AliCPT)
- FITS image data and WCS coordinate systems
- Gravitational-wave events (LIGO/Virgo/KAGRA) and their electromagnetic counterparts
- Anomaly detection in astronomical data (spike, dip, pattern-break, WCS-mismatch)
- Source detection algorithms (DAOStarFinder, image segmentation)
- Scientific pipelines for cross-matching and light-curve extraction

You are running on the GravitationalWave platform (v4.10), a 7-container Docker system.
Answer concisely and accurately. Maintain a scientific, professional tone."""

# v4.28: Offline keyword-response system for when DeepSeek API is unavailable.
# Provides basic astronomy-domain responses without any external API call.
_OFFLINE_KEYWORDS = {
    "dss2": "DSS2 (Digitized Sky Survey 2) is a ground-based optical all-sky survey "
            "providing Red, Green, and Blue band images. On this platform, DSS2 data "
            "covers RA 0-360°, Dec -90-+90° at 0.5° FOV resolution. Use the FITS Search "
            "page to query by coordinates, or the DSS2 Color Viewer for RGB composites.",
    "nvss": "NVSS (NRAO VLA Sky Survey) is a 1.4 GHz radio continuum survey covering "
           "the sky north of Dec -40° at 45 arcsec resolution. This platform indexes "
           "NVSS catalog sources with flux densities and positions. Search by RA/Dec "
           "on the FITS Search page.",
    "first": "FIRST (Faint Images of the Radio Sky at Twenty-cm) is a 1.4 GHz radio "
            "survey covering ~10,000 deg². Higher resolution (5 arcsec) than NVSS. "
            "Use radius < 1° for focused searches. Available through FITS Search.",
    "wise": "WISE (Wide-field Infrared Survey Explorer) is a NASA all-sky infrared "
           "survey in 4 bands (W1-W4 at 3.4, 4.6, 12, and 22 μm). This platform "
           "indexes WISE sources with IR photometry. Use for IR counterpart searches.",
    "ztf": "ZTF (Zwicky Transient Facility) is a wide-field optical time-domain survey "
          "using the Palomar 48-inch telescope. Provides g, r, i band photometry. "
          "Useful for transient and variable source identification.",
    "legacy": "The DESI Legacy Imaging Surveys (DECaLS/MzLS/BASS) provide deep optical "
             "imaging in g, r, z bands over ~14,000 deg². This platform's morphology "
             "classifier archetypes are derived from Legacy Survey data.",
    "alicpt": "AliCPT-1 is the first-generation Cosmic Microwave Background telescope "
             "in Ali, Tibet. This platform contains 180 AliCPT-1 FITS cutouts used "
             "for anomaly detection and DL model inference testing.",
    "anomaly": "Anomaly detection on this platform uses two independent methods: "
              "(1) Rule-based classifier detecting spike, dip, pattern-break, and "
              "WCS-mismatch anomalies via sigma-clipping + FFT; (2) CNN autoencoder "
              "detecting anomalies via reconstruction error (z-score). See Error "
              "Analysis page for reports and DL Anomaly Detection for live classification.",
    "morphology": "Galaxy morphology classification uses a Zoobot-style ConvNeXt-Nano "
                 "encoder producing 640-D embeddings, compared to archetype embeddings "
                 "via cosine similarity. Classes: spiral, elliptical, edge-on, merger, "
                 "irregular. Confidence scores are NOT Platt-calibrated.",
    "wcs": "WCS (World Coordinate System) maps pixel coordinates to sky coordinates "
          "(RA/Dec). This platform validates WCS via CRVAL range checks, CD matrix "
          "condition, and pixel scale verification. WCS mismatches are flagged as "
          "anomalies. Use the Pipeline page for WCS queries.",
    "fits": "FITS (Flexible Image Transport System) is the standard astronomical data "
           "format. This platform stores FITS files in /app/data/ and provides cutout, "
           "thumbnail, WCS query, source detection, and photometry endpoints. See "
           "Pipeline page for science tools.",
    "how": "You can search observations by RA/Dec on the FITS Search page, view FITS "
          "images in the Aladin/Firefly viewer (click any search result), check anomaly "
          "reports on the Error Analysis page, classify galaxies with DL models on the "
          "DL Inference page, use the AI Chat for queries, and run science pipelines "
          "(WCS, source detection, photometry) on the Pipeline page.",
    "data": "This platform indexes data from 7 surveys: DSS2 (optical), NVSS (radio), "
           "FIRST (radio), WISE (infrared), ZTF (optical time-domain), LEGACY (deep "
           "optical), and AliCPT-1 (CMB). Total indexed observations: ~200,000. "
           "FITS files: ~2,000. Anomaly reports: ~3,500. Search by RA/Dec or survey name.",
}
_OFFLINE_DEFAULT = (
    "I'm currently in offline mode because the DeepSeek API quota has been exhausted "
    "or the API is unreachable. I can answer basic questions about the GravitationalWave "
    "platform, its surveys (DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, AliCPT), anomaly "
    "detection methods, galaxy morphology classification, WCS coordinates, and FITS "
    "data. Try asking about a specific survey, feature, or how to use the platform. "
    "For real-time AI-powered queries, please wait until the daily quota resets at "
    "midnight UTC, or configure a local LLM via Ollama (see Settings > LLM Configuration)."
)

def _llm_offline_response(user_message: str) -> str:
    """Generate a keyword-based offline response when DeepSeek API is unavailable (v4.28).

    Searches for astronomy-domain keywords in the user's message and returns
    a pre-authored factual response. Falls back to _OFFLINE_DEFAULT if no
    keywords match.

    This provides basic utility even when the platform is completely offline
    or quota-exhausted — the chatbot never shows a raw error to the user.
    """
    msg_lower = user_message.lower()
    matched = []
    for keyword, response in _OFFLINE_KEYWORDS.items():
        if keyword in msg_lower:
            matched.append(response)
    if matched:
        return "\n".join(matched)

@app.post("/pipeline/llm/chat")
async def llm_chat(request: Request):
    """Proxy LLM chat requests to DeepSeek API. API key stays server-side.

    For tool-using agent capabilities, use POST /pipeline/agent/chat instead.
    """
    import re as _re  # v4.26: needed for prompt injection pattern matching
    if not DEEPSEEK_API_KEY:
        return JSONResponse({"error": "LLM not configured"}, status_code=503)

    # Quota check (v4.23)
    quota = _llm_check_quota()
    if not quota["allowed"]:
        # v4.28: Offline fallback — when quota is exhausted, switch to keyword-based
        # astronomy response mode instead of returning a 429 error.
        offline_mode = os.environ.get("LLM_OFFLINE_MODE", "keywords").lower()
        if offline_mode != "none":
            try:
                body = await request.json()
                last_msg = ""
                for m in reversed(body.get("messages", [])):
                    if m.get("role") == "user":
                        last_msg = m.get("content", "")
                        break
                # v4.34: Use local_llm instead of keyword-only
                local_llm = get_local_llm()
                offline_reply = await local_llm.chat([{"role": "user", "content": last_msg}])
                _llm_record_request()
                return {
                    "content": offline_reply,
                    "model": f"offline-{local_llm.status['tier']}-v4.34",
                    "attempts": 1,
                    "quota_remaining": 0,
                    "offline_mode": True,
                    "note": f"LLM quota exhausted — using {local_llm.status['tier']} response. "
                            "Set LLM_OFFLINE_MODE=none to return 429 error instead.",
                }
            except Exception:
                pass
        return JSONResponse({
            "error": f"Daily LLM quota exceeded ({quota['daily_count']}/{quota['quota']}). Resets at midnight UTC.",
            "quota": quota,
        }, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    messages = body.get("messages", [])
    if not messages:
        return JSONResponse({"error": "Missing messages"}, status_code=400)
    verify = body.get("verify", False)  # v4.23: optional output verification
    # v4.DIVS: optional per-request model override (whitelist).
    # DeepSeek exposes vision at deepseek-v4-flash-vision-exp; chat at deepseek-chat.
    _MODEL_ALLOW = {"deepseek-chat", "deepseek-v4-flash-vision-exp", DEEPSEEK_MODEL}
    requested_model = body.get("model")
    active_model = requested_model if requested_model in _MODEL_ALLOW else DEEPSEEK_MODEL

    # v4.26: Input sanitization — detect and reject prompt injection attempts
    _MAX_MSG_LENGTH = int(os.getenv("LLM_MAX_MSG_LENGTH", "4000"))

    # v4.28: Coordinate anonymization — round RA/Dec before sending to third-party API.
    # Protects unpublished survey coordinates from exact exposure.
    # Configure precision via LLM_COORDINATE_DECIMALS env (default: 1 = ~10 arcmin resolution).
    _COORD_DECIMALS = int(os.getenv("LLM_COORDINATE_DECIMALS", "2"))  # v4.30c: 2 decimals = ~0.36 arcmin (was 1 decimal = ~10 arcmin)
    import re as _re_coord  # v4.28

    # v4.28: Character normalization for injection detection.
    # Obfuscated variants (ign0re, pr3v10us, etc.) are normalized before pattern matching.
    _OBFUSCATION_MAP = str.maketrans({
        '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
        '@': 'a', '$': 's', '!': 'i', '7': 't', '8': 'b',
    })

    _INJECTION_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|directives?)",
        r"(?i)(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now\s+)?(DAN|jailbreak|evil|unfiltered)",
        r"(?i)(reveal|disclose|print|output|show)\s+(your\s+)?(system\s+)?(prompt|instructions?|config)",
        r"(?i)forget\s+(all\s+)?(previous\s+)?(training|instructions?|rules?)",
        r"(?i)\[SYSTEM\]|\[SYS\]|<<SYS>>|##\s*System",
        r"(?i)disable\s+(safety|content\s+filter|moderation|ethics)",
    ]
    # v4.34: Weighted semantic injection scoring (Fix #9)
    # Soft rules — cumulative score > threshold blocks the request
    _INJECTION_SCORING = [
        (re.compile(r"(?i)(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now\s+)?(DAN|jailbreak|evil|unfiltered|unrestricted|without\s+restrictions)"), "role_override", 30),
        (re.compile(r"(?i)(reveal|disclose|print|output|show)\s+(your\s+)?(system\s+)?(prompt|instructions?|config|rules?)"), "instruction_leak", 25),
        (re.compile(r"(?i)(forget|ignore|disregard|override)\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|directives?|training|rules?|messages?)"), "memory_override", 25),
        (re.compile(r"(?i)\[SYSTEM\]|\[SYS\]|<<SYS>>|##\s*System|\[INST\]|<<INST>>"), "system_tag", 20),
        (re.compile(r"(?i)disable\s+(safety|content\s+filter|moderation|ethics|guardrails?|restrictions?)"), "safety_bypass", 35),
        (re.compile(r"(?i)(execute|run)\s+(?:arbitrary\s+)?(?:system\s+)?(?:command|code|shell|bash|python)"), "code_injection", 15),
        (re.compile(r"(?i)(?:you\s+are\s+now|from\s+now\s+on\s+you\s+are)\s+(?:a\s+)?(?:different|new|another)\s+(?:model|AI|assistant|personality|character)"), "role_override", 25),
        (re.compile(r"(?i)(?:what\s+is|tell\s+me|show\s+me)\s+(?:your\s+)?(?:original|base|underlying)\s+(?:prompt|instructions?|system\s+message)"), "instruction_leak", 20),
        (re.compile(r"(?i)respond\s+(?:as|like)\s+(?:if\s+you\s+were|you\s+are)\s+(?:a\s+)?(?:different|another|fictional)\s+(?:character|person|entity)"), "role_override", 20),
    ]
    _INJECTION_SCORE_THRESHOLD = int(os.getenv("LLM_INJECTION_SCORE_THRESHOLD", "40"))

    def _score_injection_attempt(text: str, normalized: str) -> int:
        """Score text for prompt injection risk. Returns cumulative score."""
        score = 0
        for pattern, category, weight in _INJECTION_SCORING:
            if pattern.search(text) or pattern.search(normalized):
                score += weight
                _log_llm.info("Injection score +%d from category '%s'", weight, category)
                if score >= _INJECTION_SCORE_THRESHOLD:
                    break
        return score

    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if isinstance(content, str):
            # v4.28: Coordinate anonymization — round RA/Dec to configured precision
            # Matches patterns like "RA=123.456789" or "Dec=-45.123456" or "123.456, -45.123"
            content = _re_coord.sub(
                r'(RA\s*[=:]\s*|ra\s*[=:]\s*|Dec\s*[=:]\s*|dec\s*[=:]\s*)(\d+\.\d+)',
                lambda m: f"{m.group(1)}{round(float(m.group(2)), _COORD_DECIMALS)}",
                content
            )
            # Also round standalone coordinate pairs: "123.456789, -45.123456"
            content = _re_coord.sub(
                r'(\d{1,3}\.\d{4,})\s*,\s*(-?\d{1,2}\.\d{4,})',
                lambda m: f"{round(float(m.group(1)), _COORD_DECIMALS)}, {round(float(m.group(2)), _COORD_DECIMALS)}",
                content
            )

            # Check message length
            if len(content) > _MAX_MSG_LENGTH:
                return JSONResponse({
                    "error": f"Message {i} exceeds max length ({len(content)} > {_MAX_MSG_LENGTH} chars)",
                }, status_code=400)
            # v4.28: Normalize obfuscated characters before pattern matching
            normalized = content.translate(_OBFUSCATION_MAP)
            # Check for prompt injection patterns (against both original and normalized)
            for pattern in _INJECTION_PATTERNS:
                if _re.search(pattern, content) or _re.search(pattern, normalized):
                    _log_llm.warning("Prompt injection pattern detected in message %d: %s", i, pattern)
                    return JSONResponse({
                        "error": "Message contains content that violates safety policy. "
                                 "Please rephrase your query without attempting to override system instructions.",
                    }, status_code=400)

    has_system = any(m.get("role") == "system" for m in messages)
    payload = messages if has_system else [{"role": "system", "content": _LLM_SYSTEM_PROMPT}] + messages

    # Adaptive timeout: separate connect/read/total timeouts
    # All configurable via env: LLM_CONNECT_TIMEOUT_SEC / LLM_READ_TIMEOUT_SEC / LLM_TOTAL_TIMEOUT_SEC
    import asyncio as _asyncio
    import time as _time

    last_error = None
    t_start = _time.monotonic()
    for attempt in range(1 + _LLM_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=_LLM_CONNECT_TIMEOUT,
                    read=_LLM_READ_TIMEOUT,
                    write=30.0,
                    pool=10.0,
                ),
            ) as client:
                resp = await client.post(
                    DEEPSEEK_API_URL,
                    json={
                        "model": active_model,
                        "messages": payload,
                        "temperature": 0.5,
                        "max_tokens": 800,
                        "stream": False,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    },
                )

            if resp.status_code == 401:
                return JSONResponse({"error": "LLM auth failed"}, status_code=502)
            if resp.status_code == 429:
                if attempt < _LLM_MAX_RETRIES:
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    await _asyncio.sleep(retry_after)
                    continue
                return JSONResponse({"error": "LLM rate limited"}, status_code=429)

            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return JSONResponse({"error": "Empty LLM response"}, status_code=502)

            content_text = choices[0].get("message", {}).get("content", "")
            _llm_record_request()  # v4.23: track usage

            # v4.23: Optional output verification
            verify_note = None
            if verify:
                verify_note = await _verify_llm_output(content_text)

            _log_llm.info("LLM chat completed",
                          extra={"model": DEEPSEEK_MODEL, "attempts": attempt + 1,
                                 "tokens_estimate": len(content_text) // 4,
                                 "duration_ms": round((_time.monotonic() - t_start) * 1000, 1)})
            result = {"content": content_text, "model": active_model, "attempts": attempt + 1,
                       "quota_remaining": _llm_check_quota()["remaining"]}
            if verify_note:
                result["verify_note"] = verify_note
            return result

        except httpx.ConnectTimeout:
            last_error = f"Connection timeout after {_LLM_CONNECT_TIMEOUT}s"
            break
        except httpx.ReadTimeout:
            last_error = f"Read timeout after {_LLM_READ_TIMEOUT}s"
            if attempt >= _LLM_MAX_RETRIES:
                break
            await _asyncio.sleep(2 ** attempt)
        except httpx.TimeoutException:
            last_error = f"Total timeout after {_LLM_TOTAL_TIMEOUT}s"
            break
        except Exception as e:
            last_error = str(e)[:200]
            if attempt >= _LLM_MAX_RETRIES:
                break
            await _asyncio.sleep(2 ** attempt)

    return JSONResponse({"error": f"LLM error: {last_error}"}, status_code=502)

# ═══════════════════════════════════════════════════════════════════════════
# AI Agent Endpoints (v4.33) — ReAct Agent with tool-use capabilities
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/pipeline/agent/chat")
async def agent_chat(request: Request):
    """AI Agent chat — DeepSeek with function-calling tool use.

    Upgrades the LLM chat to an autonomous agent that can:
    - Query databases (observations, errors, comments)
    - Analyze FITS files (headers, statistics, WCS)
    - Run DL inference (morphology, source type, anomaly detection)
    - Check system health and pipeline status

    Request body: {"messages": [{"role": "user", "content": "..."}]}
    Response: AgentResult.to_dict() with steps, tool_calls, final response.

    The agent loop:
      1. Send user message + tools to DeepSeek
      2. DeepSeek decides: respond directly OR call a tool
      3. If tool call: execute tool, send result back, repeat
      4. Return final response with full step trace
    """
    if not DEEPSEEK_API_KEY:
        return JSONResponse({"error": "DeepSeek API key not configured", "success": False}, status_code=503)

    # v4.34: Extract session ID for per-user quota
    session_id = None
    try:
        session_id = request.headers.get("X-Session-ID")
    except Exception:
        pass

    # Quota check
    user_id = getattr(request.state, 'user', {}).get('userId', None) if hasattr(request.state, 'user') else None
    quota = _llm_check_quota(session_id, user_id)
    if not quota["allowed"]:
        offline_mode = os.environ.get("LLM_OFFLINE_MODE", "keywords").lower()
        if offline_mode != "none":
            try:
                body = await request.json()
                last_msg = ""
                for m in reversed(body.get("messages", [])):
                    if m.get("role") == "user":
                        last_msg = m.get("content", "")
                        break
                # v4.34: Try local LLM first, fall back to keyword
                local_llm = get_local_llm()
                offline_reply = await local_llm.chat([{"role": "user", "content": last_msg}])
                _llm_record_request()
                return {
                    "success": True, "content": offline_reply,
                    "model": f"offline-{local_llm.status['tier']}-v4.34",
                    "total_rounds": 1, "tool_calls_count": 0, "steps": [],
                    "note": f"LLM quota exhausted — using {local_llm.status['tier']} response.",
                }
            except Exception:
                pass
        return JSONResponse({
            "error": f"Daily LLM quota exceeded ({quota['daily_count']}/{quota['quota']})",
            "success": False, "quota": quota,
        }, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body", "success": False}, status_code=400)

    messages = body.get("messages", [])
    if not messages:
        return JSONResponse({"error": "Missing messages", "success": False}, status_code=400)

    # Input sanitization (same as llm_chat)
    _MAX_MSG_LENGTH = int(os.getenv("LLM_MAX_MSG_LENGTH", "4000"))
    import re as _re_agent

    # v4.34: Coordinate rounding (was missing from agent endpoint — Fix #4)
    _COORD_DECIMALS = int(os.getenv("LLM_COORDINATE_DECIMALS", "2"))
    import re as _re_coord_agent
    _OBFUSCATION_MAP_AGENT = str.maketrans({
        '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
        '@': 'a', '$': 's', '!': 'i', '7': 't', '8': 'b',
    })

    for i, msg in enumerate(messages):
        content_text = msg.get("content", "")
        if isinstance(content_text, str):
            # v4.34: Coordinate anonymization before sending to 3rd party
            content_text = _re_coord_agent.sub(
                r'(RA\s*[=:]\s*|ra\s*[=:]\s*|Dec\s*[=:]\s*|dec\s*[=:]\s*)(\d+\.\d+)',
                lambda m: f"{m.group(1)}{round(float(m.group(2)), _COORD_DECIMALS)}",
                content_text
            )
            content_text = _re_coord_agent.sub(
                r'(\d{1,3}\.\d{4,})\s*,\s*(-?\d{1,2}\.\d{4,})',
                lambda m: f"{round(float(m.group(1)), _COORD_DECIMALS)}, {round(float(m.group(2)), _COORD_DECIMALS)}",
                content_text
            )
            msg["content"] = content_text

            if len(content_text) > _MAX_MSG_LENGTH:
                return JSONResponse({
                    "error": f"Message {i} exceeds max length ({len(content_text)} > {_MAX_MSG_LENGTH})",
                    "success": False,
                }, status_code=400)
            # Check hard injection patterns
            for pattern in _INJECTION_PATTERNS:
                if _re_agent.search(pattern, content_text):
                    return JSONResponse({
                        "error": "Message contains content that violates safety policy.",
                        "success": False,
                    }, status_code=400)
            # v4.34: Soft injection scoring
            normalized = content_text.translate(_OBFUSCATION_MAP_AGENT)
            inj_score = _score_injection_attempt(content_text, normalized)
            if inj_score >= _INJECTION_SCORE_THRESHOLD:
                _log_llm.warning("Agent request blocked: injection score %d", inj_score)
                return JSONResponse({
                    "error": f"Message flagged by safety system (risk score: {inj_score}). "
                             "Please rephrase without system instruction patterns.",
                    "success": False,
                }, status_code=400)

    # Config from env/request
    max_rounds = int(body.get("max_tool_rounds", os.getenv("AGENT_MAX_TOOL_ROUNDS", "10")))
    cfg = AgentConfig(
        max_tool_rounds=max_rounds,
        temperature=float(body.get("temperature", 0.3)),
        max_tokens=int(body.get("max_tokens", 1500)),
    )

    # Run agent loop
    agent = _get_agent()
    _log_llm.info("Agent chat started — messages=%d, tools=%d",
                  len(messages), agent.registry.tool_count)

    # v4.34: Compliance audit logging
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")[:200]
            break
    sensitive = _detect_sensitive_coordinates(last_user_msg)
    _audit_compliance_log(last_user_msg, session_id, "agent_chat",
                          extra={"sensitive_coords_detected": len(sensitive) if sensitive else 0})

    result = await agent.run(messages, config=cfg)
    _llm_record_request(session_id, user_id)

    result_dict = result.to_dict()
    result_dict["quota_remaining"] = _llm_check_quota(session_id)["remaining"]
    result_dict["available_tools"] = agent.available_tools

    # v4.34: Output guard (Fix #10)
    if result.success and result.final_response:
        guard_result = await scan_output(result.final_response)
        result_dict["content_safety"] = {
            "safe": guard_result["safe"],
            "score": guard_result["score"],
            "flags": guard_result["flags"],
        }
        if not guard_result["safe"]:
            _log_llm.warning("Output guard flagged agent response: score=%d, flags=%d",
                           guard_result["score"], len(guard_result["flags"]))

    _log_llm.info("Agent chat completed — success=%s, rounds=%d, tool_calls=%d, time=%.0fms",
                  result.success, result.total_rounds, result.tool_calls_count, result.total_time_ms)

    return result_dict

@app.post("/pipeline/agent/chat/stream")
async def agent_chat_stream(request: Request):
    """v4.34: Streaming AI Agent chat with SSE progress events.

    Sends Server-Sent Events:
      - thinking: agent is reasoning about next action
      - tool_call: agent called a tool (name + args)
      - tool_result: tool execution completed (success + elapsed)
      - verification: fact-checking results
      - done: final response with full AgentResult
      - error: error message

    Consume with EventSource or fetch + ReadableStream.
    """
    if not DEEPSEEK_API_KEY:
        return JSONResponse({"error": "DeepSeek API key not configured", "success": False}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body", "success": False}, status_code=400)

    messages = body.get("messages", [])
    if not messages:
        return JSONResponse({"error": "Missing messages", "success": False}, status_code=400)

    # v4.34: Session quota check
    session_id = None
    try:
        session_id = request.headers.get("X-Session-ID")
    except Exception:
        pass

    user_id = getattr(request.state, 'user', {}).get('userId', None) if hasattr(request.state, 'user') else None
    quota = _llm_check_quota(session_id, user_id)
    if not quota["allowed"]:
        return JSONResponse({
            "error": f"Daily LLM quota exceeded ({quota['daily_count']}/{quota['quota']})",
            "success": False,
        }, status_code=429)

    # Input sanitization (same as agent_chat)
    _MAX_MSG_LENGTH = int(os.getenv("LLM_MAX_MSG_LENGTH", "4000"))
    for i, msg in enumerate(messages):
        content_text = msg.get("content", "")
        if isinstance(content_text, str) and len(content_text) > _MAX_MSG_LENGTH:
            return JSONResponse({
                "error": f"Message {i} exceeds max length ({len(content_text)} > {_MAX_MSG_LENGTH})",
                "success": False,
            }, status_code=400)

    max_rounds = int(body.get("max_tool_rounds", os.getenv("AGENT_MAX_TOOL_ROUNDS", "10")))
    cfg = AgentConfig(
        max_tool_rounds=max_rounds,
        temperature=float(body.get("temperature", 0.3)),
        max_tokens=int(body.get("max_tokens", 1500)),
    )

    agent = _get_agent()

    async def event_generator():
        # v4.35: SSE heartbeat keep-alive (Fix #4)
        # Sends ": heartbeat" comment every 15s to prevent proxy timeout
        _HEARTBEAT_INTERVAL = float(os.getenv("SSE_HEARTBEAT_SEC", "15.0"))
        queue = asyncio.Queue()
        _stop_heartbeat = asyncio.Event()

        async def _agent_producer():
            try:
                async for event in agent.run_streaming(messages, config=cfg):
                    await queue.put(f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
            except Exception as e:
                await queue.put(f"event: error\ndata: {json.dumps({'message': str(e)[:200]}, ensure_ascii=False)}\n\n")
            finally:
                _llm_record_request(session_id, user_id)
                _stop_heartbeat.set()
                await queue.put(None)  # sentinel

        async def _heartbeat_producer():
            while not _stop_heartbeat.is_set():
                try:
                    await asyncio.wait_for(_stop_heartbeat.wait(), timeout=_HEARTBEAT_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    await queue.put(": heartbeat\n\n")

        agent_task = asyncio.create_task(_agent_producer())
        heartbeat_task = asyncio.create_task(_heartbeat_producer())

        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                yield msg
        finally:
            _stop_heartbeat.set()
            heartbeat_task.cancel()
            agent_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Quota-Remaining": str(quota.get("remaining", 0)),
        },
    )

@app.get("/pipeline/agent/status")
async def agent_status():
    """Get AI Agent configuration and availability status."""
    agent = _get_agent()
    quota = _llm_check_quota()
    # v4.34: Get model info for version tracking
    try:
        from .agent import get_model_info
        model_info = get_model_info()
    except ImportError:
        model_info = {}

    local_llm = get_local_llm()
    return {
        "version": "v4.35",
        "configured": agent.is_configured,
        "model": DEEPSEEK_MODEL,
        "api_url": DEEPSEEK_API_URL.split("?")[0],
        "available_tools": agent.available_tools,
        "tool_count": agent.registry.tool_count,
        "quota": {
            "daily_limit": quota["quota"],
            "daily_used": quota["daily_count"],
            "daily_remaining": quota["remaining"],
            "allowed": quota["allowed"],
        },
        "config": {
            "max_tool_rounds": _MAX_TOOL_ROUNDS,
            "tool_result_max_chars": _TOOL_RESULT_MAX_CHARS,
            "total_timeout_sec": _AGENT_TOTAL_TIMEOUT,
        },
        "compliance": {
            "level": _COMPLIANCE_LEVEL,
            "coordinate_decimals": int(os.getenv("LLM_COORDINATE_DECIMALS", "2")),
        },
        "local_llm": local_llm.status,
        "model_tracking": model_info,
        # v4.35: Tool cache stats (Fix #2)
        "tool_cache": agent.registry.cache_stats if hasattr(agent.registry, 'cache_stats') else {},
    }

# ═══════════════════════════════════════════════════════════════════════════
# v4.35: Admin Audit Endpoints (Fix #6) — RBAC-protected (admin only)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/pipeline/admin/audit/logs")
async def admin_audit_logs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: str = None,
    level: str = None,
    user_role: str = None,
):
    """Query audit logs with pagination and filters. Admin only."""
    result = await query_audit_logs(
        page=page, page_size=min(page_size, 100),
        action=action, level=level, user_role=user_role,
    )
    return result

@app.get("/pipeline/admin/audit/stats")
async def admin_audit_stats(request: Request):
    """Get audit statistics summary. Admin only."""
    return await get_audit_stats()

@app.get("/pipeline/admin/audit/alerts")
async def admin_audit_alerts(request: Request, limit: int = 20):
    """Get recent audit alerts. Admin only."""
    alerts = await get_recent_alerts(min(limit, 100))
    return {"success": True, "alerts": alerts, "count": len(alerts)}

@app.get("/pipeline/admin/quota/users")
async def admin_quota_users(request: Request):
    """Get per-session quota usage. Admin only."""
    result = {}
    for sid, count in _SESSION_QUOTAS.items():
        result[sid[:16]] = {
            "count": count,
            "limit": _SESSION_QUOTA_LIMIT,
            "remaining": max(0, _SESSION_QUOTA_LIMIT - count),
            "percent": round(count / max(1, _SESSION_QUOTA_LIMIT) * 100, 1),
        }
    return {
        "success": True,
        "active_sessions": len(_SESSION_QUOTAS),
        "global_daily_count": _llm_daily_count,
        "global_daily_quota": _LLM_DAILY_QUOTA,
        "sessions": dict(sorted(result.items(), key=lambda x: x[1]["count"], reverse=True)[:50]),
    }

@app.get("/pipeline/agent/tools")
async def agent_tools():
    """List all tools available to the AI Agent with their schemas."""
    agent = _get_agent()
    schemas = agent.registry.get_schemas()
    return {
        "version": "v4.35",
        "tool_count": len(schemas),
        "tools": [
            {
                "name": s["function"]["name"],
                "description": s["function"]["description"],
                "parameters": s["function"]["parameters"],
            }
            for s in schemas
        ],
    }

async def _verify_llm_output(content_text: str):
    """v4.23: Verify numerical claims in LLM output against ES/MCP data.

    Extracts claims about observation counts and cross-checks with
    the MCP server or ES API. Returns a verification note string
    if discrepancies are found, or None if all claims check out.
    """
    import re
    notes = []
    try:
        # Check observation count claims
        count_match = re.search(r'(\d+)\s*(?:total\s*)?(?:observations|records?|entries?|FITS files?)', content_text, re.IGNORECASE)
        if count_match:
            claimed = int(count_match.group(1))
            # Query ES via the files endpoint to get actual count
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get("http://localhost:8200/pipeline/files")
                    if resp.status_code == 200:
                        actual = resp.json().get("count", 0)
                        if abs(claimed - actual) / max(actual, 1) > 0.2:
                            notes.append(f"Claimed {claimed} observations, but platform has {actual}. "
                                        f"Difference: {abs(claimed - actual)} ({abs(claimed - actual)/max(actual,1)*100:.0f}%)")
            except Exception:
                pass  # Verification best-effort; don't block response

        # Check anomaly count claims
        anomaly_match = re.search(r'(\d+)\s*(?:total\s*)?(?:anomalies|errors?\s*reports?)', content_text, re.IGNORECASE)
        if anomaly_match:
            claimed = int(anomaly_match.group(1))
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get("http://localhost:8200/pipeline/errors/count")
                    if resp.status_code == 200:
                        actual = resp.json().get("count", 0)
                        if abs(claimed - actual) > max(actual * 0.2, 2):
                            notes.append(f"Claimed {claimed} anomalies, but platform has {actual}. "
                                        f"Difference: {abs(claimed - actual)}")
            except Exception:
                pass
    except Exception:
        pass

    if notes:
        return " | ".join(notes)
    return None

@app.get("/pipeline/llm/usage")
async def llm_usage():
    """v4.23: Return LLM quota usage statistics (no key exposure)."""
    quota = _llm_check_quota()
    return {
        "configured": bool(DEEPSEEK_API_KEY),
        "model": DEEPSEEK_MODEL,
        "quota": {
            "daily_limit": quota["quota"],
            "daily_used": quota["daily_count"],
            "daily_remaining": quota["remaining"],
            "pct_used": round(quota["daily_count"] / max(quota["quota"], 1) * 100, 1),
        },
    }

@app.get("/pipeline/llm/status")
async def llm_status():
    """Return LLM API configuration status (no key exposure)."""
    quota = _llm_check_quota()
    return {
        "configured": bool(DEEPSEEK_API_KEY),
        "model": DEEPSEEK_MODEL,
        "provider": "third-party (DeepSeek API)",
        "local_fallback": {
            "available": False,
            "status": "not_deployed",
            "recommended": "Ollama + Qwen2.5-7B / Llama-3.1-8B on gw-pipeline container",
            "note": (
                "No local LLM deployed. When DeepSeek API is unreachable or quota exhausted, "
                "AI chat is completely unavailable. A local model would provide offline "
                "availability, data sovereignty (no coordinates sent to third-party), "
                "and no quota limits."
            ),
        },
        "data_privacy": {
            "coordinates_sent_to_third_party": True,
            "anonymization": "none — raw RA/Dec/FITS filenames sent to DeepSeek API",
            "retention_policy": "governed by DeepSeek API terms of service",
            "compliance_note": (
                "All chat content including astronomical coordinates is transmitted "
                "in plaintext to DeepSeek API servers. No data anonymization applied. "
                "Users should NOT include coordinates from unpublished surveys."
            ),
        },
        "input_sanitization": {
            "enabled": True,
            "max_message_length": 4000,
            "injection_patterns_blocked": 6,
            "obfuscation_normalization": True,
            "note": "v4.28: Obfuscated characters (ign0re→ignore) normalized before matching. "
                    "Coordinate precision rounded to configured decimals before sending.",
        },
        "coordinate_anonymization": {
            "enabled": True,
            "decimal_places": int(os.getenv("LLM_COORDINATE_DECIMALS", "1")),
            "note": f"RA/Dec coordinates rounded to {os.getenv('LLM_COORDINATE_DECIMALS', '1')} decimal(s) before API transmission",
        },
        "offline_fallback": {
            "mode": os.environ.get("LLM_OFFLINE_MODE", "keywords"),
            "keywords_available": len(_OFFLINE_KEYWORDS) if '_OFFLINE_KEYWORDS' in dir() else 14,
            "note": "When quota exhausted, switches to keyword-based astronomy responses instead of 429 error",
        },
        "timeouts": {
            "connect_sec": _LLM_CONNECT_TIMEOUT,
            "read_sec": _LLM_READ_TIMEOUT,
            "total_sec": _LLM_TOTAL_TIMEOUT,
            "max_retries": _LLM_MAX_RETRIES,
        },
        "quota_remaining": quota["remaining"],
        "quota_total": quota["quota"],
    }

@app.post("/pipeline/sources")
async def detect_sources_post(request: SourceDetectionRequest):
    """Detect sources via POST with JSON body. Async: detect_sources runs in thread pool."""
    filepath = _safe_path(request.filename)
    if not filepath.exists():
        raise HTTPException(404, f"Not found: {request.filename}")

    loop = asyncio.get_running_loop()
    try:
        result = await _run_heavy(
            filepath,
            detect_sources,
            str(filepath),
            request.snr_threshold,
            request.fwhm,
        )
        return result
    except Exception as e:
        raise HTTPException(400, str(e))

# ── Photometry endpoint for data comparison (v4.13) ──────────────────
from pydantic import BaseModel as PydanticBase

class PhotometryRequest(PydanticBase):
    filenames: list[str] = Field(..., min_length=1, max_length=100,
        description="List of FITS filenames to extract photometry from")

def _extract_photometry(filepath_str: str) -> dict:
    """Extract flux statistics from a single FITS file for comparison."""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS

    filepath = Path(filepath_str)
    use_memmap = filepath.stat().st_size > 5 * 1024 * 1024
    with fits.open(filepath_str, memmap=use_memmap) as hdul:
        data = None
        header = None
        if hdul[0].data is not None:
            data = hdul[0].data.astype(np.float64)
            header = hdul[0].header
        else:
            for hdu in hdul:
                if hdu.data is not None:
                    data = hdu.data.astype(np.float64)
                    header = hdu.header
                    break
        if data is None:
            return {"error": "No image data", "filename": filepath.name}

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    nonzero = data[data != 0]

    # ── Global statistics ──
    stats = {
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "mean": float(np.mean(data)),
        "median": float(np.median(data)),
        "std": float(np.std(data)),
    }
    if len(nonzero) > 0:
        stats["nonzero_mean"] = float(np.mean(nonzero))
        stats["nonzero_median"] = float(np.median(nonzero))
        stats["nonzero_std"] = float(np.std(nonzero))
        stats["nonzero_fraction"] = round(len(nonzero) / data.size, 4)

    # ── Aperture photometry (central 10% radius) ──
    h, w = data.shape
    cy, cx = h // 2, w // 2
    radius = int(min(h, w) * 0.1)
    y_indices, x_indices = np.ogrid[:h, :w]
    mask = (y_indices - cy) ** 2 + (x_indices - cx) ** 2 <= radius ** 2
    aperture_flux = float(np.sum(data[mask]))
    aperture_pixels = int(np.sum(mask))

    # ── WCS info ──
    wcs_info = {}
    try:
        w = WCS(header)
        wcs_info["projection"] = str(w.wcs.ctype[0]) if w.wcs.ctype else ""
        wcs_info["pixel_scale"] = float(np.sqrt(w.proj_plane_pixel_scales()[0].value * 3600)) if not w.is_celestial_off() else None
    except Exception:
        pass

    return {
        "filename": filepath.name,
        "shape": list(data.shape),
        "stats": stats,
        "aperture": {
            "center": [cx, cy],
            "radius_px": radius,
            "flux": aperture_flux,
            "pixels": aperture_pixels,
            "flux_per_pixel": aperture_flux / aperture_pixels if aperture_pixels > 0 else 0,
        },
        "wcs": wcs_info,
    }

# -- Anomaly Classify request model (v4.32) --

class AnomalyClassifyRequest(PydanticBase):
    filename: str = Field(..., min_length=1, description="FITS filename relative to FITS_DIR")
    ra: Optional[float] = Field(None, description="RA in degrees (optional, for context)")
    dec: Optional[float] = Field(None, description="Dec in degrees (optional, for context)")
    size_arcmin: float = Field(5.0, ge=0.5, le=60.0, description="Cutout size in arcmin")
    spike_sigma: float = Field(5.0, ge=1.0, le=20.0, description="Spike detection threshold (sigma)")
    dip_sigma: float = Field(5.0, ge=1.0, le=20.0, description="Dip detection threshold (sigma)")
    pattern_break_sigma: float = Field(4.0, ge=1.0, le=20.0, description="Pattern-break detection threshold (sigma)")
    window_size: int = Field(64, ge=16, le=256, description="Sliding window size for local statistics")

def _classify_single(filepath_str: str, spike_sigma: float, dip_sigma: float,
                     pattern_break_sigma: float, window_size: int) -> dict:
    """Run all four anomaly detectors on a single FITS file."""
    import numpy as np
    from astropy.io import fits

    filepath = Path(filepath_str)
    use_memmap = filepath.stat().st_size > 5 * 1024 * 1024
    with fits.open(filepath_str, memmap=use_memmap) as hdul:
        data = None
        if hdul[0].data is not None:
            data = hdul[0].data.astype(np.float64)
        else:
            for hdu in hdul:
                if hdu.data is not None:
                    data = hdu.data.astype(np.float64)
                    break
        if data is None:
            return {"error": "No image data found", "filename": filepath.name}

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    # Gather WCS metadata
    wcs_meta = None
    try:
        wcs_meta = wcs_info(filepath_str)
    except Exception:
        pass

    result = classify_anomalies(
        data,
        wcs_info=wcs_meta,
        spike_sigma=spike_sigma,
        dip_sigma=dip_sigma,
        pattern_break_sigma=pattern_break_sigma,
        window_size=window_size,
    )
    result["filename"] = filepath.name
    if wcs_meta:
        result["wcs_info"] = {
            "projection": wcs_meta.get("projection"),
            "pixel_scale_arcsec": wcs_meta.get("pixel_scale_arcsec"),
            "image_size_arcmin": wcs_meta.get("image_size_arcmin"),
        }
    # v4.26: Attach benchmark status — rule classifier has zero labeled ground truth
    result["_gw_benchmark_status"] = {
        "validated": False,
        "ground_truth_dataset": "none — 0 labeled anomaly samples with verified types",
        "precision_recall_f1": "unknown — no benchmark against labeled dataset performed",
        "threshold_calibration": "global hardcoded (per-band calibration not implemented)",
        "note": (
            "Rule-based classifier uses fixed sigma thresholds applied uniformly across "
            "6 surveys/5 wavelength bands. These thresholds are NOT calibrated per-band "
            "and have NOT been validated against any ground-truth anomaly dataset. "
            "For research use, treat anomaly types as suggestive only. "
            "Use ensemble mode (/pipeline/dl/anomaly/enhance) for independent CNN validation."
        ),
    }
    return result

def _resolve_fits_path(filename: str) -> Path | None:
    """Resolve a FITS filename with fallback search.

    The error-report system stores paths like
    abnormal_results/fits/AliCPT_Abnormal_...fits while the pipeline
    FITS directory uses AliCPT-1/AliCPT_Abnormal_...fits.  This
    helper tries exact match first, then falls back to a recursive
    search by base filename.
    """
    try:
        p = _safe_path(filename, check_fits=False)
        if p.exists():
            return p
    except HTTPException:
        pass
    base = Path(filename).name
    candidates = sorted(Path(FITS_DIR).rglob(base))
    if candidates:
        return candidates[0]
    alt_base = base.replace(".", "_")
    candidates = sorted(Path(FITS_DIR).rglob(alt_base))
    if candidates:
        return candidates[0]
    return None
@app.post("/pipeline/anomaly/classify")
async def classify_anomaly_endpoint(req: AnomalyClassifyRequest):
    """Run rule-based anomaly detection on a FITS file.

    Classifies anomalies into four categories: spike, dip, pattern-break,
    and WCS-mismatch using statistical methods (sigma-clipping, gradient
    analysis, 2-D FFT).  No GPU or deep-learning dependency required.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if filepath is None or not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_heavy(filepath, _classify_single, str(filepath),
                                   req.spike_sigma, req.dip_sigma,
                                   req.pattern_break_sigma, req.window_size)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Anomaly classification failed: {str(e)}")

@app.get("/pipeline/anomaly/classifier-info")
async def anomaly_classifier_info():
    """Get metadata about the rule-based anomaly classifier (v4.26).

    Returns documented limitations, algorithm descriptions, and benchmark status.
    Use this to understand the classifier's scientific validity before relying on results.
    """
    return {
        "classifier_type": "rule-based statistical (numpy/scipy, no deep learning)",
        "version": "v4.26",
        "detectors": {
            "spike": {
                "algorithm": "local sigma-clipping (sigma * local_std above local_mean)",
                "default_threshold": "5.0 sigma",
                "detects": "bright outliers — cosmic rays, hot pixels, RFI spikes",
                "false_positive_risk": "HIGH in high-dynamic-range images; not calibrated per-band",
                "false_negative_risk": "MODERATE — weak spikes below 3σ may be missed",
            },
            "dip": {
                "algorithm": "inverse sigma-clipping (sigma * local_std below local_mean)",
                "default_threshold": "5.0 sigma",
                "detects": "dark defects — dead pixels, missing data, chip gaps",
                "false_positive_risk": "HIGH near image edges and in low-SNR regions",
                "false_negative_risk": "MODERATE — shallow dips in bright regions may be missed",
            },
            "pattern_break": {
                "algorithm": "row/column gradient analysis + 2D FFT high-frequency detection",
                "default_threshold": "4.0 sigma",
                "detects": "striping, row/column artifacts, mosaic seams, periodic noise",
                "false_positive_risk": "HIGH in images with strong astrophysical gradients (e.g. edge-on galaxies)",
                "false_negative_risk": "MODERATE — low-amplitude periodic patterns may go undetected",
            },
            "wcs_mismatch": {
                "algorithm": "WCS metadata validation (CRVAL range, CD matrix singularity, pixel scale)",
                "default_threshold": "N/A (metadata check)",
                "detects": "incorrect coordinate systems, missing WCS, corrupted astrometry",
                "false_positive_risk": "LOW — metadata checks are deterministic",
                "false_negative_risk": "LOW — but cannot detect scientifically-wrong-but-syntactically-valid WCS",
            },
        },
        "benchmark_status": {
            "validated": False,
            "ground_truth_available": False,
            "labeled_samples": 0,
            "precision": "unknown",
            "recall": "unknown",
            "f1": "unknown",
            "per_class_metrics": "unknown",
            "cross_survey_validation": "not performed",
            "note": (
                "No labeled anomaly dataset exists for this platform. "
                "The 12 anomaly reports in ES have type labels (DEAD_PIX/RFI/HOT_PIX/NOISE) "
                "but these were assigned by the same rule classifier, creating a circular "
                "validation problem. Independent ground truth (e.g., manual astronomer labeling) "
                "is needed before any accuracy claims can be made."
            ),
        },
        "calibration": {
            "per_band_calibrated": False,
            "threshold_adaptation": "none — fixed thresholds for all surveys/bands",
            "known_issue": (
                "NVSS (1.4 GHz radio) and AliCPT (90/150 GHz millimeter) have noise baselines "
                "differing by orders of magnitude. Fixed sigma thresholds WILL cause systematic "
                "over-detection in some bands and under-detection in others."
            ),
        },
        "recommendations": [
            "Use ensemble mode (/pipeline/dl/anomaly/enhance) for independent CNN validation of each detection",
            "Treat rule classifier types as hypotheses, not definitive classifications",
            "Manual astronomer review recommended before citing results in publications",
            "Accumulate user feedback to build labeled dataset for future ML training",
        ],
        "_gw_source": "pipeline-live",
    }

@app.post("/pipeline/photometry")
async def compare_photometry(req: PhotometryRequest):
    """Extract photometric statistics from multiple FITS files for comparison.

    Returns per-file statistics (min/max/mean/median/std, aperture flux)
    suitable for multi-band SED plotting or light curve analysis.
    """
    results = []
    loop = asyncio.get_running_loop()
    for fn in req.filenames:
        try:
            filepath = _safe_path(fn, check_fits=True)
            if not filepath.exists():
                results.append({"filename": fn, "error": "File not found"})
                continue
            phot = await _run_heavy(filepath, _extract_photometry, str(filepath))
            results.append(phot)
        except HTTPException as e:
            results.append({"filename": fn, "error": str(e.detail)})
        except Exception as e:
            results.append({"filename": fn, "error": str(e)})
    return {"count": len(results), "results": results}

# ═══════════════════════════════════════════════════════════════════════
#  v4.18 Deep Learning Inference Endpoints
#  Locally-embedded astronomy-domain open-source DL models
#  (Zoobot, AION-1, lightweight classifiers)
# ═══════════════════════════════════════════════════════════════════════

@app.post("/pipeline/dl/morphology")
async def dl_galaxy_morphology(req: DLClassifyRequest):
    """Classify galaxy morphology from FITS image data.

    Uses locally-embedded deep learning models (Zoobot ONNX or
    lightweight feature-based classifier). No external API calls.

    Returns morphology class (spiral/elliptical/edge-on/merger/irregular)
    with confidence scores and model provenance.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if filepath is None or not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_dl_inference(filepath, _run_morphology, str(filepath))
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL morphology classification failed: {str(e)}")

@app.post("/pipeline/dl/source-type")
async def dl_source_type(req: DLClassifyRequest):
    """Classify astronomical source type (star/galaxy/quasar).

    Uses photometric and morphological features extracted from FITS data.
    Returns source classification with confidence scores.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if filepath is None or not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_dl_inference(filepath, _run_source_type, str(filepath))
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL source classification failed: {str(e)}")

@app.post("/pipeline/dl/anomaly/detect")
async def dl_anomaly_detect(req: DLClassifyRequest):
    """Independent DL-based anomaly detection using CNN autoencoder (v4.22).

    The CNN autoencoder IS the detector. It does NOT require a rule
    classifier to run first. Reconstruction error alone determines
    whether an image is anomalous.

    For anomaly TYPE classification (spike/dip/etc), use the
    /pipeline/anomaly/classify endpoint or the ensemble endpoint.
    """
    try:
        filepath = _safe_path(req.filename)
        result: dict = await _run_dl_inference(filepath, _run_dl_anomaly_detect, str(filepath))
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import logging
        logging.getLogger("pipeline.dl").exception("DL anomaly detection failed")
        raise HTTPException(500, f"DL anomaly detection failed: {str(e)}")

@app.post("/pipeline/dl/anomaly/enhance")
async def dl_anomaly_enhance(req: DLAnomalyEnhanceRequest):
    """Ensemble anomaly detection: rule classifier + DL autoencoder (v4.22).

    Both models vote independently, then results are combined.
    This is genuine ensemble learning, not one model enhancing the other.

    The DL autoencoder provides an independent anomaly assessment
    (is this image anomalous?) while the rule classifier provides
    type classification (spike/dip/pattern_break/wcs_mismatch).
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if filepath is None or not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_dl_inference(
            filepath, _run_anomaly_enhance, str(filepath),
            req.anomaly_type, req.rule_confidence
        )
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL anomaly enhancement failed: {str(e)}")

@app.get("/pipeline/dl/versions")
async def dl_model_versions():
    """Get version, drift, and license metadata for all DL models (v4.25)."""
    try:
        from .dl_inference import get_model_versions
        return {"models": get_model_versions(), "_gw_source": "pipeline-live"}
    except Exception as e:
        return {"models": {}, "_gw_source": "pipeline-error",
                "error": f"Failed to get model versions: {str(e)[:200]}"}

@app.get("/pipeline/dl/status")
async def dl_status():
    """Get status of all locally-embedded DL models (v4.29).

    Returns ONNX availability, loaded models, GPL compliance status
    (with active_license transparency), benchmark reports, inference
    statistics, and concurrency configuration.
    """
    try:
        status = dl_get_model_status()
        result = {
            "onnx_available": status.onnx_available,
            "models": status.models,
            # v4.29: GPL transparency from dataclass — no more field duplication
            "gpl_status": status.gpl_status,
            "active_license": status.active_license,
        }
        # v4.27: Inference stats
        with _dl_inference_lock:
            result["inference_stats"] = dict(_dl_inference_stats)
        result["inference_config"] = status.inference_config
        result["inference_config"]["current_free_memory_mb"] = round(_get_free_memory_mb(), 0)
        # v4.27: Benchmark report (if available)
        benchmark_path = Path(os.environ.get("DL_MODEL_DIR", "/app/models")) / "benchmark_report.json"
        # v4.28: Rule classifier benchmark report
        rule_bench_path = Path(os.environ.get("DL_MODEL_DIR", "/app/models")) / "benchmark_rule_report.json"
        if benchmark_path.exists():
            import json as _json
            try:
                with open(benchmark_path) as bf:
                    result["benchmark"] = _json.load(bf)
            except Exception:
                result["benchmark"] = {"available": False, "note": "Benchmark report exists but could not be read"}
        else:
            result["benchmark"] = {
                "available": False,
                "note": "No benchmark report. Run benchmark/benchmark_classifiers.py to generate.",
            }
        # v4.28: Rule classifier benchmark (synthetic injection)
        if rule_bench_path.exists():
            import json as _json
            try:
                with open(rule_bench_path) as rf:
                    result["rule_classifier_benchmark"] = _json.load(rf)
            except Exception:
                result["rule_classifier_benchmark"] = {"available": False, "note": "Report exists but unreadable"}
        else:
            result["rule_classifier_benchmark"] = {
                "available": False,
                "note": "No rule classifier benchmark. Run benchmark/benchmark_rule_classifier.py to generate.",
            }
        result["_gw_source"] = "pipeline-live"
        result["mcp_version"] = "v4.29"
        return result
    except Exception as e:
        return {"error": str(e), "onnx_available": False, "models": [], "_gw_source": "pipeline-error"}

# ═══════════════════════════════════════════════════════════════════════
#  v4.29 DL Concurrency Diagnostic Endpoint
# ═══════════════════════════════════════════════════════════════════════

@app.get("/pipeline/dl/concurrency-test")
async def dl_concurrency_test(n: int = 5, trials: int = 3):
    """Run concurrency diagnostic to verify ONNX GIL release behavior (v4.29).

    Performs N parallel lightweight inferences (and ONNX if available)
    to measure speedup vs serial execution. This validates that the
    ThreadPoolExecutor + asyncio.Semaphore architecture achieves true
    parallelism.

    ONNX Runtime's C++ backend calls Py_BEGIN_ALLOW_THREADS during
    inference, releasing the Python GIL. This test CONFIRMS that
    behavior empirically — if speedup < 0.7×N, the GIL is not being
    released and a ProcessPoolExecutor migration is needed.

    Query params:
        n: Number of parallel calls (default 5, max 20)
        trials: Number of measurement rounds (default 3, max 10)
    """
    n = max(1, min(n, 20))
    trials = max(1, min(trials, 10))
    try:
        result = dl_concurrency_test(n_parallel=n, n_trials=trials)
        result["_gw_source"] = "pipeline-live"
        return result
    except Exception as e:
        return {
            "error": str(e),
            "_gw_source": "pipeline-error",
            "test": "v4.29 concurrency diagnostic failed",
        }

# ═══════════════════════════════════════════════════════════════════════
#  v4.27 DL Model Management Endpoints
# ═══════════════════════════════════════════════════════════════════════

@app.get("/pipeline/dl/benchmark")
async def dl_benchmark():
    """Get the DL model benchmark report (v4.27).

    Returns actual measured performance metrics from benchmark_classifiers.py
    run against the 180 AliCPT-1 FITS files. Includes:
      - Anomaly detection precision/recall/F1 on 12 labeled samples
      - Morphology class distribution (no ground truth, consistency only)
      - Source type classification distribution
      - Inference timing statistics
    """
    benchmark_path = Path(os.environ.get("DL_MODEL_DIR", "/app/models")) / "benchmark_report.json"
    if not benchmark_path.exists():
        return {
            "available": False,
            "_gw_source": "pipeline-live",
            "note": (
                "No benchmark report found. Run: python benchmark/benchmark_classifiers.py "
                "to generate performance metrics against the 180 AliCPT-1 FITS files."
            ),
        }
    try:
        import json as _json
        with open(benchmark_path) as f:
            report = _json.load(f)
        report["_gw_source"] = "pipeline-live"
        return report
    except Exception as e:
        return {"available": False, "error": str(e), "_gw_source": "pipeline-error"}

@app.post("/pipeline/dl/activate-version")
async def dl_activate_version(request: Request):
    """Activate a specific model version (v4.27).

    Switches the /app/models/current symlink to point to the specified version.
    Models are reloaded on the next inference request (lazy reload).

    Request body: {"version": "v2"}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    version = body.get("version", "")
    if not version:
        raise HTTPException(400, 'Missing "version" field. Example: {"version": "v2"}')

    models_dir = Path(os.environ.get("DL_MODEL_DIR", "/app/models"))
    target_dir = models_dir / version
    if not target_dir.exists():
        available = [d.name for d in models_dir.iterdir() if d.is_dir() and d.name.startswith("v")]
        raise HTTPException(
            404,
            f"Version '{version}' not found. Available versions: {', '.join(sorted(available))}"
        )

    current_link = models_dir / "current"
    try:
        if current_link.exists() or current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(target_dir)
        # Clear ONNX session cache so models are reloaded on next request
        from .dl_inference import _ONNX
        unloaded = _ONNX.unload_all()
        return {
            "status": "activated",
            "version": version,
            "models_unloaded": unloaded,
            "note": "Models will be reloaded on next inference request",
            "_gw_source": "pipeline-live",
        }
    except OSError as e:
        raise HTTPException(500, f"Failed to activate version: {e}")

@app.post("/pipeline/dl/rollback")
async def dl_rollback():
    """Rollback to the previous model version (v4.27).

    Reads the activation history from model_registry.json and reverts
    to the version before the current one.
    """
    import json as _json
    models_dir = Path(os.environ.get("DL_MODEL_DIR", "/app/models"))
    registry_path = models_dir / "model_registry.json"

    if not registry_path.exists():
        raise HTTPException(404, "No model_registry.json found. Cannot determine rollback target.")

    try:
        with open(registry_path) as f:
            registry = _json.load(f)
    except Exception as e:
        raise HTTPException(500, f"Failed to read model_registry.json: {e}")

    history = registry.get("activation_history", [])
    if len(history) < 2:
        return {
            "status": "no_rollback_available",
            "current_version": history[-1] if history else "unknown",
            "note": "Need at least 2 activations in history for rollback",
            "_gw_source": "pipeline-live",
        }

    # Current version is the last entry, rollback target is the one before
    current_version = history[-1]
    rollback_target = history[-2]

    target_dir = models_dir / rollback_target
    if not target_dir.exists():
        raise HTTPException(
            500,
            f"Rollback target '{rollback_target}' directory not found on disk"
        )

    current_link = models_dir / "current"
    try:
        if current_link.exists() or current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(target_dir)
        from .dl_inference import _ONNX
        unloaded = _ONNX.unload_all()
        return {
            "status": "rolled_back",
            "from_version": current_version,
            "to_version": rollback_target,
            "models_unloaded": unloaded,
            "note": "Models will be reloaded on next inference request",
            "_gw_source": "pipeline-live",
        }
    except OSError as e:
        raise HTTPException(500, f"Failed to rollback: {e}")

@app.get("/pipeline/dl/inference-stats")
async def dl_inference_stats():
    """Get DL inference statistics (v4.27)."""
    with _dl_inference_lock:
        stats = dict(_dl_inference_stats)
    return {
        "stats": stats,
        "config": {
            "max_concurrent": _DL_MAX_CONCURRENT,
            "timeout_sec": _DL_INFERENCE_TIMEOUT_SEC,
            "min_free_memory_mb": _DL_MIN_FREE_MEMORY_MB,
            "current_free_memory_mb": round(_get_free_memory_mb(), 0),
        },
        "_gw_source": "pipeline-live",
    }

# ── DL inference helper functions (run in heavy thread pool) ────────

def _run_morphology(filepath: str) -> dict:
    """Run galaxy morphology classification on a FITS file."""
    try:
        from .fits_core import read_fits
        fits_result = read_fits(filepath)
        data = fits_result["data"]
        result: GalaxyMorphologyResult = classify_galaxy_morphology(data)
        return {
            "filename": filepath,
            "morphology_class": result.morphology_class,
            "confidence": round(result.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in result.probabilities.items()},
            "model_name": result.model_name,
            "inference_time_ms": result.inference_time_ms,
            "needs_onnx_upgrade": result.needs_onnx,
            # v4.27: Explainability — archetype cosine similarities
            "archetype_similarities": result.archetype_similarities,
        }
    except Exception as e:
        return {"error": str(e)}

def _run_source_type(filepath: str) -> dict:
    """Run source type classification on a FITS file."""
    try:
        from .fits_core import read_fits
        fits_result = read_fits(filepath)
        data = fits_result["data"]
        result: SourceTypeResult = classify_source_type(data)
        return {
            "filename": filepath,
            "source_class": result.source_class,
            "confidence": round(result.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in result.probabilities.items()},
            "model_name": result.model_name,
            "inference_time_ms": result.inference_time_ms,
            "features_used": result.features_used,
            # v4.27: Explainability — feature importance ranking
            "feature_importance": result.feature_importance,
        }
    except Exception as e:
        return {"error": str(e)}

def _run_dl_anomaly_detect(filepath: str) -> dict:
    """Run independent DL anomaly detection (no rule classifier input needed).

    The CNN autoencoder is the primary detector.
    """
    fits_result = read_fits(filepath)
    data = fits_result["data"]
    if data is None or data.size == 0:
        raise ValueError("Empty FITS data")

    result = None  # v4.37: detect_anomaly_dl not available in container dl_inference
    return {
        "filename": filepath,
        "is_anomalous": result.is_anomalous,
        "anomaly_score": result.anomaly_score,
        "reconstruction_error": result.reconstruction_error,
        "confidence": result.confidence,
        "verdict": result.verdict,
        "threshold_used": result.threshold_used,
        "model_name": result.model_name,
        "inference_time_ms": result.inference_time_ms,
        # v4.27: Explainability — pixel-level reconstruction error heatmap
        # error_map is a 2-D list of normalized error values (0-1).
        # For large FITS (>100x100), this field is truncated to first 64x64
        # to keep response size manageable. Use /pipeline/dl/anomaly/error-map
        # endpoint for full-resolution heatmap.
        "error_map": (
            [row[:64] for row in result.error_map[:64]]
            if result.error_map and len(result.error_map) > 0
            else []
        ),
        "error_map_full_resolution_available": len(result.error_map) > 0,
    }

def _run_anomaly_enhance(filepath: str, anomaly_type: str, rule_confidence: float) -> dict:
    """Run ensemble anomaly detection (rule + DL vote independently)."""
    try:
        from .fits_core import read_fits
        fits_result = read_fits(filepath)
        data = fits_result["data"]
        result: AnomalyEnhancementResult = enhance_anomaly_detection(
            data, anomaly_type, rule_confidence
        )
        return {
            "filename": filepath,
            "original_type": result.original_type,
            "original_confidence": result.original_confidence,
            "enhanced_confidence": result.enhanced_confidence,
            "dl_verdict": result.dl_verdict,
            "explanation": result.explanation,
            "model_name": result.model_name,
        }
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════════════
#  v4.18 Deep Learning Inference Endpoints
#  Locally-embedded astronomy-domain open-source DL models
#  (Zoobot, AION-1, lightweight classifiers)
# ═══════════════════════════════════════════════════════════════════════

@app.post("/pipeline/dl/morphology")
async def dl_galaxy_morphology(req: DLClassifyRequest):
    """Classify galaxy morphology from FITS image data.

    Uses locally-embedded deep learning models (Zoobot ONNX or
    lightweight feature-based classifier). No external API calls.

    Returns morphology class (spiral/elliptical/edge-on/merger/irregular)
    with confidence scores and model provenance.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_heavy(filepath, _run_morphology, str(filepath))
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL morphology classification failed: {str(e)}")

@app.post("/pipeline/dl/source-type")
async def dl_source_type(req: DLClassifyRequest):
    """Classify astronomical source type (star/galaxy/quasar).

    Uses photometric and morphological features extracted from FITS data.
    Returns source classification with confidence scores.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_heavy(filepath, _run_source_type, str(filepath))
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL source classification failed: {str(e)}")

@app.post("/pipeline/dl/anomaly/enhance")
async def dl_anomaly_enhance(req: DLAnomalyEnhanceRequest):
    """Enhance rule-based anomaly detection with DL confidence rescoring.

    Cross-validates anomaly classifications using image feature analysis.
    Returns enhanced confidence scores and DL verdict.
    """
    try:
        filepath = _resolve_fits_path(req.filename)
        if not filepath.exists():
            raise HTTPException(404, f"File not found: {req.filename}")
        result = await _run_heavy(
            filepath, _run_anomaly_enhance, str(filepath),
            req.anomaly_type, req.rule_confidence
        )
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except FITSError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"DL anomaly enhancement failed: {str(e)}")

@app.get("/pipeline/dl/status")
async def dl_status():
    """Get status of all locally-embedded DL models.

    Returns ONNX availability, loaded models, and lightweight fallback status.
    """
    try:
        return dl_get_model_status()
    except Exception as e:
        return {"error": str(e), "onnx_available": False, "models": []}

# ── DL inference helper functions (run in heavy thread pool) ────────

def _run_morphology(filepath: str) -> dict:
    """Run galaxy morphology classification on a FITS file."""
    try:
        from .fits_core import read_fits
        data, _header, _shape, _dtype = read_fits(filepath)
        result: GalaxyMorphologyResult = classify_galaxy_morphology(data)
        return {
            "filename": filepath,
            "morphology_class": result.morphology_class,
            "confidence": round(result.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in result.probabilities.items()},
            "model_name": result.model_name,
            "inference_time_ms": result.inference_time_ms,
            "needs_onnx_upgrade": result.needs_onnx,
        }
    except Exception as e:
        return {"error": str(e)}

def _run_source_type(filepath: str) -> dict:
    """Run source type classification on a FITS file."""
    try:
        from .fits_core import read_fits
        data, _header, _shape, _dtype = read_fits(filepath)
        result: SourceTypeResult = classify_source_type(data)
        return {
            "filename": filepath,
            "source_class": result.source_class,
            "confidence": round(result.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in result.probabilities.items()},
            "model_name": result.model_name,
            "inference_time_ms": result.inference_time_ms,
            "features_used": result.features_used,
        }
    except Exception as e:
        return {"error": str(e)}

def _run_anomaly_enhance(filepath: str, anomaly_type: str, rule_confidence: float) -> dict:
    """Run DL-enhanced anomaly confidence rescoring."""
    try:
        from .fits_core import read_fits
        data, _header, _shape, _dtype = read_fits(filepath)
        result: AnomalyEnhancementResult = enhance_anomaly_detection(
            data, anomaly_type, rule_confidence
        )
        return {
            "filename": filepath,
            "original_type": result.original_type,
            "original_confidence": result.original_confidence,
            "enhanced_confidence": result.enhanced_confidence,
            "dl_verdict": result.dl_verdict,
            "explanation": result.explanation,
            "model_name": result.model_name,
        }
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════════════
#  v4.16 Scientific Computing Endpoints
# ═══════════════════════════════════════════════════════════════════════

# ── SSE Job Progress Stream (Fix 1) ──────────────────────────────────

@app.get("/pipeline/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str):
    """SSE endpoint: real-time job progress push for frontend loading bars.

    Usage (frontend JS):
      const es = new EventSource('/pipeline/jobs/abc123/stream')
      es.addEventListener('progress', (e) => {
        const { progress, status } = JSON.parse(e.data)
        setProgress(progress)  // 0.0 → 1.0
      })
      es.addEventListener('done', (e) => { ... handle result ... })
      es.addEventListener('error', (e) => { ... handle error ... })

    Events:
      - progress: {progress: 0.0-1.0, status: "running"}
      - done:     {progress: 1.0, status: "done", result: ...}
      - error:    {progress: N, status: "failed"/"timeout", error: "..."}
    """
    from fastapi.responses import StreamingResponse

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    async def event_stream():
        last_progress = -1.0
        last_status = None

        while True:
            j = get_job(job_id)
            if not j:
                yield f"event: error\ndata: {json.dumps({'error': 'Job not found'})}\n\n"
                return

            current_status = j.status.value
            current_progress = j.progress

            if current_progress != last_progress or current_status != last_status:
                event_data = {"progress": round(current_progress, 3), "status": current_status}

                if current_status == "done":
                    event_data["result"] = j.result
                    yield f"event: done\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    return
                elif current_status in ("failed", "timeout"):
                    event_data["error"] = j.error
                    yield f"event: error\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    return
                else:
                    yield f"event: progress\ndata: {json.dumps(event_data)}\n\n"

                last_progress = current_progress
                last_status = current_status

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# ── SNR Map Download (Fix 2a) ────────────────────────────────────────

@app.get("/pipeline/snr/download")
async def snr_download(
    filename: str = Query(..., description="FITS filename"),
    fmt: str = Query("fits", description="Download format: fits or png"),
):
    """Download the SNR map as a FITS file (with WCS) or high-res PNG.

    Unlike /pipeline/snr which returns JSON + optional inline base64,
    this returns a downloadable file for DS9, Aladin overlay, or publication.
    """
    import io
    import numpy as np
    from astropy.io import fits
    from scipy.ndimage import uniform_filter
    from fastapi.responses import Response
    from astropy.stats import sigma_clipped_stats

    filepath = _safe_path(filename, check_fits=True)
    if not filepath.exists():
        raise HTTPException(404, f"File not found: {filename}")

    with fits.open(str(filepath), memmap=True) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                data = hdu.data.astype(np.float64)
                wcs_header = hdu.header
                break
        else:
            raise HTTPException(400, "No image data")

    _, median, std = sigma_clipped_stats(data, sigma=3.0)
    if std == 0:
        raise HTTPException(400, "Image has zero standard deviation — cannot compute SNR")

    noise_map = uniform_filter(np.abs(data - median), size=7)
    noise_map[noise_map < std * 0.5] = std
    snr_map = (data / noise_map).astype(np.float32)

    if fmt == "fits":
        snr_hdu = fits.PrimaryHDU(data=snr_map, header=wcs_header)
        snr_hdu.header['BUNIT'] = ('S/N', 'Signal-to-noise ratio')
        snr_hdu.header['HISTORY'] = 'SNR map generated by GW Pipeline v4.16'
        buf = io.BytesIO()
        snr_hdu.writeto(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type='application/fits',
            headers={
                'Content-Disposition': f'attachment; filename="snr_{filepath.stem}.fits"',
                'Cache-Control': 'public, max-age=3600',
            },
        )
    else:  # png
        from PIL import Image as PILImage
        snr_clipped = np.clip(snr_map, 0, 10)
        if snr_clipped.size > 2_000_000:
            snr_clipped = snr_clipped[::2, ::2]
        try:
            from matplotlib import cm
            import matplotlib
            matplotlib.use('Agg')
            colored = cm.get_cmap('viridis')(snr_clipped / 10.0)
            colored = (colored[:, :, :3] * 255).astype(np.uint8)
        except ImportError:
            normalized = (snr_clipped / 10.0 * 255).astype(np.uint8)
            colored = np.stack([normalized, normalized // 3, normalized // 6], axis=-1)
        img = PILImage.fromarray(colored, mode='RGB')
        img = img.resize((1024, 1024), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type='image/png',
            headers={
                'Content-Disposition': f'attachment; filename="snr_{filepath.stem}.png"',
                'Cache-Control': 'public, max-age=3600',
            },
        )

# ── Source Detection Parameter Reference (Fix 2b) ────────────────────

@app.get("/pipeline/sources/params")
async def source_detection_params():
    """Return parameter descriptions and tuning advice for the source detection UI.

    Use this to build a frontend parameter-tuning panel with sliders,
    tooltips, and recommended presets for different science cases.
    """
    return {
        "point_sources": {
            "endpoint": "/pipeline/sources",
            "description": "Matched-filter point source detection using DAOStarFinder",
            "parameters": {
                "threshold_snr": {
                    "type": "float", "range": [1.0, 50.0], "default": 5.0, "step": 0.5,
                    "label": "SNR Threshold",
                    "description": "Detection threshold in signal-to-noise. Lower = more sources and more false positives.",
                    "presets": [
                        {"label": "Deep field (faint sources)", "value": 3.0},
                        {"label": "Standard", "value": 5.0},
                        {"label": "Bright only", "value": 10.0},
                    ],
                },
                "fwhm_pix": {
                    "type": "float", "range": [1.0, 20.0], "default": 3.0, "step": 0.5,
                    "label": "FWHM (pixels)",
                    "description": "Full Width at Half Maximum of point sources. Depends on telescope PSF and pixel scale.",
                    "presets": [
                        {"label": "WISE (6\"/pix)", "value": 2.0},
                        {"label": "DSS2 (1.7\"/pix)", "value": 3.0},
                        {"label": "AliCPT", "value": 1.5},
                    ],
                },
                "kernel": {
                    "type": "enum", "values": ["gaussian", "mexicanhat", "tophat"], "default": "gaussian",
                    "label": "Detection Kernel",
                    "description": "Convolution kernel for matched-filter detection.",
                    "presets": [
                        {"label": "Gaussian (isolated sources)", "value": "gaussian"},
                        {"label": "Mexican Hat (crowded fields)", "value": "mexicanhat"},
                        {"label": "Tophat (extended objects)", "value": "tophat"},
                    ],
                },
            },
        },
        "extended_sources": {
            "endpoint": "/pipeline/sources/extended",
            "description": "Image segmentation + deblending for extended/blended sources",
            "parameters": {
                "nsig": {
                    "type": "float", "range": [1.0, 20.0], "default": 3.0, "step": 0.5,
                    "label": "Detection Sigma",
                    "description": "Threshold above background in sigma. Uses Background2D estimation.",
                    "presets": [
                        {"label": "Sensitive", "value": 2.0},
                        {"label": "Standard", "value": 3.0},
                        {"label": "Conservative", "value": 5.0},
                    ],
                },
                "npixels": {
                    "type": "int", "range": [5, 100], "default": 10,
                    "label": "Min Pixels",
                    "description": "Minimum connected pixels for a source. Smaller = detects smaller objects.",
                    "presets": [
                        {"label": "Compact (galaxies)", "value": 10},
                        {"label": "Extended (nebulae)", "value": 30},
                        {"label": "Very extended", "value": 50},
                    ],
                },
                "contrast": {
                    "type": "float", "range": [0.001, 0.1], "default": 0.01, "step": 0.001,
                    "label": "Deblend Contrast",
                    "description": "Fraction of peak for deblending. Lower = more aggressive separation.",
                },
            },
        },
        "snr_map": {
            "endpoint": "/pipeline/snr",
            "download_endpoint": "/pipeline/snr/download?filename=...&fmt=fits",
            "description": "Local RMS-estimated SNR map. Download as FITS (with WCS) for DS9 overlay.",
            "parameters": {
                "heatmap": {
                    "type": "bool", "default": False,
                    "label": "Include Preview",
                    "description": "Include base64 PNG in JSON (for quick preview). Set false for data-only.",
                },
            },
        },
    }

def _apply_profile(profile: str) -> None:
    """R6.53 #4: Apply dev/prod profile to app settings before uvicorn starts."""
    if profile == "dev":
        # Dev: permissive CORS, debug logging, open /docs
        os.environ.setdefault("PIPELINE_DEV_MODE", "1")
        os.environ.setdefault("PIPELINE_CORS_ALLOW_ORIGINS", "*")
        os.environ.setdefault("PIPELINE_LOG_LEVEL", "DEBUG")
        os.environ.setdefault("PIPELINE_DOCS_OPEN", "1")
        os.environ.setdefault("PIPELINE_AUTH_REQUIRED", "0")
        print("[profile] dev: CORS=*, DEBUG logs, /docs open, no auth required")
    elif profile == "prod":
        # Prod: strict CORS (configure via PIPELINE_CORS_ALLOW_ORIGINS), INFO logs,
        # /docs closed, audit logging on
        os.environ.setdefault("PIPELINE_DEV_MODE", "0")
        os.environ.setdefault("PIPELINE_CORS_ALLOW_ORIGINS", "")
        os.environ.setdefault("PIPELINE_LOG_LEVEL", "INFO")
        os.environ.setdefault("PIPELINE_DOCS_OPEN", "0")
        os.environ.setdefault("PIPELINE_AUTH_REQUIRED", "1")
        print("[profile] prod: strict CORS, INFO logs, /docs closed, auth required")
    else:
        raise SystemExit(f"Unknown --profile={profile!r} (expected: dev|prod)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="gw-pipeline FastAPI server")
    parser.add_argument("--profile", choices=["dev", "prod"], default=os.getenv("PIPELINE_PROFILE", "dev"),
                        help="Runtime profile (dev=permissive, prod=strict). Default: dev. "
                             "Override via env PIPELINE_PROFILE=dev|prod.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8200")))
    args = parser.parse_args()

    _apply_profile(args.profile)
    print(f"[startup] gw-pipeline profile={args.profile} host={args.host} port={args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
