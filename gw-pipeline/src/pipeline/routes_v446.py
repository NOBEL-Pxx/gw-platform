"""
R6.46: AB history + Alert endpoints.

Adds 3 endpoints to the FastAPI app:
  GET /pipeline/observability/ab-history     -- bucketed time-series
  GET /pipeline/observability/alerts         -- active + recent alerts
  POST /pipeline/observability/alerts/{id}/dismiss  -- manual dismiss

Why these endpoints (vs Sentry-style alerts):
- Lab has no Sentry account
- Backend observability is the single source of truth (R6.44)
- Alerts page reuses existing dashboard infrastructure
- PagerDuty Events API v2 integration is optional (env-gated)

Usage: Import in server.py and call register_routes_v446(app)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("gw.routes-v446")


def register_routes(app):
    """Register all R6.46 routes on the FastAPI app."""

    # ═════════════════════════════════════════════════════════════════════
    # R6.46 todo 1: AB metric time-series history (chart data)
    # ═════════════════════════════════════════════════════════════════════

    @app.get("/pipeline/observability/ab-history")
    async def get_ab_history(
        request: Request,
        bucket_ms: int = Query(
            default=3600000, ge=60_000, le=86_400_000,
            description="Bucket size in ms (1min..1day)",
        ),
        window_ms: int = Query(
            default=7 * 86_400_000, ge=3_600_000, le=30 * 86_400_000,
            description="Lookback window in ms (1h..30d)",
        ),
    ):
        """Return bucketed AB metrics for charting winner drift over time.

        Default bucket=1h, window=7d (168 buckets). Each bucket contains
        per-group counts + median/avg load time + winner + delta_ms.
        """
        try:
            from .observability import query_ab_history
            return query_ab_history(bucket_ms=bucket_ms, window_ms=window_ms)
        except ImportError as e:
            return JSONResponse(
                {"error": f"observability not available: {e}"},
                status_code=500,
            )

    # ═════════════════════════════════════════════════════════════════════
    # R6.46 todo 2: Active alerts + manual dismiss
    # ═════════════════════════════════════════════════════════════════════

    @app.get("/pipeline/observability/alerts")
    async def get_alerts(
        request: Request,
        active_only: bool = Query(
            default=True,
            description="If true, only return alerts that haven't been dismissed",
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        """Return active or all alerts.

        Each alert entry:
        {
          id, type, alert_key, severity, message, fired_at, dismissed_at,
          last_value, occurrences
        }
        """
        try:
            from .observability import query_alerts
            alerts = query_alerts(active_only=active_only, limit=limit)
            return {
                "alerts": alerts,
                "count": len(alerts),
                "active_only": active_only,
            }
        except ImportError as e:
            return JSONResponse(
                {"error": f"observability not available: {e}"},
                status_code=500,
            )

    @app.post("/pipeline/observability/alerts/{alert_id}/dismiss")
    async def dismiss_alert_endpoint(request: Request, alert_id: int):
        """Manually dismiss an active alert.

        Returns:
        {
          dismissed: bool,
          alert_id: int,
          dismissed_at: int  # epoch ms (only if dismissed)
        }
        """
        try:
            from .observability import dismiss_alert
            result = dismiss_alert(alert_id)
            if not result.get("dismissed"):
                return JSONResponse(result, status_code=404)
            return result
        except ImportError as e:
            return JSONResponse(
                {"error": f"observability not available: {e}"},
                status_code=500,
            )

    logger.info(
        "R6.46 routes registered: ab-history (GET), alerts (GET/dismiss)"
    )
