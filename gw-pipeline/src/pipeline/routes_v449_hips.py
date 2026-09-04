# R6.49: HiPS tile CDN fallback resolver.
# Provides /pipeline/hips-tile-resolve and /pipeline/hips-cache-invalidate.

import os as _os
import time as _time
import json as _json
from pathlib import Path as _Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

try:
    import httpx as _httpx
except ImportError:
    _httpx = None

from fastapi import APIRouter, Query

# Fallback order: try fastest public mirrors first, then archive
_HIPS_CDN_FALLBACKS = [
    "https://alasky.cds.unistra.fr",
    "https://aladin.u-strasbg.fr",
    "https://archives.esac.esa.int",
]

# In-process cache: (path) -> (endpoint, ts, latency, ok)
_RESOLVE_CACHE: Dict[str, Tuple[str, float, float, bool]] = {}
_RESOLVE_TTL_S = int(_os.environ.get("HIPS_RESOLVE_TTL_S", "300"))

# R6.50: Persistent file cache so resolve survives container restarts.
_PERSIST_PATH = _Path(_os.environ.get("HIPS_RESOLVE_CACHE_FILE", "/app/observability/hips_resolve_cache.json"))
_LAST_DISK_SAVE: float = 0.0
_SAVE_DEBOUNCE_S: float = 5.0  # don't fsync more often than every 5s


def _load_persistent_cache() -> int:
    """Load cache from disk at module load. Returns number of entries loaded."""
    try:
        if not _PERSIST_PATH.exists():
            return 0
        data = _json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
        n = 0
        for k, v in data.items():
            if isinstance(v, (list, tuple)) and len(v) == 4:
                _RESOLVE_CACHE[k] = (v[0], float(v[1]), float(v[2]), bool(v[3]))
                n += 1
        return n
    except Exception:
        return 0


def _save_persistent_cache(force: bool = False) -> bool:
    """Persist cache to disk. Debounced unless force=True."""
    global _LAST_DISK_SAVE
    now = _time.time()
    if not force and (now - _LAST_DISK_SAVE) < _SAVE_DEBOUNCE_S:
        return False
    try:
        _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Strip entries that have expired
        cutoff = now - _RESOLVE_TTL_S
        live = {k: [v[0], v[1], v[2], v[3]] for k, v in _RESOLVE_CACHE.items() if v[1] >= cutoff}
        _PERSIST_PATH.write_text(_json.dumps(live, ensure_ascii=False), encoding="utf-8")
        _LAST_DISK_SAVE = now
        return True
    except Exception:
        return False


# Load at module import (after both helpers defined)
_LOADED_AT_BOOT = _load_persistent_cache()


def _probe_endpoint(endpoint: str, path: str, timeout: float = 2.5) -> Tuple[str, float, bool]:
    """Probe a single endpoint. Return (endpoint, latency_ms, ok)."""
    if _httpx is None:
        return (endpoint, 0.0, False)
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
    t0 = _time.perf_counter()
    try:
        r = _httpx.head(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 405:
            r = _httpx.get(url, timeout=timeout, follow_redirects=True, headers={"Range": "bytes=0-0"})
        latency = (_time.perf_counter() - t0) * 1000
        ok = r.status_code < 400
        return (endpoint, latency, ok)
    except Exception:
        latency = (_time.perf_counter() - t0) * 1000
        return (endpoint, latency, False)


def resolve_hips_endpoint(path: str, use_cache: bool = True) -> Dict[str, Any]:
    """Probe all CDNs in parallel, return the fastest reachable endpoint."""
    cache_key = path
    now = _time.time()
    if use_cache and cache_key in _RESOLVE_CACHE:
        ep, ts, latency, ok = _RESOLVE_CACHE[cache_key]
        if now - ts < _RESOLVE_TTL_S:
            return {"endpoint": ep, "latency_ms": latency, "ok": ok, "cached": True, "fallback_chain": _HIPS_CDN_FALLBACKS}

    results = []
    if _httpx is not None:
        with ThreadPoolExecutor(max_workers=len(_HIPS_CDN_FALLBACKS)) as ex:
            futures = [ex.submit(_probe_endpoint, ep, path) for ep in _HIPS_CDN_FALLBACKS]
            for f in as_completed(futures):
                results.append(f.result())

    reachable = [r for r in results if r[2]]
    if reachable:
        reachable.sort(key=lambda r: r[1])
        endpoint, latency, _ = reachable[0]
        _RESOLVE_CACHE[cache_key] = (endpoint, now, latency, True)
        _save_persistent_cache()  # R6.50: debounced fsync
        return {"endpoint": endpoint, "latency_ms": latency, "ok": True, "cached": False, "fallback_chain": _HIPS_CDN_FALLBACKS}
    else:
        # All failed; return first fallback as default
        endpoint = _HIPS_CDN_FALLBACKS[0]
        _RESOLVE_CACHE[cache_key] = (endpoint, now, 0.0, False)
        _save_persistent_cache()  # R6.50: debounced fsync
        return {"endpoint": endpoint, "latency_ms": 0.0, "ok": False, "cached": False, "fallback_chain": _HIPS_CDN_FALLBACKS}


router = APIRouter()


@router.get("/pipeline/hips-tile-resolve")
def tile_resolve(path: str = Query(..., description="HiPS tile path")):
    """Return the first reachable HiPS CDN endpoint for the given path."""
    return resolve_hips_endpoint(path, use_cache=True)


@router.post("/pipeline/hips-cache-invalidate")
def cache_invalidate():
    """Clear resolve cache (admin operation)."""
    cleared = len(_RESOLVE_CACHE)
    _RESOLVE_CACHE.clear()
    # R6.50: also delete disk file
    try:
        if _PERSIST_PATH.exists():
            _PERSIST_PATH.unlink()
    except Exception:
        pass
    return {"cleared": cleared, "disk_file_deleted": True}


@router.get("/pipeline/hips-cache-stats")
def cache_stats():
    """R6.50: Return cache statistics + persistence info."""
    now = _time.time()
    live = sum(1 for v in _RESOLVE_CACHE.values() if (now - v[1]) < _RESOLVE_TTL_S)
    expired = len(_RESOLVE_CACHE) - live
    return {
        "entries_total": len(_RESOLVE_CACHE),
        "entries_live": live,
        "entries_expired": expired,
        "ttl_seconds": _RESOLVE_TTL_S,
        "persist_path": str(_PERSIST_PATH),
        "persist_exists": _PERSIST_PATH.exists(),
        "persist_loaded_at_boot": _LOADED_AT_BOOT,
        "last_disk_save_unix": int(_LAST_DISK_SAVE),
    }


def register_routes(app):
    """Register R6.49 hips routes."""
    app.include_router(router)
