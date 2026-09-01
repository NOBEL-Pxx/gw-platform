"""
Routes package (R6.24+) -- server.py modularization.

server.py currently mixes 59 endpoints across many concerns:
    - /health, /version, /metrics                        -> ops/util
    - /observations, /observations/{id}                  -> observation
    - /fits/info, /fits/wcs, /fits/source-extract         -> fits
    - /dl/anomaly, /dl/classify, /dl/inference            -> dl
    - /llm/chat, /llm/agent, /llm/tools                  -> llm
    - /audit, /secrets, /rbac                            -> ops

Target split (R6.24 establishes the boundary; full move happens in R6.24.1+):

    observation.py   -- observation list + CRUD + filters
    fits.py          -- FITS info / WCS / source extraction / upload
    llm.py           -- LLM proxy + agent loop + tool dispatch
    dl.py            -- DL inference + anomaly classifier dispatch
    (ops/util kept in server.py for now; future R6.25+)

Each routes/<x>.py exposes a single `router` (FastAPI APIRouter) so server.py
becomes:

    from pipeline.routes import fits, llm, dl, observation
    app.include_router(observation.router, prefix="/observations", tags=["observation"])
    app.include_router(fits.router,        prefix="/fits",        tags=["fits"])
    app.include_router(dl.router,          prefix="/dl",          tags=["dl"])
    app.include_router(llm.router,         prefix="/llm",         tags=["llm"])

Strangler fig: this PR keeps every endpoint in server.py working unchanged.
The new modules currently only re-export helper functions (no router yet).
Follow-up PRs (R6.24.1, R6.24.2, ...) move one endpoint family at a time,
keeping server.py bootable after each move.
"""
from __future__ import annotations

from pipeline.routes.fits import fits_helpers
from pipeline.routes.llm import llm_helpers
from pipeline.routes.dl import dl_helpers
from pipeline.routes.observation import observation_helpers


__all__ = [
    "fits_helpers",
    "llm_helpers",
    "dl_helpers",
    "observation_helpers",
]
