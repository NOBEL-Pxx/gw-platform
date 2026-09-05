"""FastAPI HTTP server for debugging, standalone access, and custom AI model integration.

v4.16: Added degradation-status endpoint, per-response source metadata headers.
       All responses now include X-GW-Source header for quality transparency.
"""
import os, time
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from gw_client import GWClient, degrade_state
from typing import Optional
import uvicorn

app = FastAPI(title="GW MCP Server", version="1.0.0")
client = GWClient()

# ── Validation helpers ────────────────────────────────────────────
def _validate_ra(ra: Optional[float]) -> None:
    if ra is not None and (ra < 0 or ra > 360):
        raise HTTPException(400, f"Invalid RA={ra}: must be 0-360 degrees")

def _validate_dec(dec: Optional[float]) -> None:
    if dec is not None and (dec < -90 or dec > 90):
        raise HTTPException(400, f"Invalid Dec={dec}: must be -90 to +90 degrees")

def _validate_radius(radius: float) -> None:
    if radius < 0 or radius > 180:
        raise HTTPException(400, f"Invalid radius={radius}: must be 0-180 degrees")

def _validate_page(page: int) -> None:
    if page < 1:
        raise HTTPException(400, f"Invalid page={page}: must be >= 1")

def _validate_str_len(value: str, max_len: int, field: str) -> None:
    if len(value) > max_len:
        raise HTTPException(400, f"{field} too long: {len(value)} chars (max {max_len})")


@app.middleware("http")
async def add_degrade_header(request: Request, call_next):
    """Inject X-GW-Alert header into every response for client-side monitoring."""
    response = await call_next(request)
    response.headers["X-GW-Alert"] = degrade_state.alert_level
    response.headers["X-GW-Version"] = "v4.16"
    return response


# ── Health & Diagnostics ────────────────────────────────────────────

@app.get("/health")
async def health():
    """Deep health check — verifies backend connectivity + MCP degradation state."""
    hc = await client.health_check()
    return {
        "status": "ok" if hc["backend_reachable"] else "degraded",
        "mcp_version": "v4.28",
        "backend": client.base_url,
        "mock": client._use_mock,
        "backend_reachable": hc["backend_reachable"],
        "alert_level": hc["alert_level"],
        "consecutive_failures": hc["consecutive_failures"],
        "stats": {
            "live": hc["live_count"],
            "fallback": hc["fallback_count"],
            "mock": hc["mock_count"],
            "error": hc["error_count"],
            "total": hc["total_requests"],
        },
    }


@app.get("/degrade-status")
async def degrade_status():
    """Full degradation state: alert level, per-endpoint failure counts,
    data-source breakdown. Use to monitor MCP health independently."""
    return client.degrade_status()


@app.get("/tools")
async def list_tools():
    return {"tools": [
        "search_observations", "get_error_reports", "get_error_detail",
        "get_error_reference", "get_comments", "add_comment",
        "get_system_status"
    ]}


@app.get("/alive")
async def alive():
    """Minimal liveness probe — no backend check, returns immediately."""
    return {"alive": True, "version": "v4.28"}


# ── API passthrough (matches Spring Boot paths) ──────────────────────

@app.get("/api/app/gravitationalwave/geoSearch")
async def geo_search(ra: Optional[float]=None, dec: Optional[float]=None,
    radius: float=1.0, telescope: Optional[str]=None,
    page: int=1, page_size: int=10):
    _validate_ra(ra)
    _validate_dec(dec)
    _validate_radius(radius)
    _validate_page(page)
    if telescope and len(telescope) > 50:
        raise HTTPException(400, f"telescope too long: {len(telescope)} chars (max 50)")
    return await client.search_observations(
        ra=ra, dec=dec, radius=radius, telescope=telescope,
        page=page, page_size=page_size)


@app.get("/api/app/gravitationalwave/error")
async def error_reports(page: int=1, page_size: int=10):
    _validate_page(page)
    return await client.get_error_reports(page=page, page_size=page_size)


@app.get("/api/app/gravitationalwave/error/{error_id}")
async def error_detail(error_id: str, page: int=1, page_size: int=10):
    _validate_page(page)
    _validate_str_len(error_id, 256, "error_id")
    result = await client.get_error_detail(error_id, page=page, page_size=page_size)
    # Extract logContent from first detail item to response top level
    items = result.get("data", {}).get("list", [])
    if items and "logContent" in items[0] and "logContent" not in result.get("data", {}):
        result["data"]["logContent"] = items[0].get("logContent", "")
    return result


@app.get("/api/app/gravitationalwave/error/{error_id}/{uuid}")
async def error_reference(error_id: str, uuid: str):
    _validate_str_len(error_id, 256, "error_id")
    _validate_str_len(uuid, 256, "uuid")
    return await client.get_error_reference(error_id, uuid)


@app.get("/api/app/gravitationalwave/comments/{grawave_id}")
async def comments(grawave_id: str, page: int=1, size: int=10):
    _validate_page(page)
    _validate_str_len(grawave_id, 256, "grawave_id")
    return await client.get_comments(grawave_id, page=page, size=size)


@app.post("/api/app/gravitationalwave/comments")
async def add_comment(data: dict):
    grawave_id = data.get("grawaveId", "")
    content = data.get("content", "")
    user_id = data.get("userId", "")
    category = data.get("category", "analysis")
    if not grawave_id or not grawave_id.strip():
        raise HTTPException(400, "grawaveId is required")
    _validate_str_len(grawave_id, 256, "grawaveId")
    _validate_str_len(content, 10000, "content")
    _validate_str_len(user_id, 256, "userId")
    _validate_str_len(category, 50, "category")
    return await client.add_comment(grawave_id, content, user_id, category)


# ── Static files placeholder ──

@app.get("/static-files/{file_path:path}")
async def static_files(file_path: str):
    return {"message": f"Static files not available in mock mode: {file_path}"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)
