"""
Observation routes (R6.24+) -- error report list / CRUD / filters.

Current state: endpoints live in server.py. This file establishes the
migration target. R6.24.1 will move the first endpoint here.

Endpoints planned for this module (extracted from server.py):
    GET  /observations              -- paginated list with filters
    GET  /observations/{id}         -- single report detail
    POST /observations              -- create new report
    PUT  /observations/{id}         -- update report
    DELETE /observations/{id}       -- soft-delete (audit-logged)
    GET  /observations/{id}/history -- full audit trail

Helpers exported (legacy code paths still work):
    observation_helpers.filter_by_date_range()
    observation_helpers.filter_by_anomaly_type()
    observation_helpers.compute_aggregate_stats()

Why split observation first:
- Highest read traffic (the /index dashboard loads this on every page open)
- Independent data model (no FITS/WCS/DL coupling)
- Easy to test in isolation (mocks for ES/Mongo only)
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers -- currently re-exported from server.py; will absorb logic in R6.24.1
# ---------------------------------------------------------------------------

class _ObservationHelpers:
    """Namespace for observation-related pure functions.

    Until R6.24.1 moves the implementations here, this delegates to the
    legacy server.py module-level functions via late binding.
    """

    def filter_by_date_range(self, items: list[dict[str, Any]],
                              start: str, end: str) -> list[dict[str, Any]]:
        from pipeline.server import filter_by_date_range
        return filter_by_date_range(items, start, end)

    def filter_by_anomaly_type(self, items: list[dict[str, Any]],
                                anomaly_type: str) -> list[dict[str, Any]]:
        from pipeline.server import filter_by_anomaly_type
        return filter_by_anomaly_type(items, anomaly_type)

    def compute_aggregate_stats(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        from pipeline.server import compute_aggregate_stats
        return compute_aggregate_stats(items)


observation_helpers = _ObservationHelpers()


# ---------------------------------------------------------------------------
# Router placeholder (R6.24.1 will add endpoints here)
# ---------------------------------------------------------------------------

try:
    from fastapi import APIRouter
    router = APIRouter()
    # R6.24.1: @router.get("/") / @router.get("/{obs_id}") etc.
except ImportError:
    router = None  # FastAPI not installed in dev env; CI catches this


__all__ = ["observation_helpers", "router"]
