"""
Detector registry + classify_anomalies() entry point (R6.24+).

The registry is populated eagerly at import time. Adding a new detector
means: create a new file in this package subclassing AnomalyDetector, then
register it here.

`classify_anomalies()` keeps the legacy function-call signature so existing
callers (server.py endpoints, batch_scheduler) need no changes.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from pipeline.anomaly.base import AnomalyDetector, AnomalyResult
from pipeline.anomaly.dip import DipDetector
from pipeline.anomaly.pattern_break import PatternBreakDetector
from pipeline.anomaly.spike import SpikeDetector
from pipeline.anomaly.wcs import WcsMismatchDetector


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DETECTOR_REGISTRY: dict[str, AnomalyDetector] = {
    cls.name: cls()
    for cls in (SpikeDetector, DipDetector, PatternBreakDetector, WcsMismatchDetector)
}


def load_detectors(names: list[str] | None = None) -> list[AnomalyDetector]:
    """Return detector instances matching *names* (or all if None).

    Useful for A/B testing: `load_detectors(["spike", "wcs"])` to run only two.
    Unknown names raise KeyError with a helpful message.
    """
    if names is None:
        return list(DETECTOR_REGISTRY.values())
    missing = [n for n in names if n not in DETECTOR_REGISTRY]
    if missing:
        raise KeyError(
            f"Unknown detector(s) {missing}; available: {sorted(DETECTOR_REGISTRY)}"
        )
    return [DETECTOR_REGISTRY[n] for n in names]


# ---------------------------------------------------------------------------
# Public entry point (backward-compatible with anomaly_classifier.classify_anomalies)
# ---------------------------------------------------------------------------

def classify_anomalies(
    data: NDArray,
    wcs: Any | None = None,
    *,
    spike_sigma: float = 5.0,
    dip_sigma: float = 5.0,
    pattern_break_sigma: float = 4.0,
    wcs_max_pixel_scale_deg: float = 1.0,
    detectors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run all (or specified) detectors and return results as list-of-dicts.

    Args:
        data: 2-D numpy array of pixel values.
        wcs: Optional WCS object (astropy.wcs.WCS, dict, etc.).
        spike_sigma, dip_sigma, pattern_break_sigma: detection thresholds.
        wcs_max_pixel_scale_deg: see WcsMismatchDetector.
        detectors: subset of detector names; None means all four.

    Returns:
        List of dicts (one per detector), each with keys:
            type, confidence, pixel_regions, description, wcs_issues.
        Output schema matches legacy anomaly_classifier.classify_anomalies.
    """
    instances = load_detectors(detectors)
    per_kwargs = {
        "spike": {"sigma": spike_sigma},
        "dip": {"sigma": dip_sigma},
        "pattern_break": {"sigma": pattern_break_sigma},
        "wcs_mismatch": {"max_pixel_scale_deg": wcs_max_pixel_scale_deg},
    }
    out: list[dict[str, Any]] = []
    for det in instances:
        kwargs = per_kwargs.get(det.name, {})
        result: AnomalyResult = det.detect(data, wcs, **kwargs)
        out.append(result.to_dict())
    return out


__all__ = [
    "DETECTOR_REGISTRY",
    "load_detectors",
    "classify_anomalies",
]
