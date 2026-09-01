"""
PatternBreakDetector -- row / column artefacts + 2D-FFT high-frequency check.

R6.24 refactor: extracted from anomaly_classifier.pattern_break_detector.
The detector logic is unchanged.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from pipeline.anomaly.base import AnomalyDetector, AnomalyResult


class PatternBreakDetector(AnomalyDetector):
    """Detect row/column artefacts via gradient analysis and 2-D FFT.

    1. Compute row-wise and column-wise median profiles.
    2. Flag rows / columns whose gradient exceeds *sigma* x gradient std.
    3. Run a 2-D FFT and check for abnormally concentrated high-frequency power
       (periodic striping, scan-line noise).
    """

    name = "pattern_break"

    def detect(
        self,
        data: NDArray,
        wcs: Any | None = None,
        *,
        sigma: float = 4.0,
    ) -> AnomalyResult:
        # ----- row / column gradient analysis -----
        row_profile = np.nanmedian(data, axis=1)
        col_profile = np.nanmedian(data, axis=0)

        row_grad = np.abs(np.gradient(row_profile))
        col_grad = np.abs(np.gradient(col_profile))

        row_thresh = np.nanmean(row_grad) + sigma * np.nanstd(row_grad)
        col_thresh = np.nanmean(col_grad) + sigma * np.nanstd(col_grad)

        bad_rows = np.where(row_grad > row_thresh)[0].tolist()
        bad_cols = np.where(col_grad > col_thresh)[0].tolist()

        # ----- 2-D FFT high-frequency check -----
        fft = np.fft.fft2(data.astype(np.float64))
        fft_shifted = np.fft.fftshift(fft)
        power = np.abs(fft_shifted)

        h, w = power.shape
        cy, cx = h // 2, w // 2
        hf_mask = np.zeros_like(power, dtype=bool)
        hf_border_y = int(h * 0.3)
        hf_border_x = int(w * 0.3)
        hf_mask[:hf_border_y, :] = True
        hf_mask[-hf_border_y:, :] = True
        hf_mask[:, :hf_border_x] = True
        hf_mask[:, -hf_border_x:] = True
        # Carve out the central low-frequency disc
        yy, xx = np.ogrid[:h, :w]
        center_disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= (min(h, w) * 0.2) ** 2
        hf_mask &= ~center_disc

        hf_power = power[hf_mask]
        lf_power = power[~hf_mask]
        # Avoid division by zero on tiny/empty LF mask
        if lf_power.size == 0 or float(np.mean(lf_power)) == 0:
            hf_ratio = 0.0
        else:
            hf_ratio = float(np.mean(hf_power) / np.mean(lf_power))

        has_hf_anomaly = hf_ratio > 0.15  # empirical threshold

        if bad_rows or bad_cols or has_hf_anomaly:
            desc_parts = []
            if bad_rows:
                desc_parts.append(f"{len(bad_rows)} anomalous row(s)")
            if bad_cols:
                desc_parts.append(f"{len(bad_cols)} anomalous column(s)")
            if has_hf_anomaly:
                desc_parts.append(f"high-frequency power ratio={hf_ratio:.3f}")
            desc = "; ".join(desc_parts)
            # Confidence: gradient anomaly magnitude
            grad_mag = max(
                float(np.max(row_grad) / max(row_thresh, 1e-9)),
                float(np.max(col_grad) / max(col_thresh, 1e-9)),
            )
            confidence = round(min(1.0, (grad_mag - 1.0) / 3.0), 3)
        else:
            desc = "No pattern-break artefacts detected"
            confidence = 0.0

        return AnomalyResult(
            type=self.name,
            confidence=confidence,
            pixel_regions=[],
            description=desc,
            wcs_issues=[],
            extras={
                "bad_rows": bad_rows,
                "bad_cols": bad_cols,
                "hf_power_ratio": round(hf_ratio, 4),
            },
        )
