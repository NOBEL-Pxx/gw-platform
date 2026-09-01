"""
DipDetector -- dark defects (dead pixels, missing data, bad columns).

R6.24 refactor: extracted from anomaly_classifier.dip_detector. Symmetric
inverse of SpikeDetector.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as scipy_ndimage

from pipeline.anomaly.base import (
    AnomalyDetector,
    AnomalyResult,
    confidence_from_snrs,
    extract_regions,
    local_stats,
)


class DipDetector(AnomalyDetector):
    """Detect dark defects via local sigma-clipping (inverse of spike).

    A pixel is flagged when the local background mean exceeds the pixel value
    by more than *sigma* x local std.
    """

    name = "dip"

    def detect(
        self,
        data: NDArray,
        wcs: Any | None = None,
        *,
        sigma: float = 5.0,
        window_size: int = 64,
        min_region_pixels: int = 3,
    ) -> AnomalyResult:
        local_mean, local_std = local_stats(data, window_size)
        deficit = local_mean - data.astype(np.float64)
        mask = deficit > (sigma * np.maximum(local_std, 1e-9))

        labeled = scipy_ndimage.label(mask)[0]
        if labeled.max() > 0:
            for lbl in range(1, labeled.max() + 1):
                if int(np.sum(labeled == lbl)) < min_region_pixels:
                    mask[labeled == lbl] = False

        regions = extract_regions(mask, data, local_mean, local_std)
        snrs = [r.snr for r in regions]
        conf = confidence_from_snrs(snrs, sigma)

        if regions:
            desc = (
                f"{len(regions)} dip region{'s' if len(regions) != 1 else ''} "
                f"detected above {sigma}\u03c3 threshold"
            )
        else:
            desc = f"No dip anomalies detected at {sigma}\u03c3"

        return AnomalyResult(
            type=self.name,
            confidence=conf,
            pixel_regions=regions,
            description=desc,
            wcs_issues=[],
        )
