"""
WcsMismatchDetector -- CRVAL/CD matrix sanity checks.

R6.24 refactor: extracted from anomaly_classifier.wcs_mismatch_detector.
The detector logic is unchanged.

The detector takes the WCS header (astropy.wcs.WCS or dict-like) as a separate
input from the pixel data, since WCS validation is metadata-only.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from pipeline.anomaly.base import AnomalyDetector, AnomalyResult


class WcsMismatchDetector(AnomalyDetector):
    """Validate WCS metadata: CRVAL, CD matrix, pixel scale."""

    name = "wcs_mismatch"

    def detect(
        self,
        data: NDArray,
        wcs: Any | None = None,
        *,
        max_pixel_scale_deg: float = 1.0,  # > 1 deg/pixel = suspicious
        cd_determinant_tol: float = 0.5,   # |det| outside [1-tol, 1+tol] = bad
    ) -> AnomalyResult:
        if wcs is None:
            return AnomalyResult(
                type=self.name,
                confidence=0.0,
                description="No WCS metadata provided",
                wcs_issues=[],
            )

        issues: list[dict[str, Any]] = []

        # Extract fields -- support both astropy.wcs.WCS and dict-like
        def _get(key: str, default: Any = None) -> Any:
            if hasattr(wcs, key):
                return getattr(wcs, key)
            if hasattr(wcs, "wcs"):
                # astropy.wcs.WCS exposes .wcs.<attr>
                inner = getattr(wcs, "wcs", None)
                if inner is not None and hasattr(inner, key):
                    return getattr(inner, key)
            if isinstance(wcs, dict):
                return wcs.get(key, default)
            return default

        crval = _get("crval")
        cdelt = _get("cdelt")
        cd = _get("cd")
        # astropy uses `cd` attribute on WCS object, but for older versions
        # use `pc` matrix and `cdelt` separately
        pc = _get("pc")
        if cd is None and pc is not None and cdelt is not None:
            cd = pc * cdelt  # approximate combined scaling

        # ----- pixel scale check -----
        pixel_scale = None
        if cd is not None:
            try:
                cd_arr = np.asarray(cd, dtype=np.float64)
                # mean absolute value of the diagonal-ish scale
                pixel_scale = float(np.sqrt(abs(np.linalg.det(cd_arr))))
            except Exception:
                pixel_scale = None
        elif cdelt is not None:
            try:
                cdelt_arr = np.asarray(cdelt, dtype=np.float64)
                pixel_scale = float(np.sqrt(abs(float(np.prod(cdelt_arr)))))
            except Exception:
                pixel_scale = None

        if pixel_scale is not None and pixel_scale > max_pixel_scale_deg:
            issues.append({
                "field": "pixel_scale",
                "value": pixel_scale,
                "threshold": max_pixel_scale_deg,
                "severity": "high",
                "message": (
                    f"Pixel scale {pixel_scale:.4f} deg/pix exceeds "
                    f"{max_pixel_scale_deg:.4f} deg/pix threshold"
                ),
            })

        # ----- CD determinant sanity -----
        if cd is not None:
            try:
                cd_arr = np.asarray(cd, dtype=np.float64)
                det = float(np.linalg.det(cd_arr))
                if not (1 - cd_determinant_tol <= abs(det) <= 1 + cd_determinant_tol):
                    issues.append({
                        "field": "cd_determinant",
                        "value": det,
                        "threshold": f"[{1 - cd_determinant_tol}, {1 + cd_determinant_tol}]",
                        "severity": "medium",
                        "message": f"CD determinant {det:.4f} outside expected range",
                    })
            except Exception:
                pass

        # ----- CRVAL plausibility -----
        if crval is not None:
            try:
                crval_arr = np.asarray(crval, dtype=np.float64)
                if np.any(np.abs(crval_arr) > 360.0):
                    issues.append({
                        "field": "crval",
                        "value": crval_arr.tolist(),
                        "threshold": "[-360, 360]",
                        "severity": "high",
                        "message": f"CRVAL {crval_arr.tolist()} outside plausible range",
                    })
            except Exception:
                pass

        if not issues:
            desc = "WCS metadata within expected tolerances"
            confidence = 0.0
        else:
            desc = f"{len(issues)} WCS issue(s) detected: " + "; ".join(
                i["message"] for i in issues
            )
            # High severity = high confidence in mismatch
            high_count = sum(1 for i in issues if i.get("severity") == "high")
            confidence = round(min(1.0, 0.4 + 0.3 * high_count + 0.1 * len(issues)), 3)

        return AnomalyResult(
            type=self.name,
            confidence=confidence,
            pixel_regions=[],
            description=desc,
            wcs_issues=issues,
        )
