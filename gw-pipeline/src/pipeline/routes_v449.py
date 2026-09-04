# R6.49: Alert routing audit log endpoints.
# Registered via register_routes_v449(app) in server.py.

from typing import Optional
from fastapi import APIRouter, Header, Query
from .observability import query_alert_routing_audit


def register_routes_v449(app):
    router = APIRouter()

    @router.get("/pipeline/observability/alert-routing/audit")
    def get_audit(
        family: Optional[str] = Query(None, description="Filter by font family"),
        limit: int = Query(100, ge=1, le=500),
        since_ms: Optional[int] = Query(None, description="Only entries with ts >= since_ms"),
        cursor: Optional[str] = Query(None, description="R6.51 opaque cursor from prior page"),
    ):
        """R6.51: Cursor-paginated audit log (returns dict with next_cursor)."""
        return query_alert_routing_audit(family=family, limit=limit, since_ms=since_ms, cursor=cursor)

    app.include_router(router)
