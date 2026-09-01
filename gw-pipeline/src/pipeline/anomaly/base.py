"""
AnomalyDetector abstract base class + shared types (R6.24+).

This module defines the contract every concrete detector must satisfy.
Adding a new anomaly type = subclass AnomalyDetector + add to registry.py.

The base class intentionally keeps state minimal: each detector instance is
stateless w.r.t. the input image, so they can be safely reused across requests
(thread-safe under the FastAPI sync threadpool).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as scipy_ndimage


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

@dataclass
class PixelRegion:
    """A connected cluster of anomalous pixels."""
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    peak_value: float
    snr: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "peak_value": self.peak_value,
            "snr": round(self.snr, 2),
        }


@dataclass
class AnomalyResult:
    """Standardized output of every detector."""
    type: str
    confidence: float
    pixel_regions: list[PixelRegion] = field(default_factory=list)
    description: str = ""
    wcs_issues: list[dict[str, Any]] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type,
            "confidence": self.confidence,
            "pixel_regions": [r.to_dict() for r in self.pixel_regions],
            "description": self.description,
            "wcs_issues": list(self.wcs_issues),
        }
        out.update(self.extras)  # detector-specific fields merged at top level
        return out


# ---------------------------------------------------------------------------
# Shared helpers (formerly private functions in anomaly_classifier.py)
# ---------------------------------------------------------------------------

def local_stats(
    data: NDArray,
    window_size: int = 64,
) -> tuple[NDArray, NDArray]:
    """Per-pixel local background (mean) and std via a sliding window.

    O(N) via scipy.ndimage.uniform_filter. 5-sigma+ detectors don\'t need a
    full median estimator -- mean + running variance is enough.
    """
    work = data.astype(np.float64)
    local_mean = scipy_ndimage.uniform_filter(work, size=window_size)
    mean_sq = scipy_ndimage.uniform_filter(work ** 2, size=window_size)
    local_std = np.sqrt(np.maximum(mean_sq - local_mean ** 2, 0.0))
    return local_mean, local_std


def extract_regions(
    mask: NDArray,
    data: NDArray,
    local_mean: NDArray,
    local_std: NDArray,
    min_pixels: int = 2,
) -> list[PixelRegion]:
    """Cluster connected pixels from a boolean mask into PixelRegion objects."""
    labeled, n_features = scipy_ndimage.label(mask)
    if n_features == 0:
        return []

    regions: list[PixelRegion] = []
    for label_id in range(1, n_features + 1):
        ys, xs = np.where(labeled == label_id)
        if len(ys) < min_pixels:
            continue
        peak_value = float(np.max(data[ys, xs]))
        bg_std = float(np.mean(local_std[ys, xs]))
        bg_median = float(np.mean(local_mean[ys, xs]))
        snr = (peak_value - bg_median) / max(bg_std, 1e-9)
        regions.append(
            PixelRegion(
                x_min=int(np.min(xs)),
                x_max=int(np.max(xs)),
                y_min=int(np.min(ys)),
                y_max=int(np.max(ys)),
                peak_value=peak_value,
                snr=snr,
            )
        )
    regions.sort(key=lambda r: r.snr, reverse=True)
    return regions


def confidence_from_snrs(snr_values: list[float], threshold: float) -> float:
    """Map the best-region SNR to [0, 1] via a soft ramp above threshold."""
    if not snr_values:
        return 0.0
    best = max(snr_values)
    if best <= threshold:
        return 0.0
    return round(min(1.0, (best - threshold) / (3.0 * threshold)), 3)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class AnomalyDetector(ABC):
    """Strategy interface for one anomaly type.

    Concrete detectors must:
      - set `name` (matches the detector type in classify_anomalies output)
      - implement `detect(data, wcs, **kwargs) -> AnomalyResult`
      - be thread-safe (no per-request state)
    """

    name: str = ""  # subclasses override

    @abstractmethod
    def detect(
        self,
        data: NDArray,
        wcs: Any | None = None,
        **kwargs: Any,
    ) -> AnomalyResult:
        """Run this detector and return a structured AnomalyResult."""

    # Convenience: match the legacy function-call API so callers that did
    # `spike_detector(data)` keep working after the refactor.
    def __call__(
        self,
        data: NDArray,
        wcs: Any | None = None,
        **kwargs: Any,
    ) -> AnomalyResult:
        return self.detect(data, wcs, **kwargs)
