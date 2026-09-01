"""
SpikeDetector -- bright outliers (cosmic rays, hot pixels, RFI).

R6.24 refactor: extracted from anomaly_classifier.spike_detector into its own
file. The detector logic is unchanged; only the wrapper signature now returns
an AnomalyResult dataclass.
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


class SpikeDetector(AnomalyDetector):
    """Detect bright outliers via local sigma-clipping.

    A pixel is flagged when its value exceeds the local background mean by
    more than *sigma* x local std. Connected components are clustered and
    sorted by SNR.
    """

    name = "spike"

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
        excess = data.astype(np.float64) - local_mean
        mask = excess > (sigma * np.maximum(local_std, 1e-9))

        # Suppress single-pixel / tiny regions
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
                f"{len(regions)} spike region{'s' if len(regions) != 1 else ''} "
                f"detected above {sigma}\u03c3 threshold"
            )
        else:
            desc = f"No spike anomalies detected at {sigma}\u03c3"

        return AnomalyResult(
            type=self.name,
            confidence=conf,
            pixel_regions=regions,
            description=desc,
            wcs_issues=[],
        )
