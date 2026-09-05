"""
v4.38: FITS File Upload + Vision Q&A (Fix #5)

Provides:
  POST /pipeline/fits/upload              — Upload FITS file for analysis
  GET  /pipeline/fits/upload/{upload_id}  — Get upload status/metadata
  DELETE /pipeline/fits/upload/{upload_id} — Delete uploaded file
  POST /pipeline/agent/vision             — Ask questions about FITS images
  GET  /pipeline/fits/description/{filename} — Generate text description of FITS

Uploaded files stored in /app/uploads/ (tmpfs, auto-cleaned on restart).
Max file size configurable via GW_UPLOAD_MAX_MB env (default 100 MB).

Usage: Import in server.py and call register_upload_routes(app)
"""

from __future__ import annotations
import os, logging, uuid, time as _time, hashlib, shutil
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import Request, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("gw.fits-upload")

_UPLOAD_DIR = Path(os.getenv("GW_UPLOAD_DIR", "/app/uploads"))
_UPLOAD_MAX_MB = int(os.getenv("GW_UPLOAD_MAX_MB", "100"))
_UPLOAD_TTL_SEC = int(os.getenv("GW_UPLOAD_TTL_SEC", "3600"))  # 1 hour


def _validate_fits_magic(content: bytes) -> bool:
    """Check FITS magic bytes (SIMPLE  =)."""
    if len(content) < 80:
        return False
    header_start = content[:80].decode("ascii", errors="replace")
    return header_start.startswith("SIMPLE  =")


def _sanitize_filename(name: str) -> str:
    """Sanitize filename — keep only safe characters."""
    safe = "".join(c for c in name if c.isalnum() or c in "._-")
    return safe[:200] or "upload.fits"


async def _cleanup_expired():
    """Remove expired upload files."""
    now = _time.time()
    if not _UPLOAD_DIR.exists():
        return
    for fpath in _UPLOAD_DIR.glob("*.fits"):
        try:
            if now - fpath.stat().st_mtime > _UPLOAD_TTL_SEC:
                fpath.unlink()
                logger.info("Cleaned up expired upload: %s", fpath.name)
        except Exception:
            pass


def register_upload_routes(app):
    """Register FITS upload + vision routes on the FastAPI app."""

    # Ensure upload directory exists
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    @app.post("/pipeline/fits/upload")
    async def upload_fits(request: Request):
        """Upload a FITS file for temporary analysis.

        Accepts raw binary body with X-Filename header.
        File is validated for FITS format and stored in tmpfs.
        Returns upload_id for use with analysis/vision endpoints.
        """
        await _cleanup_expired()

        # Get filename from header or query
        fname = request.headers.get("X-Filename", "upload.fits")
        fname = request.query_params.get("filename", fname)

        # Validate file extension
        if not fname.lower().endswith((".fits", ".fit", ".fits.gz")):
            return JSONResponse(
                {"error": "Invalid file type. Only .fits, .fit, .fits.gz accepted."},
                status_code=400,
            )

        # Read raw body content
        try:
            content = await request.body()
        except Exception as e:
            return JSONResponse({"error": f"Failed to read request body: {e}"}, status_code=400)

        # Check size
        size_mb = len(content) / (1024 * 1024)
        if size_mb > _UPLOAD_MAX_MB:
            return JSONResponse(
                {"error": f"File too large: {size_mb:.1f}MB (max {_UPLOAD_MAX_MB}MB)"},
                status_code=413,
            )

        # Validate FITS magic bytes
        # For .gz files, check after first 80 bytes (may need decompression)
        if not fname.lower().endswith(".gz"):
            if not _validate_fits_magic(content):
                return JSONResponse(
                    {"error": "Not a valid FITS file — missing 'SIMPLE  =' header"},
                    status_code=400,
                )

        # Generate safe filename and save
        upload_id = uuid.uuid4().hex[:16]
        safe_name = _sanitize_filename(fname)
        save_name = f"{upload_id}_{safe_name}"
        save_path = _UPLOAD_DIR / save_name

        try:
            save_path.write_bytes(content)
        except OSError as e:
            return JSONResponse({"error": f"Failed to save file: {e}"}, status_code=500)

        # Extract basic FITS info
        header_summary = {}
        try:
            from .fits_core import read_fits
            fits_data = read_fits(str(save_path))
            hdr = fits_data.get("header", {})
            header_summary = {
                "naxis": fits_data.get("naxis", 0),
                "shape": list(fits_data["data"].shape) if fits_data.get("data") is not None else [],
                "telescope": hdr.get("TELESCOP", ""),
                "instrument": hdr.get("INSTRUME", ""),
                "object": hdr.get("OBJECT", ""),
                "date_obs": str(hdr.get("DATE-OBS", "")),
                "filter": hdr.get("FILTER", ""),
            }
            # Extract provenance from header
            from .provenance import extract_fits_provenance
            header_summary["provenance"] = extract_fits_provenance(hdr)
        except Exception as e:
            header_summary = {"error": str(e)[:200]}

        # Compute SHA-256
        sha = hashlib.sha256(content).hexdigest()

        logger.info("FITS upload: %s (%.1f MB, sha256=%s)", save_name, size_mb, sha[:16])

        return {
            "upload_id": upload_id,
            "filename": safe_name,
            "file_size_mb": round(size_mb, 2),
            "checksum_sha256": sha,
            "header_summary": header_summary,
            "expires_in_sec": _UPLOAD_TTL_SEC,
        }

    @app.get("/pipeline/fits/upload/{upload_id}")
    async def get_upload_status(upload_id: str, request: Request):
        """Get metadata and status for an uploaded FITS file."""
        await _cleanup_expired()

        # Find file matching upload_id prefix
        matches = list(_UPLOAD_DIR.glob(f"{upload_id}_*"))
        if not matches:
            return JSONResponse({"error": "Upload not found or expired"}, status_code=404)

        fpath = matches[0]
        stat = fpath.stat()
        remaining = max(0, _UPLOAD_TTL_SEC - (_time.time() - stat.st_mtime))

        return {
            "upload_id": upload_id,
            "filename": fpath.name[len(upload_id) + 1:],
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(stat.st_mtime)),
            "expires_in_sec": int(remaining),
        }

    @app.delete("/pipeline/fits/upload/{upload_id}")
    async def delete_upload(upload_id: str, request: Request):
        """Delete an uploaded FITS file."""
        matches = list(_UPLOAD_DIR.glob(f"{upload_id}_*"))
        if not matches:
            return JSONResponse({"error": "Upload not found"}, status_code=404)

        try:
            matches[0].unlink()
            return {"deleted": True, "upload_id": upload_id}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/pipeline/fits/description/{filename}")
    async def generate_fits_description(filename: str, request: Request):
        """Generate a natural-language text description of a FITS file.

        Useful as context for text-only LLMs to "see" FITS data.
        """
        try:
            from .fits_core import read_fits, wcs_info
            import numpy as np

            fits_data = read_fits(filename)
            data = fits_data["data"]
            header = fits_data.get("header", {})
            h, w = data.shape if data.ndim == 2 else (data.shape[-2], data.shape[-1])

            # Basic statistics
            dmin, dmax = float(np.min(data)), float(np.max(data))
            dmean, dstd = float(np.mean(data)), float(np.std(data))
            dmedian = float(np.median(data))

            # WCS info
            wcs_desc = ""
            try:
                wcs = wcs_info(filename)
                ra = wcs.get("reference_value", [0, 0])[0]
                dec = wcs.get("reference_value", [0, 0])[1]
                scale = wcs.get("pixel_scale_arcsec", [0, 0])
                wcs_desc = (
                    f"The image is centered at RA={ra:.4f}°, Dec={dec:.4f}° "
                    f"with pixel scale {scale[0]:.2f}\" per pixel. "
                )
            except Exception:
                pass

            # Telescope / instrument
            telescope = header.get("TELESCOP", "unknown telescope")
            instrument = header.get("INSTRUME", "")
            band = header.get("FILTER", header.get("BAND", ""))
            date_obs = str(header.get("DATE-OBS", ""))

            inst_str = f" ({instrument})" if instrument else ""
            band_str = f" in {band} band" if band else ""
            date_str = f" observed on {date_obs}" if date_obs else ""

            description = (
                f"This is a {h}×{w} FITS image from {telescope}{inst_str}{band_str}{date_str}. "
                f"{wcs_desc}"
                f"Flux statistics: min={dmin:.4f}, max={dmax:.4f}, "
                f"mean={dmean:.4f}, median={dmedian:.4f}, std={dstd:.4f}. "
                f"The dynamic range (max/min) is {dmax / max(abs(dmin), 1e-9):.1f}×."
            )

            return {"filename": filename, "description": description}
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=500)

    @app.post("/pipeline/agent/vision")
    async def agent_vision(request: Request):
        """Answer questions about a FITS image using AI.

        Accepts: {filename, question}
        If the DeepSeek model supports vision, sends the FITS thumbnail as image.
        Otherwise, uses FITS header + stats text description as context.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        filename = body.get("filename", "")
        question = body.get("question", "")

        if not filename or not question:
            return JSONResponse(
                {"error": "Both 'filename' and 'question' are required"},
                status_code=400,
            )

        try:
            from .fits_core import read_fits, wcs_info
            from .agent.agent_loop import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_VISION_MODEL
            import numpy as np
            import base64
            import httpx

            fits_data = read_fits(filename)
            data = fits_data["data"]
            header = fits_data.get("header", {})

            # Get image stats
            dmin, dmax = float(np.min(data)), float(np.max(data))
            dmean, dstd = float(np.mean(data)), float(np.std(data))
            dmedian = float(np.median(data))

            # Build FITS context
            h, w = data.shape if data.ndim == 2 else (data.shape[-2], data.shape[-1])
            telescope = header.get("TELESCOP", "unknown")
            instrument = header.get("INSTRUME", "")
            band = header.get("FILTER", header.get("BAND", "unknown"))

            fits_context = (
                f"FITS image: {h}×{w} pixels, telescope={telescope}, "
                f"instrument={instrument}, band={band}. "
                f"Flux stats: min={dmin:.4f}, max={dmax:.4f}, mean={dmean:.4f}, "
                f"median={dmedian:.4f}, std={dstd:.4f}."
            )

            # Try to generate thumbnail for vision
            thumbnail_b64 = None
            try:
                from .thumbnail_cache import cache_key, get_cached
                ck = cache_key(filename, "thumbnail")
                cached = get_cached(ck)
                if cached:
                    with open(cached, "rb") as fh:
                        thumbnail_b64 = base64.b64encode(fh.read()).decode()
            except Exception:
                pass

            # Build API request
            messages = [
                {"role": "system", "content": (
                    "You are an astronomy AI assistant. Analyze the FITS image data "
                    "and answer the user's question precisely. Reference specific "
                    "pixel values, coordinates, and statistical properties."
                )},
            ]

            # Vision model (deepseek-v4-flash-vision-exp) supports image input — use it
            # whenever a thumbnail is available.
            if thumbnail_b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{thumbnail_b64}"}},
                        {"type": "text", "text": f"{question}\n\nContext: {fits_context}"},
                    ],
                })
            else:
                # Text-only mode with detailed context
                messages.append({
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"Context (this is a FITS image, not a regular photo):\n"
                        f"{fits_context}\n\n"
                        f"Since I cannot show you the actual image, here is all the metadata. "
                        f"Please analyze based on this data and provide your best assessment."
                    ),
                })

            # Call DeepSeek API
            async with httpx.AsyncClient(timeout=120.0) as client:
                api_url = DEEPSEEK_API_URL
                if not api_url.endswith("/chat/completions"):
                    if "/v1" in api_url:
                        api_url = api_url.split("/v1")[0] + "/v1/chat/completions"
                resp = await client.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": DEEPSEEK_VISION_MODEL,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 1000,
                    },
                )
                resp.raise_for_status()
                result = resp.json()

            answer = result["choices"][0]["message"]["content"]
            return {
                "answer": answer,
                "model": result.get("model", DEEPSEEK_VISION_MODEL),
                "filename": filename,
                "fits_context": fits_context,
                "vision_mode": thumbnail_b64 is not None,
            }

        except Exception as e:
            logger.error("agent_vision failed: %s", e)
            return JSONResponse({"error": f"Vision analysis failed: {str(e)[:300]}"}, status_code=500)

    logger.info("v4.38 upload routes registered: FITS upload + vision (%s)", "Fix #5")
