"""
R6.47: Alert routing management endpoints.

Adds 3 endpoints for managing per-family PagerDuty routing keys:
  GET    /pipeline/observability/alert-routing         -- list all
  PUT    /pipeline/observability/alert-routing         -- upsert one
  DELETE /pipeline/observability/alert-routing/{family} -- delete one

Multi-tenant logic:
- Priority: PAGERDUTY_ROUTING_TABLE env (per-family) > DB row > default _PAGERDUTY_ROUTING_KEY
- DB rows take precedence over env (allow runtime updates without restart)
- Deleting a DB row falls back to env or default

Usage: Import in server.py and call register_routes_v447(app)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("gw.routes-v447")


class AlertRoutingUpsert(BaseModel):
    family: str = Field(..., min_length=1, max_length=128, description="Font family name")
    pagerduty_routing_key: str = Field(..., min_length=1, max_length=256)
    team_email: Optional[str] = Field(default="", max_length=256)


def register_routes(app):
    """Register all R6.47 routes on the FastAPI app."""

    @app.get("/pipeline/observability/alert-routing")
    async def list_alert_routing(request: Request):
        """List all DB-stored family -> PagerDuty routing mappings."""
        try:
            from .observability import get_alert_routing
            rows = get_alert_routing()
            return {"routing": rows, "count": len(rows)}
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    @app.put("/pipeline/observability/alert-routing")
    async def upsert_alert_routing_endpoint(request: Request, body: AlertRoutingUpsert):
        """Insert or update routing for a font family. Idempotent."""
        try:
            from .observability import upsert_alert_routing
            return upsert_alert_routing(
                family=body.family,
                pagerduty_routing_key=body.pagerduty_routing_key,
                team_email=body.team_email or "",
            )
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    @app.delete("/pipeline/observability/alert-routing/{family}")
    async def delete_alert_routing_endpoint(request: Request, family: str):
        """Remove a routing entry. Subsequent alerts fall back to default routing key."""
        try:
            from .observability import delete_alert_routing
            result = delete_alert_routing(family)
            if not result.get("deleted"):
                return JSONResponse(result, status_code=404)
            return result
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    logger.info("R6.47 routes registered: alert-routing (GET/PUT/DELETE)")
