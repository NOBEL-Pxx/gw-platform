"""Tool implementations for the GW AI Agent.

Each tool is an async function that takes validated arguments and returns
a JSON-serializable result dict. Tools access:
  - Spring Boot backend API (gw-backend:8093) for database queries
  - Local filesystem for FITS file operations
  - Local pipeline endpoints for DL inference
  - MCP server (gw-mcp-server:8100) for health/degradation status

All tools return structured results with at minimum:
  { "success": bool, ... tool-specific fields ... }
"""
import os, json, time, logging
from typing import Optional, Dict, Any
import httpx

_log = logging.getLogger("gw-agent-tools")

# ── Service URLs (Docker network internal) ──────────────────────────
BACKEND_URL = os.getenv("BACKEND_SERVICE_URL", "http://gw-backend:8093")
MCP_URL = os.getenv("MCP_SERVICE_URL", "http://gw-mcp-server:8100")
BASE_PATH = "/api/app/gravitationalwave"
FITS_DATA_DIR = os.getenv("FITS_DATA_DIR", "/app/data")

# ── Timeouts ─────────────────────────────────────────────────────────
_TOOL_CONNECT_TIMEOUT = float(os.getenv("AGENT_TOOL_CONNECT_TIMEOUT", "10.0"))
_TOOL_READ_TIMEOUT = float(os.getenv("AGENT_TOOL_READ_TIMEOUT", "30.0"))
_TOOL_TOTAL_TIMEOUT = float(os.getenv("AGENT_TOOL_TOTAL_TIMEOUT", "60.0"))
# v4.35: Parameter validation functions (Fix #5)
import math as _math


def _validate_coordinates(ra=None, dec=None, radius=None):
    """Validate astronomical coordinate parameters. Returns list of error strings."""
    errors = []
    if ra is not None:
        if not _math.isfinite(ra):
            errors.append(f"RA={ra} is not a finite number")
        elif not (-360.0 <= ra <= 360.0):
            errors.append(f"RA={ra} out of valid range [0, 360]")
    if dec is not None:
        if not _math.isfinite(dec):
            errors.append(f"Dec={dec} is not a finite number")
        elif not (-90.0 <= dec <= 90.0):
            errors.append(f"Dec={dec} out of valid range [-90, 90]")
    if radius is not None:
        if not _math.isfinite(radius):
            errors.append(f"Radius={radius} is not a finite number")
        elif not (0.0 < radius <= 180.0):
            errors.append(f"Radius={radius} out of valid range (0, 180]")
    return errors


def _validate_filename(filename: str):
    """Validate FITS filename - prevent path traversal and empty values."""
    if not filename or not isinstance(filename, str) or not filename.strip():
        return ["Filename is empty or invalid"]
    if ".." in filename or filename.startswith("/") or "\\" in filename:
        return [f"Invalid filename (path traversal blocked): {filename}"]
    if len(filename) > 500:
        return [f"Filename too long ({len(filename)} chars, max 500)"]
    return []


def _validate_page_params(page=None, page_size=None):
    """Validate pagination parameters."""
    errors = []
    if page is not None:
        if not isinstance(page, int) or page < 1:
            errors.append(f"Page={page} must be integer >= 1")
        elif page > 10000:
            errors.append(f"Page={page} too large (max 10000)")
    if page_size is not None:
        if not isinstance(page_size, int) or page_size < 1:
            errors.append(f"Page size={page_size} must be integer >= 1")
        elif page_size > 100:
            errors.append(f"Page size={page_size} too large (max 100)")
    return errors


# v4.35: Per-tool validators mapping
_TOOL_VALIDATORS = {
    "search_observations": lambda **a: (
        _validate_coordinates(a.get('ra'), a.get('dec'), a.get('radius')) +
        _validate_page_params(a.get('page'), a.get('page_size'))
    ),
    "count_observations": lambda **a: _validate_page_params(a.get("page"), a.get("page_size")),
    "get_error_reports": lambda **a: _validate_page_params(a.get("page"), a.get("page_size")),
    "get_error_detail": lambda **a: _validate_page_params(a.get("page"), a.get("page_size")),
    "get_comments": lambda **a: _validate_page_params(a.get("page"), a.get("page_size")),
    "list_fits_files": lambda **a: _validate_page_params(None, a.get("limit")),
    "get_fits_header": lambda **a: _validate_filename(a.get("filename", "")),
    "get_fits_stats": lambda **a: _validate_filename(a.get("filename", "")),
    "classify_galaxy_morphology": lambda **a: _validate_filename(a.get("filename", "")),
    "classify_source_type": lambda **a: _validate_filename(a.get("filename", "")),
    "detect_anomaly_dl": lambda **a: _validate_filename(a.get("filename", "")),
    "run_wcs_query": lambda **a: _validate_filename(a.get("filename", "")) +
        ([] if a.get('x') is None else ([] if isinstance(a.get('x'), (int,float)) and a['x'] >= 0 else [f"x={a.get('x')} must be non-negative"])) +
        ([] if a.get('y') is None else ([] if isinstance(a.get('y'), (int,float)) and a['y'] >= 0 else [f"y={a.get('y')} must be non-negative"])),
}



async def _backend_get(path: str, params: dict = None) -> dict:
    """Call Spring Boot backend API."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=_TOOL_CONNECT_TIMEOUT, read=_TOOL_READ_TIMEOUT,
                              write=10.0, pool=5.0),
    ) as client:
        url = f"{BACKEND_URL}{BASE_PATH}{path}"
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _mcp_get(path: str, params: dict = None) -> dict:
    """Call MCP server HTTP API."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=_TOOL_READ_TIMEOUT, write=5.0, pool=5.0),
    ) as client:
        url = f"{MCP_URL}{path}"
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# Database Query Tools
# ═══════════════════════════════════════════════════════════════════════════

async def search_observations(ra=None, dec=None, radius=1.0, telescope=None,
                               page=1, page_size=10) -> dict:
    """Search observations by coordinates and/or telescope."""
    try:
        params = {"page": page, "page_size": min(page_size, 100), "radius": radius}
        if ra is not None: params["ra"] = ra
        if dec is not None: params["dec"] = dec
        if telescope: params["telescope"] = telescope

        result = await _backend_get("/geoSearch", params)
        total = result.get("data", {}).get("total_info", {}).get("total_count", 0)
        items = result.get("data", {}).get("list", [])
        return {
            "success": True,
            "total_count": total,
            "returned_count": len(items),
            "page": page,
            "page_size": page_size,
            "records": items[:20],  # Limit to avoid huge responses
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Search failed: {str(e)[:200]}"}


async def get_error_reports(page=1, page_size=10) -> dict:
    """Get anomaly detection error reports."""
    try:
        result = await _backend_get("/error", {"page": page, "page_size": min(page_size, 100)})
        total = result.get("data", {}).get("total_info", {}).get("total_count", 0)
        items = result.get("data", {}).get("list", [])
        return {
            "success": True,
            "total_count": total,
            "returned_count": len(items),
            "page": page,
            "reports": items[:20],
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Error reports query failed: {str(e)[:200]}"}


async def get_error_detail(error_id: str, page=1, page_size=10) -> dict:
    """Get detailed info for a specific anomaly."""
    try:
        result = await _backend_get(f"/error/{error_id}", {"page": page, "page_size": min(page_size, 100)})
        items = result.get("data", {}).get("list", [])
        log_content = items[0].get("logContent", "") if items else result.get("data", {}).get("logContent", "")
        return {
            "success": True,
            "error_id": error_id,
            "total_details": result.get("data", {}).get("total_info", {}).get("total_count", 0),
            "details": items[:10],
            "log_preview": str(log_content)[:500] if log_content else "N/A",
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Error detail query failed: {str(e)[:200]}"}


async def get_error_reference(error_id: str, uuid: str) -> dict:
    """Get multi-band observation data for a specific anomaly source."""
    try:
        result = await _backend_get(f"/error/{error_id}/{uuid}")
        return {
            "success": True,
            "error_id": error_id,
            "uuid": uuid,
            "data": result.get("data", {}),
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Error reference query failed: {str(e)[:200]}"}


async def get_comments(grawave_id: str, page=1, page_size=10) -> dict:
    """Get user comments for an observation."""
    try:
        result = await _backend_get(f"/comments/{grawave_id}", {"page": page, "size": min(page_size, 100)})
        items = result.get("data", {}).get("list", [])
        return {
            "success": True,
            "grawave_id": grawave_id,
            "total_comments": result.get("data", {}).get("total_info", {}).get("total_count", 0),
            "comments": items[:20],
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Comments query failed: {str(e)[:200]}"}


async def count_observations(telescope=None) -> dict:
    """Count observations, optionally filtered by telescope."""
    try:
        params = {"page": 1, "page_size": 1}
        if telescope: params["telescope"] = telescope
        result = await _backend_get("/geoSearch", params)
        total = result.get("data", {}).get("total_info", {}).get("total_count", 0)
        return {
            "success": True,
            "total_observations": total,
            "filter_telescope": telescope or "all",
            "_source": result.get("_gw_source", "live"),
        }
    except Exception as e:
        return {"success": False, "error": f"Count query failed: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════════════════════════
# File Analysis Tools
# ═══════════════════════════════════════════════════════════════════════════

async def list_fits_files(survey=None, limit=50) -> dict:
    """List FITS files in the data directory."""
    try:
        import glob as _glob
        pattern = os.path.join(FITS_DATA_DIR, "**", "*.fits")
        if survey:
            pattern = os.path.join(FITS_DATA_DIR, f"*{survey}*", "*.fits")

        files = []
        for fpath in _glob.glob(pattern, recursive=True):
            try:
                stat = os.stat(fpath)
                files.append({
                    "path": fpath,
                    "name": os.path.basename(fpath),
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                })
            except OSError:
                pass

        files.sort(key=lambda x: x["modified"], reverse=True)
        total = len(files)
        files = files[:min(limit, 200)]

        # Also get surveys
        surveys = set()
        for f in files:
            parts = f["path"].replace("\\", "/").split("/")
            for p in parts:
                if p.upper() in ("DSS2", "NVSS", "FIRST", "WISE", "ZTF", "LEGACY", "ALICPT"):
                    surveys.add(p.upper())

        return {
            "success": True,
            "total_files": total,
            "returned": len(files),
            "files": files,
            "detected_surveys": sorted(surveys),
            "data_directory": FITS_DATA_DIR,
        }
    except Exception as e:
        return {"success": False, "error": f"File listing failed: {str(e)[:200]}"}


async def get_fits_header(filename: str) -> dict:
    """Read FITS header metadata."""
    try:
        from astropy.io import fits as _fits
        fpath = filename if os.path.isabs(filename) else os.path.join(FITS_DATA_DIR, filename)
        if not os.path.exists(fpath):
            alt = os.path.join(FITS_DATA_DIR, os.path.basename(filename))
            if os.path.exists(alt):
                fpath = alt
            else:
                return {"success": False, "error": f"FITS file not found: {filename}"}

        with _fits.open(fpath, memmap=True) as hdul:
            header = dict(hdul[0].header)
            # Extract key astronomy fields
            wcs_keys = {}
            for key in ["CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
                        "CD1_1", "CD1_2", "CD2_1", "CD2_2", "CDELT1", "CDELT2",
                        "NAXIS1", "NAXIS2", "BUNIT", "TELESCOP", "INSTRUME",
                        "DATE-OBS", "FILTER", "BAND", "OBJECT", "RA", "DEC",
                        "EQUINOX", "RADESYS", "BMAJ", "BMIN", "BPA"]:
                if key in header:
                    wcs_keys[key] = str(header[key]) if not isinstance(header[key], (int, float, bool)) else header[key]

        return {
            "success": True,
            "filename": os.path.basename(fpath),
            "image_size": f"{header.get('NAXIS1', '?')} x {header.get('NAXIS2', '?')}",
            "wcs_info": wcs_keys,
            "total_header_keys": len(header),
        }
    except ImportError:
        return {"success": False, "error": "astropy not available for FITS header reading"}
    except Exception as e:
        return {"success": False, "error": f"FITS header read failed: {str(e)[:200]}"}


async def get_fits_stats(filename: str) -> dict:
    """Compute statistical summary of FITS image data."""
    try:
        from astropy.io import fits as _fits
        import numpy as np
        fpath = filename if os.path.isabs(filename) else os.path.join(FITS_DATA_DIR, filename)
        if not os.path.exists(fpath):
            alt = os.path.join(FITS_DATA_DIR, os.path.basename(filename))
            if os.path.exists(alt):
                fpath = alt
            else:
                return {"success": False, "error": f"FITS file not found: {filename}"}

        with _fits.open(fpath, memmap=True) as hdul:
            data = hdul[0].data
            if data is None:
                return {"success": False, "error": "FITS file has no image data"}
            d = data.astype(np.float64)
            finite = d[np.isfinite(d)]
            if len(finite) == 0:
                return {"success": False, "error": "No finite pixels in FITS data"}

            percentiles = np.percentile(finite, [1, 5, 25, 50, 75, 95, 99])
            return {
                "success": True,
                "filename": os.path.basename(fpath),
                "shape": list(data.shape),
                "statistics": {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                    "median": float(np.median(finite)),
                    "std": float(np.std(finite)),
                    "p1": float(percentiles[0]),
                    "p5": float(percentiles[1]),
                    "p25": float(percentiles[2]),
                    "p50": float(percentiles[3]),
                    "p75": float(percentiles[4]),
                    "p95": float(percentiles[5]),
                    "p99": float(percentiles[6]),
                },
                "dynamic_range": float(np.max(finite) - np.min(finite)),
                "saturated_fraction": float(np.sum(np.abs(d - np.max(finite)) < 1e-10) / len(finite)),
            }
    except ImportError as e:
        return {"success": False, "error": f"Required library not available: {e}"}
    except Exception as e:
        return {"success": False, "error": f"FITS stats failed: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════════════════════════
# DL Inference Tools (call local pipeline endpoints)
# ═══════════════════════════════════════════════════════════════════════════

async def _pipeline_post(endpoint: str, data: dict) -> dict:
    """Post to local pipeline DL endpoint."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(f"http://localhost:8200{endpoint}", json=data)
        resp.raise_for_status()
        return resp.json()


async def classify_galaxy_morphology(filename: str) -> dict:
    """Classify galaxy morphology using Zoobot ONNX model."""
    try:
        result = await _pipeline_post("/pipeline/dl/morphology", {"filename": filename})
        return {
            "success": True,
            "filename": filename,
            "morphology_class": result.get("morphology_class", "unknown"),
            "confidence": result.get("confidence", 0),
            "probabilities": result.get("probabilities", {}),
            "model": result.get("model_name", "zoobot"),
            "inference_time_ms": result.get("inference_time_ms", 0),
        }
    except Exception as e:
        return {"success": False, "error": f"Morphology classification failed: {str(e)[:200]}"}


async def classify_source_type(filename: str) -> dict:
    """Classify source type (star/galaxy/quasar)."""
    try:
        result = await _pipeline_post("/pipeline/dl/source-type", {"filename": filename})
        return {
            "success": True,
            "filename": filename,
            "source_class": result.get("source_class", "unknown"),
            "confidence": result.get("confidence", 0),
            "probabilities": result.get("probabilities", {}),
            "features_used": result.get("features_used", []),
            "model": result.get("model_name", "mlp"),
            "inference_time_ms": result.get("inference_time_ms", 0),
        }
    except Exception as e:
        return {"success": False, "error": f"Source classification failed: {str(e)[:200]}"}


async def detect_anomaly_dl(filename: str) -> dict:
    """Detect anomalies using CNN autoencoder."""
    try:
        result = await _pipeline_post("/pipeline/dl/anomaly/detect", {"filename": filename})
        return {
            "success": True,
            "filename": filename,
            "is_anomalous": result.get("is_anomalous", False),
            "anomaly_score": result.get("anomaly_score", 0),
            "reconstruction_error": result.get("reconstruction_error", 0),
            "confidence": result.get("confidence", 0),
            "verdict": result.get("verdict", "unknown"),
            "threshold_used": result.get("threshold_used", ""),
            "model": result.get("model_name", "autoencoder"),
            "inference_time_ms": result.get("inference_time_ms", 0),
        }
    except Exception as e:
        return {"success": False, "error": f"Anomaly detection failed: {str(e)[:200]}"}


async def get_dl_model_status() -> dict:
    """Get DL model status."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get("http://localhost:8200/pipeline/dl/status")
            resp.raise_for_status()
            result = resp.json()
        return {
            "success": True,
            "onnx_available": result.get("onnx_available", False),
            "models": result.get("models", []),
            "benchmark": result.get("benchmark", None),
        }
    except Exception as e:
        return {"success": False, "error": f"DL status check failed: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════════════════════════
# System Tools
# ═══════════════════════════════════════════════════════════════════════════

async def get_system_status() -> dict:
    """Get overall platform health from MCP server."""
    try:
        health = await _mcp_get("/health")
        degrade = await _mcp_get("/degrade-status")
        return {
            "success": True,
            "platform_status": health.get("status", "unknown"),
            "backend_reachable": health.get("backend_reachable", False),
            "alert_level": health.get("alert_level", "unknown"),
            "mcp_version": health.get("mcp_version", "?"),
            "data_stats": {
                "live": health.get("stats", {}).get("live", 0),
                "fallback": health.get("stats", {}).get("fallback", 0),
                "error": health.get("stats", {}).get("error", 0),
            },
            "degradation": {
                "consecutive_failures": degrade.get("consecutive_failures", 0),
                "alert_level": degrade.get("alert_level", "healthy"),
                "last_success": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(degrade.get("last_success_ts", 0))) if degrade.get("last_success_ts") else "never",
            },
        }
    except Exception as e:
        return {"success": False, "error": f"System status check failed: {str(e)[:200]}"}


async def get_pipeline_info() -> dict:
    """Get available science pipeline endpoints."""
    return {
        "success": True,
        "pipelines": {
            "wcs": {
                "endpoint": "/pipeline/wcs",
                "description": "Query WCS coordinate solution for FITS files",
                "method": "GET",
                "params": "filename, x?, y?",
            },
            "source_detection": {
                "endpoint": "/pipeline/sources",
                "description": "DAOStarFinder source detection in FITS images",
                "method": "POST",
                "params": "filename, threshold?",
            },
            "photometry": {
                "endpoint": "/pipeline/photometry",
                "description": "Aperture photometry for FITS sources",
                "method": "POST",
                "params": "filename, x, y, radius?",
            },
            "cutout": {
                "endpoint": "/pipeline/cutout",
                "description": "Extract sub-region from FITS image",
                "method": "POST",
                "params": "filename, x, y, size?",
            },
            "thumbnail": {
                "endpoint": "/pipeline/thumbnail",
                "description": "Generate PNG thumbnail from FITS",
                "method": "GET",
                "params": "filename",
            },
        },
        "note": "Use these endpoints for advanced FITS analysis. DL models are preferred for morphology/source-type classification.",
    }


async def run_wcs_query(filename: str, x=None, y=None) -> dict:
    """Query WCS solution for a FITS file."""
    try:
        from astropy.io import fits as _fits
        from astropy.wcs import WCS
        fpath = filename if os.path.isabs(filename) else os.path.join(FITS_DATA_DIR, filename)
        if not os.path.exists(fpath):
            alt = os.path.join(FITS_DATA_DIR, os.path.basename(filename))
            if os.path.exists(alt): fpath = alt
            else: return {"success": False, "error": f"FITS file not found: {filename}"}

        with _fits.open(fpath, memmap=True) as hdul:
            w = WCS(hdul[0].header)
            if x is not None and y is not None:
                sky = w.pixel_to_world(x, y)
                return {
                    "success": True, "filename": os.path.basename(fpath),
                    "pixel_input": {"x": x, "y": y},
                    "sky_output": {"ra_deg": float(sky.ra.deg), "dec_deg": float(sky.dec.deg),
                                   "ra_str": sky.ra.to_string(unit="hourangle", sep=":", precision=2),
                                   "dec_str": sky.dec.to_string(sep=":", precision=1)},
                }
            else:
                return {
                    "success": True, "filename": os.path.basename(fpath),
                    "wcs_dimensions": list(w.array_shape) if w.array_shape else None,
                    "pixel_scale": f"{abs(w.pixel_scale_matrix[0][0]*3600):.2f} arcsec/pixel" if w.pixel_scale_matrix is not None else "N/A",
                    "reference_pixel": f"({w.wcs.crpix[0]:.1f}, {w.wcs.crpix[1]:.1f})",
                    "reference_sky": f"RA={w.wcs.crval[0]:.4f}°, Dec={w.wcs.crval[1]:.4f}°",
                }
    except ImportError as e:
        return {"success": False, "error": f"Required library not available: {e}"}
    except Exception as e:
        return {"success": False, "error": f"WCS query failed: {str(e)[:200]}"}


async def get_api_docs() -> dict:
    """Get API endpoint summary."""
    return {
        "success": True,
        "platform_apis": {
            "backend": {
                "base": f"{BASE_PATH}",
                "endpoints": [
                    {"method": "GET", "path": "/geoSearch", "desc": "Search observations by RA/Dec/radius/telescope"},
                    {"method": "GET", "path": "/error", "desc": "List anomaly error reports"},
                    {"method": "GET", "path": "/error/{id}", "desc": "Get anomaly detail by ID"},
                    {"method": "GET", "path": "/error/{id}/{uuid}", "desc": "Get multi-band reference data"},
                    {"method": "GET", "path": "/comments/{grawave_id}", "desc": "Get observation comments"},
                    {"method": "POST", "path": "/comments", "desc": "Add comment to observation"},
                ],
            },
            "pipeline": {
                "base": "/pipeline",
                "endpoints": [
                    {"method": "GET", "path": "/pipeline/files", "desc": "List available FITS files"},
                    {"method": "GET", "path": "/pipeline/health", "desc": "Pipeline health check"},
                    {"method": "GET", "path": "/pipeline/dl/status", "desc": "DL model status"},
                    {"method": "POST", "path": "/pipeline/dl/morphology", "desc": "Classify galaxy morphology"},
                    {"method": "POST", "path": "/pipeline/dl/source-type", "desc": "Classify source type"},
                    {"method": "POST", "path": "/pipeline/dl/anomaly/detect", "desc": "Detect anomalies (DL)"},
                    {"method": "POST", "path": "/pipeline/agent/chat", "desc": "AI Agent chat (this service)"},
                ],
            },
            "mcp": {
                "base": "http://gw-mcp-server:8100",
                "endpoints": [
                    {"method": "GET", "path": "/health", "desc": "MCP server health"},
                    {"method": "GET", "path": "/tools", "desc": "List MCP tools"},
                    {"method": "GET", "path": "/degrade-status", "desc": "Degradation state"},
                ],
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool Registry — maps tool names to (schema, handler) pairs
# ═══════════════════════════════════════════════════════════════════════════

from .tool_schemas import ALL_TOOL_SCHEMAS

# v4.35: Tool result cache for degradation auto-sync (Fix #2)
from ..tool_cache import get_tool_cache

class ToolRegistry:
    """Registry of all available Agent tools.

    Maps tool name -> (OpenAI function schema, async handler function).
    The registry is used by AgentLoop to:
      1. Send available tool schemas to DeepSeek
      2. Dispatch tool calls to the correct handler
    """

    def __init__(self):
        self._tools: Dict[str, tuple] = {}
        self._register_all()
        # v4.35: Initialize tool cache for degradation fallback
        self._cache = get_tool_cache()

    def _register_all(self):
        """Register all tools."""
        self._tools = {
            # Database
            "search_observations": (ALL_TOOL_SCHEMAS[0], search_observations),
            "get_error_reports": (ALL_TOOL_SCHEMAS[1], get_error_reports),
            "get_error_detail": (ALL_TOOL_SCHEMAS[2], get_error_detail),
            "get_error_reference": (ALL_TOOL_SCHEMAS[3], get_error_reference),
            "get_comments": (ALL_TOOL_SCHEMAS[4], get_comments),
            "count_observations": (ALL_TOOL_SCHEMAS[5], count_observations),
            # File analysis
            "list_fits_files": (ALL_TOOL_SCHEMAS[6], list_fits_files),
            "get_fits_header": (ALL_TOOL_SCHEMAS[7], get_fits_header),
            "get_fits_stats": (ALL_TOOL_SCHEMAS[8], get_fits_stats),
            # DL inference
            "classify_galaxy_morphology": (ALL_TOOL_SCHEMAS[9], classify_galaxy_morphology),
            "classify_source_type": (ALL_TOOL_SCHEMAS[10], classify_source_type),
            "detect_anomaly_dl": (ALL_TOOL_SCHEMAS[11], detect_anomaly_dl),
            "get_dl_model_status": (ALL_TOOL_SCHEMAS[12], get_dl_model_status),
            # System
            "get_system_status": (ALL_TOOL_SCHEMAS[13], get_system_status),
            "get_pipeline_info": (ALL_TOOL_SCHEMAS[14], get_pipeline_info),
            "run_wcs_query": (ALL_TOOL_SCHEMAS[15], run_wcs_query),
            "get_api_docs": (ALL_TOOL_SCHEMAS[16], get_api_docs),
        }

    def get_schemas(self) -> list:
        """Return all tool schemas for the DeepSeek API call."""
        return [schema for schema, _ in self._tools.values()]

    def get_handler(self, name: str):
        """Get the async handler function for a tool name."""
        entry = self._tools.get(name)
        return entry[1] if entry else None

    async def execute(self, name: str, arguments: dict) -> dict:
        """Execute a tool by name with given arguments.

        Returns a result dict with at minimum {success: bool, ...}.
        Errors are caught and returned as {success: False, error: str}.
        """
        handler = self.get_handler(name)
        if handler is None:
            return {"success": False, "error": f"Unknown tool: {name}"}

        # v4.35: Validate parameters before execution (Fix #5)
        validator = _TOOL_VALIDATORS.get(name)
        if validator:
            try:
                errors = validator(**arguments)
                if errors:
                    _log.warning("Tool %s validation failed: %s", name, errors)
                    return {
                        "success": False,
                        "error": "Parameter validation failed: " + "; ".join(errors),
                        "_tool_name": name,
                    }
            except Exception as val_err:
                _log.warning("Tool %s validator error: %s", name, val_err)

        _log.info("Tool call: %s(%s)", name,
                  ", ".join(f"{k}={str(v)[:50]}" for k, v in arguments.items()))

        t_start = time.monotonic()
        try:
            # v4.35: Route through cache for degradation fallback (Fix #2)
            result = await self._cache.get_or_fetch(name, arguments, handler)
            elapsed_ms = round((time.monotonic() - t_start) * 1000, 1)
            result["_tool_name"] = name
            result["_execution_time_ms"] = elapsed_ms
            _log.info("Tool %s completed in %sms (success=%s)", name, elapsed_ms, result.get("success"))
            return result
        except TypeError as e:
            _log.error("Tool %s bad arguments: %s", name, e)
            return {"success": False, "error": f"Invalid arguments for {name}: {str(e)[:200]}",
                    "_tool_name": name}
        except Exception as e:
            _log.error("Tool %s execution error: %s", name, e)
            return {"success": False, "error": f"Tool {name} execution error: {str(e)[:200]}",
                    "_tool_name": name}

    @property
    def cache_stats(self) -> dict:
        """v4.35: Return tool cache statistics."""
        return self._cache.stats

    @property
    def tool_names(self) -> list:
        return sorted(self._tools.keys())

    @property
    def tool_count(self) -> int:
        return len(self._tools)


# Singleton
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the singleton ToolRegistry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
