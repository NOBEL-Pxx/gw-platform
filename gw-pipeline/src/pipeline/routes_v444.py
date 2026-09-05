"""
R6.44: Observability Routes (Font errors + A/B test dashboard)

New endpoints registered on the FastAPI app:
  ── Todo 1: Font error monitoring (real backend, replaces localStorage) ──
  POST /pipeline/observability/font-errors      -- record one font load error
  GET  /pipeline/observability/font-errors      -- list recent errors
  GET  /pipeline/observability/font-errors/stats -- aggregate by family+weight
  GET  /pipeline/observability/health           -- sanity check (DB size, counts)

  ── Todo 3: A/B test backend dashboard ──
  POST /pipeline/observability/ab-metrics       -- record one A/B sample
  GET  /pipeline/observability/ab-dashboard     -- aggregate (median/p95/winner)

Why these endpoints exist (vs Sentry SDK):
- Lab deployment with no external DSN
- Need full data ownership (compliance + reproducibility)
- Local file system already mounted via Docker volume
- Research platform needs raw data export for papers

Usage: Import in server.py and call register_routes(app)
"""

from __future__ import annotations

import logging
import time as _time
from typing import Any, Optional

from fastapi import Request, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("gw.routes-v444")


def register_routes(app):
    """Register all R6.44 observability routes on the FastAPI app."""

    # ═════════════════════════════════════════════════════════════════════
    # R6.44 todo 1: Font error monitoring (replaces localStorage fallback)
    # ═════════════════════════════════════════════════════════════════════

    @app.post("/pipeline/observability/font-errors")
    async def post_font_error(request: Request):
        """Record a font-load error from frontend useFontMonitor.

        Body: {family, weight, src, url, userAgent, timestamp?}
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        family = (body.get("family") or "").strip()
        weight = (body.get("weight") or "").strip()
        if not family:
            return JSONResponse({"error": "family required"}, status_code=400)

        try:
            from .observability import record_font_error
            result = record_font_error(
                family=family,
                weight=weight or "unknown",
                src=body.get("src") or "",
                url=body.get("url") or "",
                user_agent=body.get("userAgent") or "",
                timestamp=body.get("timestamp"),
            )
            return result
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.get("/pipeline/observability/font-errors")
    async def get_font_errors(
        request: Request,
        family: Optional[str] = Query(default=None, description="Filter by font family"),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        """List recent font errors (newest first)."""
        try:
            from .observability import query_font_errors
            rows = query_font_errors(family=family, limit=limit)
            return {"errors": rows, "count": len(rows)}
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    @app.get("/pipeline/observability/font-errors/stats")
    async def get_font_error_stats(request: Request):
        """Aggregate font errors by family + weight."""
        try:
            from .observability import query_font_error_stats
            return query_font_error_stats()
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    @app.get("/pipeline/observability/health")
    async def get_observability_health(request: Request):
        """Sanity check: DB size + record counts."""
        try:
            from .observability import get_observability_health
            return get_observability_health()
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    # ═════════════════════════════════════════════════════════════════════
    # R6.44 todo 3: A/B test backend dashboard
    # ═════════════════════════════════════════════════════════════════════

    @app.post("/pipeline/observability/ab-metrics")
    async def post_ab_metric(request: Request):
        """Record one A/B test sample from frontend useFontABTest.

        Body: {group, loadTimeMs, fcp, cls, page?, userId?, timestamp?}
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        group = (body.get("group") or body.get("group_name") or "").strip()
        if group not in ("woff2", "system"):
            return JSONResponse(
                {"error": "group must be 'woff2' or 'system'"}, status_code=400,
            )

        try:
            from .observability import record_ab_metric
            result = record_ab_metric(
                group_name=group,
                load_time_ms=body.get("loadTimeMs") or body.get("load_time_ms"),
                fcp=body.get("fcp"),
                cls=body.get("cls"),
                page=body.get("page") or "",
                user_id=body.get("userId") or body.get("user_id") or "",
                timestamp=body.get("timestamp"),
            )
            return result
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.get("/pipeline/observability/ab-dashboard")
    async def get_ab_dashboard(request: Request):
        """R6.44 todo 3: backend A/B test dashboard.

        Returns aggregate metrics per group (count/avg/median/p95 for
        load_time_ms, fcp_ms, cls). Reports a winner if one group is
        at least 5% faster by median with n>=30 samples each.
        """
        try:
            from .observability import query_ab_dashboard
            return query_ab_dashboard()
        except ImportError as e:
            return JSONResponse({"error": f"observability not available: {e}"}, status_code=500)

    logger.info(
        "R6.44 observability routes registered: font-errors (POST/GET), "
        "ab-metrics (POST), ab-dashboard (GET)"
    )
