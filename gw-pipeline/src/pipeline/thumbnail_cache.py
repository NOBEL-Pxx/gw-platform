"""Disk-based thumbnail cache with proactive disk-space eviction (v4.16).

Keyed by (filename, size, file_mtime). Regenerates only when source FITS changes.

v4.16 changes:
  - MAX_CACHE_BYTES (500 MB default) — proactive eviction BEFORE write
  - MIN_FREE_DISK_MB (100 MB) — emergency eviction when disk is critically low
  - Synchronous eviction when disk usage > 90% of MAX_CACHE_BYTES
  - Background daemon eviction when disk usage > 70% (non-blocking)
"""
from __future__ import annotations

import hashlib
import os
import time
import shutil
import threading
from pathlib import Path

FITS_DATA_DIR = Path(os.getenv("FITS_DATA_DIR", "/app/data"))
CACHE_DIR = Path(os.getenv("THUMBNAIL_CACHE_DIR", "/app/thumbnail_cache"))

# ── Cache sizing (v4.16: disk-space-based) ───────────────────────────
_MAX_CACHE_ENTRIES = int(os.getenv("THUMBNAIL_MAX_ENTRIES", "5000"))
_MAX_CACHE_AGE_SECONDS = int(os.getenv("THUMBNAIL_MAX_AGE_SECONDS", str(7 * 24 * 3600)))  # 7 days
_MAX_CACHE_BYTES = int(os.getenv("THUMBNAIL_MAX_CACHE_MB", "500")) * 1024 * 1024  # 500 MB
_MIN_FREE_DISK_MB = int(os.getenv("THUMBNAIL_MIN_FREE_DISK_MB", "100")) * 1024 * 1024  # 100 MB

# Proactive eviction thresholds
_WARN_RATIO = 0.70   # Start background eviction at 70% of MAX_CACHE_BYTES
_CRITICAL_RATIO = 0.90  # Synchronous eviction at 90% — blocks writes until complete

_eviction_lock = threading.Lock()
_stats_lock = threading.Lock()
_hits = 0
_misses = 0
_evictions_total = 0
_evictions_size_bytes = 0


def _file_mtime(filename: str) -> float:
    filepath = FITS_DATA_DIR / filename
    try:
        return filepath.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def cache_key(filename: str, size: int) -> str:
    mtime = _file_mtime(filename)
    raw = f"{filename}:{size}:{mtime}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def get_cached(key: str) -> bytes | None:
    global _hits, _misses
    path = CACHE_DIR / f"{key}.png"
    try:
        if path.exists():
            with _stats_lock:
                _hits += 1
            return path.read_bytes()
        with _stats_lock:
            _misses += 1
    except OSError:
        with _stats_lock:
            _misses += 1
    return None


def _get_cache_size() -> tuple[int, int]:
    """Return (total_bytes, file_count) for all cache entries. Thread-safe."""
    if not CACHE_DIR.exists():
        return 0, 0
    try:
        files = list(CACHE_DIR.glob("*.png"))
        total = sum(f.stat().st_size for f in files)
        return total, len(files)
    except OSError:
        return 0, 0


def _get_free_disk_bytes() -> int:
    """Get free disk space on the cache partition."""
    try:
        usage = shutil.disk_usage(CACHE_DIR if CACHE_DIR.exists() else Path("/"))
        return usage.free
    except OSError:
        return 2**63  # assume unlimited


def _evict_by_bytes(target_free_bytes: int) -> int:
    """Synchronously evict oldest cache entries until target_free_bytes is freed.

    Thread-safe. Returns number of entries removed.
    """
    global _evictions_total, _evictions_size_bytes
    if not CACHE_DIR.exists():
        return 0

    with _eviction_lock:
        try:
            files = sorted(CACHE_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return 0

        current_size, _ = _get_cache_size()
        freed = 0
        removed = 0

        for f in files:
            if freed >= target_free_bytes:
                break
            try:
                file_size = f.stat().st_size
                f.unlink()
                freed += file_size
                removed += 1
                _evictions_total += 1
                _evictions_size_bytes += file_size
            except OSError:
                continue

        return removed


def _evict_by_age(max_age_seconds: int) -> int:
    """Evict entries older than max_age_seconds. Returns count removed."""
    global _evictions_total, _evictions_size_bytes
    if not CACHE_DIR.exists():
        return 0

    with _eviction_lock:
        try:
            files = list(CACHE_DIR.glob("*.png"))
        except OSError:
            return 0

        now = time.time()
        removed = 0
        for f in files:
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    file_size = f.stat().st_size
                    f.unlink()
                    removed += 1
                    _evictions_total += 1
                    _evictions_size_bytes += file_size
            except OSError:
                continue
        return removed


def _evict_by_count(max_entries: int) -> int:
    """Evict oldest entries to stay under max_entries. Returns count removed."""
    global _evictions_total, _evictions_size_bytes
    if not CACHE_DIR.exists():
        return 0

    with _eviction_lock:
        try:
            files = sorted(CACHE_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return 0

        removed = 0
        while len(files) > max_entries:
            f = files.pop(0)
            try:
                file_size = f.stat().st_size
                f.unlink()
                removed += 1
                _evictions_total += 1
                _evictions_size_bytes += file_size
            except OSError:
                continue
        return removed


def _guard_cache_write(entry_size_bytes: int = 50_000) -> str | None:
    """Proactive disk-space guard — called BEFORE every cache write.

    Returns None if the write can proceed. Returns a warning string if
    eviction was triggered. Raises RuntimeError if disk is critically full
    and eviction cannot free enough space.

    Strategy:
      1. If cache > 90% of MAX_CACHE_BYTES → sync evict down to 70% (blocks write)
      2. If cache > 70% → async background eviction (non-blocking)
      3. If disk free < MIN_FREE_DISK_MB → sync evict from cache to free space
    """
    current_size, entry_count = _get_cache_size()
    free_disk = _get_free_disk_bytes()

    # ── Sync eviction: cache critically full ──
    critical_threshold = int(_MAX_CACHE_BYTES * _CRITICAL_RATIO)
    if current_size > critical_threshold:
        target = int(_MAX_CACHE_BYTES * _WARN_RATIO)
        target_free = current_size - target + entry_size_bytes
        removed = _evict_by_bytes(target_free)
        if removed > 0:
            return f"CRITICAL: cache {current_size/(1024**2):.0f}MB > {critical_threshold/(1024**2):.0f}MB threshold — evicted {removed} entries"

    # ── Async eviction: cache approaching limit ──
    warn_threshold = int(_MAX_CACHE_BYTES * _WARN_RATIO)
    if current_size > warn_threshold:
        def _bg_evict():
            try:
                target = int(_MAX_CACHE_BYTES * 0.5)
                target_free = current_size - target
                _evict_by_bytes(target_free)
                _evict_by_age(_MAX_CACHE_AGE_SECONDS)
                new_size, _ = _get_cache_size()
            except Exception:
                pass  # daemon must never die
        t = threading.Thread(target=_bg_evict, daemon=True)
        t.start()  # fire-and-forget, non-blocking

    # ── Emergency: disk critically low ──
    if free_disk < _MIN_FREE_DISK_MB:
        target_free = _MIN_FREE_DISK_MB - free_disk + 10 * 1024 * 1024  # +10MB buffer
        removed = _evict_by_bytes(target_free)
        if removed > 0:
            return f"EMERGENCY: disk free < {_MIN_FREE_DISK_MB/(1024**2):.0f}MB — evicted {removed} cache entries"

        # Re-check: if still critically low, refuse write
        free_after = _get_free_disk_bytes()
        if free_after < 10 * 1024 * 1024:  # less than 10MB left
            raise RuntimeError(
                f"Disk critically full ({free_after/(1024**2):.0f}MB free). "
                f"Cannot write to thumbnail cache. Please free disk space."
            )

    return None


def set_cache(key: str, data: bytes) -> None:
    """Write thumbnail to cache with proactive disk-space guarding (v4.16).

    Before writing:
      1. Checks cache size vs MAX_CACHE_BYTES → evicts if > 90%
      2. Checks free disk vs MIN_FREE_DISK_MB → evicts cache entries to free space
      3. Spawns background eviction if > 70% (non-blocking)

    Raises RuntimeError if disk is critically full and cannot recover.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Proactive guard BEFORE writing
    entry_size = len(data)
    warning = _guard_cache_write(entry_size)
    # (warning is logged but doesn't prevent the write — only RuntimeError blocks)

    # Write
    (CACHE_DIR / f"{key}.png").write_bytes(data)

    # Legacy count-based eviction (keeps safety net against count explosion)
    _maybe_evict()


def _maybe_evict() -> None:
    """Legacy count-based eviction — kept as safety net for count explosion.

    Spawns a daemon thread so the caller never blocks.
    """
    def _safe_evict():
        try:
            _evict_by_age(_MAX_CACHE_AGE_SECONDS)
            _evict_by_count(_MAX_CACHE_ENTRIES)
        except Exception:
            pass

    try:
        with _eviction_lock:
            _, count = _get_cache_size()
            over_limit = count > _MAX_CACHE_ENTRIES * 1.1
        if over_limit:
            t = threading.Thread(target=_safe_evict, daemon=True)
            t.start()
    except OSError:
        pass


def evict_cache(max_entries: int = _MAX_CACHE_ENTRIES,
               max_age_seconds: int = _MAX_CACHE_AGE_SECONDS) -> int:
    """Full eviction: age-based + count-based. Thread-safe."""
    removed = _evict_by_age(max_age_seconds)
    removed += _evict_by_count(max_entries)
    return removed


def cache_stats() -> dict:
    global _hits, _misses, _evictions_total, _evictions_size_bytes
    try:
        total_size, entry_count = _get_cache_size()
    except OSError:
        total_size, entry_count = 0, 0
    with _stats_lock:
        h = _hits
        m = _misses
    total_requests = h + m
    hit_rate = round(h / total_requests, 4) if total_requests > 0 else None
    return {
        "cache_dir": str(CACHE_DIR),
        "entries": entry_count,
        "size_bytes": total_size,
        "size_mb": round(total_size / (1024 * 1024), 1),
        "max_entries": _MAX_CACHE_ENTRIES,
        "max_size_mb": _MAX_CACHE_BYTES // (1024 * 1024),
        "max_age_days": _MAX_CACHE_AGE_SECONDS // 86400,
        "min_free_disk_mb": _MIN_FREE_DISK_MB // (1024 * 1024),
        "hits": h,
        "misses": m,
        "hit_rate": hit_rate,
        "evictions_total": _evictions_total,
        "evictions_size_mb": round(_evictions_size_bytes / (1024 * 1024), 1),
    }
