"""
R6.27f: HiPS cutout proxy — backend pipeline serves HiPS cutouts on behalf of
the frontend, with disk cache. Solves the cloudflared-tunnel HiPS blocking
problem: frontend browsers cannot reliably reach alasky.cds.unistra.fr from
inside the cloudflare tunnel, so splash gets stuck at 5/19 instead of 19/19.

Why backend proxy (not just frontend fix):
- Frontend browsers go through different network paths than docker containers.
- Pipeline is on the gw-net Docker network with full outbound HTTPS access.
- Backend downloads HiPS once -> caches to disk -> subsequent requests are O(1).
- Frontend talks to /pipeline/hips-thumb which is in-cluster HTTP (fast).

Cache strategy:
- Key: SHA256(survey:band:ra:dec:size:stretch)[:16] -> stable, dedupe-friendly
- Path: /app/hips_cache/<key>.jpg (one file per unique combo)
- Same coordinates + same params = same HiPS JPG -> fetch once, serve forever.
- 19 tiles per observation * ~50KB each = ~1MB per observation -> cheap.
- LRU eviction if cache exceeds MAX_HIPS_CACHE_BYTES.

Failure mode:
- If HiPS CDN is down, backend raises 502 -> frontend onerror fires -> tile
  shows broken image. Splash does NOT force-complete (R6.27e honest settle).
- User sees real progress, real failures. No false success.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter()

# Configuration
HIPS_CUTOUT_BASE = os.getenv(
    "HIPS_CUTOUT_BASE",
    "https://alasky.cds.unistra.fr/hips-image-services/hips2fits",
)
HIPS_CDN_TIMEOUT_S = float(os.getenv("HIPS_CDN_TIMEOUT_S", "20.0"))
HIPS_CACHE_DIR = Path(os.getenv("HIPS_CACHE_DIR", "/app/thumbnail_cache/hips"))
MAX_HIPS_CACHE_BYTES = int(os.getenv("HIPS_MAX_CACHE_MB", "500")) * 1024 * 1024  # 500 MB

HIPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Lightweight stats (no locks - pipeline is single-process per container)
_stats = {
    "hits": 0,
    "misses": 0,
    "errors": 0,
    "bytes_served": 0,
    "bytes_cached": 0,
}


def _cache_key(survey: str, band: str, ra: float, dec: float, size: int, stretch: str) -> str:
    """Stable SHA256-based key. Same inputs -> same key -> cache hit."""
    raw = f"{survey}:{band}:{ra}:{dec}:{size}:{stretch}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _evict_if_needed() -> None:
    """If cache exceeds MAX_HIPS_CACHE_BYTES, delete oldest files until under 80%."""
    try:
        files = [(p, p.stat().st_mtime, p.stat().st_size) for p in HIPS_CACHE_DIR.glob("*.jpg")]
    except OSError:
        return
    total = sum(f[2] for f in files)
    if total <= MAX_HIPS_CACHE_BYTES:
        return
    files.sort(key=lambda x: x[1])
    target = MAX_HIPS_CACHE_BYTES * 0.8
    for path, _, _ in files:
        if total <= target:
            break
        try:
            sz = path.stat().st_size
            path.unlink()
            total -= sz
        except OSError:
            pass


@router.get("/hips-thumb")
async def hips_thumb(
    survey: str = Query(..., description="HiPS survey, e.g. DSS2, 2MASS, allWISE, NVSS, LEGACY"),
    band: str = Query("", description="HiPS band, e.g. Blue, Green, Red, J, H, K, W1, W4"),
    ra: float = Query(..., description="RA in degrees"),
    dec: float = Query(..., description="Dec in degrees"),
    size: int = Query(400, ge=32, le=1200, description="Image width/height in pixels"),
    stretch: str = Query("linear", description="Stretch: linear, log, sqrt, asinh"),
):
    """
    Proxy HiPS cutout. Returns JPG bytes. Cache hits return instantly from disk;
    cache misses fetch from alasky.cds.unistra.fr and persist for next call.
    """
    key = _cache_key(survey, band, ra, dec, size, stretch)
    cache_path = HIPS_CACHE_DIR / f"{key}.jpg"

    # Cache hit
    if cache_path.exists():
        try:
            data = cache_path.read_bytes()
            _stats["hits"] += 1
            _stats["bytes_served"] += len(data)
            return Response(
                content=data,
                media_type="image/jpeg",
                headers={"X-Hips-Cache": "HIT", "Cache-Control": "public, max-age=86400"},
            )
        except OSError:
            pass  # File disappeared between exists() and read_bytes()

    # Cache miss - fetch from HiPS CDN
    hips_id = f"{survey}/{band}" if band else survey
    hips_url = (
        f"{HIPS_CUTOUT_BASE}"
        f"?hips={hips_id}"
        f"&ra={ra}&dec={dec}&fov=3"
        f"&width={size}&height={size}"
        f"&stretch={stretch}&format=jpg"
    )

    try:
        async with httpx.AsyncClient(timeout=HIPS_CDN_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.get(hips_url)
            r.raise_for_status()
            data = r.content
    except httpx.TimeoutException:
        _stats["errors"] += 1
        raise HTTPException(status_code=504, detail=f"HiPS CDN timeout after {HIPS_CDN_TIMEOUT_S}s")
    except httpx.HTTPStatusError as e:
        _stats["errors"] += 1
        raise HTTPException(status_code=502, detail=f"HiPS CDN HTTP {e.response.status_code}")
    except Exception as e:
        _stats["errors"] += 1
        raise HTTPException(status_code=502, detail=f"HiPS CDN fetch failed: {e}")

    # Save to cache (best-effort)
    try:
        cache_path.write_bytes(data)
        _stats["misses"] += 1
        _stats["bytes_cached"] += len(data)
        _stats["bytes_served"] += len(data)
    except OSError:
        _stats["misses"] += 1
        _stats["bytes_served"] += len(data)

    _evict_if_needed()

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"X-Hips-Cache": "MISS", "Cache-Control": "public, max-age=86400"},
    )


@router.get("/hips-float")
async def hips_float(
    survey: str = Query(..., description="HiPS survey"),
    band: str = Query("", description="HiPS band"),
    ra: float = Query(...),
    dec: float = Query(...),
    size: int = Query(400, ge=32, le=1200),
    stretch: str = Query("linear", description="linear/sqrt/log/asinh"),
    min_cut_pct: float = Query(None, ge=0.0, le=49.0, description="Lower percentile cut (0-49)"),
    max_cut_pct: float = Query(None, ge=51.0, le=100.0, description="Upper percentile cut (51-100)"),
    dither: bool = Query(False, description="Apply Floyd-Steinberg dithering before 8-bit quantize"),
    tile: int = Query(1, ge=1, le=4, description="HiPS tile size factor (1=128px, 4=512px)"),
):
    """
    R6.27k: TRUE DS9-quality rendering.

    Pipeline:
      1. Fetch raw FITS from CDS hips2fits?format=fits (32-bit float, lossy-free)
      2. Read into numpy float32 array (full 32-bit precision)
      3. Apply percentile cut on FULL 32-bit histogram (not pre-quantized)
      4. Apply stretch function in float32
      5. OPTIONALLY apply Floyd-Steinberg dithering before 8-bit quantize
      6. Save as lossless PNG and serve to frontend

    Why this beats R6.27j:
      - R6.27j: CDS hips2fits pre-quantized to 8-bit JPEG before cut/stretch.
        Quantization noise floors at 1/255 = 0.4% relative precision.
        Any further stretch on 8-bit values produces step banding.
      - R6.27k: cut/stretch on 32-bit float, then quantize.
        Float preserves 7-decimal precision; only final quantize loses precision.
        With dither, banding is broken into 1-LSB pseudo-random noise.

    JPEG DCT blocks: PNG is lossless so no DCT blocks remain.
    Cost: ~175KB per 400px tile (vs ~30KB JPEG) = 5.8x volume, acceptable for
    user-opt-in high-quality mode (default remains fast JPEG path).
    """
    import io
    import numpy as np
    from astropy.io import fits
    from PIL import Image as PILImage

    key = hashlib.sha256(
        f"{survey}:{band}:{ra}:{dec}:{size}:{stretch}:{min_cut_pct}:{max_cut_pct}:{dither}:{tile}".encode()
    ).hexdigest()[:16]
    cache_path = HIPS_CACHE_DIR / f"{key}.png"

    if cache_path.exists():
        try:
            data = cache_path.read_bytes()
            _stats["hits"] += 1
            _stats["bytes_served"] += len(data)
            return Response(
                content=data,
                media_type="image/png",
                headers={"X-Hips-Cache": "HIT", "X-Hips-Mode": "float", "Cache-Control": "public, max-age=86400"},
            )
        except OSError:
            pass

    hips_id = f"{survey}/{band}" if band else survey
    fits_url = (
        f"{HIPS_CUTOUT_BASE}"
        f"?hips={hips_id}"
        f"&ra={ra}&dec={dec}&fov={3 * (size / 400):.4f}"
        f"&width={size}&height={size}"
        f"&stretch={stretch}&format=fits"
    )

    try:
        async with httpx.AsyncClient(timeout=HIPS_CDN_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.get(fits_url)
            r.raise_for_status()
            fits_bytes = r.content
    except httpx.TimeoutException:
        _stats["errors"] += 1
        raise HTTPException(status_code=504, detail=f"HiPS FITS timeout after {HIPS_CDN_TIMEOUT_S}s")
    except httpx.HTTPStatusError as e:
        _stats["errors"] += 1
        raise HTTPException(status_code=502, detail=f"HiPS FITS HTTP {e.response.status_code}")
    except Exception as e:
        _stats["errors"] += 1
        raise HTTPException(status_code=502, detail=f"HiPS FITS fetch failed: {e}")

    try:
        with fits.open(io.BytesIO(fits_bytes)) as hdul:
            data = hdul[0].data
            if data is None:
                for hdu in hdul:
                    if hdu.data is not None:
                        data = hdu.data
                        break
            if data is None:
                raise ValueError("no image HDU in FITS")
            data = np.asarray(data, dtype=np.float32)
    except Exception as e:
        _stats["errors"] += 1
        raise HTTPException(status_code=502, detail=f"FITS parse failed: {e}")

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    flat = data.ravel()
    if min_cut_pct is not None:
        vmin = float(np.percentile(flat, min_cut_pct))
    else:
        vmin = float(np.percentile(flat, 0.5))
    if max_cut_pct is not None:
        vmax = float(np.percentile(flat, max_cut_pct))
    else:
        vmax = float(np.percentile(flat, 99.5))
    if vmax <= vmin:
        vmax = vmin + 1.0

    scaled = (data - vmin) / (vmax - vmin)
    scaled = np.clip(scaled, 0.0, 1.0).astype(np.float32)
    if stretch == "sqrt":
        scaled = np.sqrt(scaled)
    elif stretch == "log":
        scaled = np.log10(1.0 + 9.0 * scaled)
    elif stretch == "asinh":
        scaled = np.arcsinh(scaled * 5.0) / np.arcsinh(5.0)

    scaled = np.clip(scaled, 0.0, 1.0)

    if dither:
        work = (scaled * 255.0).astype(np.float32).copy()
        h, w = work.shape
        for y in range(h):
            for x in range(w):
                old = work[y, x]
                new = float(round(old))
                work[y, x] = new
                err = old - new
                if x + 1 < w:
                    work[y, x + 1] += err * 7.0 / 16.0
                if y + 1 < h:
                    if x > 0:
                        work[y + 1, x - 1] += err * 3.0 / 16.0
                    work[y + 1, x] += err * 5.0 / 16.0
                    if x + 1 < w:
                        work[y + 1, x + 1] += err * 1.0 / 16.0
        quantized = np.clip(work, 0, 255).astype(np.uint8)
    else:
        quantized = (scaled * 255.0).astype(np.uint8)

    img = PILImage.fromarray(quantized, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    try:
        cache_path.write_bytes(png_bytes)
        _stats["misses"] += 1
        _stats["bytes_cached"] += len(png_bytes)
        _stats["bytes_served"] += len(png_bytes)
    except OSError:
        _stats["misses"] += 1
        _stats["bytes_served"] += len(png_bytes)

    _evict_if_needed()

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"X-Hips-Cache": "MISS", "X-Hips-Mode": "float", "Cache-Control": "public, max-age=86400"},
    )


@router.get("/hips-stats")
async def hips_stats():
    """Diagnostic stats: hits, misses, errors, cache size."""
    try:
        files = list(HIPS_CACHE_DIR.glob("*.jpg"))
        total_bytes = sum(p.stat().st_size for p in files)
    except OSError:
        files = []
        total_bytes = 0
    return {
        "cache_dir": str(HIPS_CACHE_DIR),
        "files": len(files),
        "bytes": total_bytes,
        "max_bytes": MAX_HIPS_CACHE_BYTES,
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "errors": _stats["errors"],
        "bytes_served": _stats["bytes_served"],
        "bytes_cached": _stats["bytes_cached"],
    }


__all__ = ["router"]
