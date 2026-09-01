"""
FITS routes (R6.24+) -- FITS file info / WCS / source extraction / upload.

Endpoints planned for this module:
    GET  /fits/info/{obs_id}        -- header keywords + dimensions + BUNIT
    GET  /fits/wcs/{obs_id}         -- WCS solution (CRVAL/CD matrix as JSON)
    POST /fits/source-extract       -- DAOStarFinder / SEP source extraction
    POST /fits/upload               -- multipart upload + thumb generation
    GET  /fits/{obs_id}/thumb       -- thumbnail (140x140 raw <img>)

Helpers exported:
    fits_helpers.parse_header_keywords()
    fits_helpers.validate_wcs_solution()
    fits_helpers.compute_thumbnail_url()

Why split fits second (after observation):
- Heavy computation (astropy.io.fits, sep) -- deserves its own resource budget
- Separate CPU profile from LLM proxy calls (which block on network I/O)
- Source extraction can be cached independently of observation CRUD
"""
from __future__ import annotations

from typing import Any


class _FitsHelpers:
    """Namespace for FITS-related pure functions."""

    def parse_header_keywords(self, header_bytes: bytes) -> dict[str, Any]:
        from pipeline.server import parse_header_keywords
        return parse_header_keywords(header_bytes)

    def validate_wcs_solution(self, wcs_dict: dict[str, Any]) -> list[str]:
        from pipeline.server import validate_wcs_solution
        return validate_wcs_solution(wcs_dict)

    def compute_thumbnail_url(self, obs_id: str, band: str) -> str:
        from pipeline.server import compute_thumbnail_url
        return compute_thumbnail_url(obs_id, band)


fits_helpers = _FitsHelpers()


try:
    from fastapi import APIRouter
    router = APIRouter()
    # R6.24.2: @router.get("/info/{obs_id}") etc.
except ImportError:
    router = None


__all__ = ["fits_helpers", "router"]
