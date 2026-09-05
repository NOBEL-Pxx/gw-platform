"""
Rule-based FITS anomaly classifier for the GravitationalWave platform.

Implements four statistical detectors that run on CPU without any new dependencies:
  - spike_detector:    Local sigma-clipping for bright outliers (cosmic rays, hot pixels, RFI)
  - dip_detector:      Inverse spike detection for dark defects (dead pixels, missing data)
  - pattern_break_detector: Gradient + 2D-FFT analysis for row/column artifacts
  - wcs_mismatch_detector:  WCS metadata validation (CRVAL, CD matrix, pixel scale)

All detectors reuse the existing numpy / scipy / astropy stack already present in the
gw-pipeline Docker image.  No PyTorch, TensorFlow, or ONNX dependency is introduced.

Usage:
    from pipeline.anomaly_classifier import classify_anomalies
    results = classify_anomalies(data, wcs, spike_sigma=5.0, dip_sigma=5.0, pattern_break_sigma=4.0)
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage as scipy_ndimage
from astropy.stats import sigma_clipped_stats

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

PixelRegion = dict[str, Any]
AnomalyResult = dict[str, Any]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_stats(
    data: NDArray,
    window_size: int = 64,
) -> tuple[NDArray, NDArray]:
    """Compute per-pixel local background (mean) and std via a sliding window.

    Uses scipy.ndimage.uniform_filter which runs in O(N) — far faster than
    median_filter for large windows.  The mean is a good-enough background
    estimator for anomaly detection (5σ+ outliers), and the std comes from
    the running variance formula sqrt(E[X²] - E[X]²).
    """
    work = data.astype(np.float64)
    local_mean = scipy_ndimage.uniform_filter(work, size=window_size)
    mean_sq = scipy_ndimage.uniform_filter(work ** 2, size=window_size)
    local_std = np.sqrt(np.maximum(mean_sq - local_mean ** 2, 0.0))
    return local_mean, local_std


def _extract_regions(
    mask: NDArray,
    data: NDArray,
    local_mean: NDArray,
    local_std: NDArray,
) -> list[PixelRegion]:
    """Cluster connected pixels from a boolean mask and return region dicts."""
    labeled, n_features = scipy_ndimage.label(mask)
    if n_features == 0:
        return []

    regions: list[PixelRegion] = []
    for label_id in range(1, n_features + 1):
        ys, xs = np.where(labeled == label_id)
        if len(ys) < 2:            # skip single-pixel noise
            continue
        region_data = data[ys, xs]
        peak_value = float(np.max(region_data))
        bg_std = float(np.mean(local_std[ys, xs]))
        bg_median = float(np.mean(local_mean[ys, xs]))
        snr = (peak_value - bg_median) / max(bg_std, 1e-9)

        regions.append({
            "x_min": int(np.min(xs)),
            "x_max": int(np.max(xs)),
            "y_min": int(np.min(ys)),
            "y_max": int(np.max(ys)),
            "peak_value": peak_value,
            "snr": round(snr, 2),
        })

    regions.sort(key=lambda r: r["snr"], reverse=True)
    return regions


def _confidence(snr_values: list[float], threshold: float) -> float:
    """Map the best-region SNR to a [0, 1] confidence score via a soft ramp."""
    if not snr_values:
        return 0.0
    best = max(snr_values)
    if best <= threshold:
        return 0.0
    return round(min(1.0, (best - threshold) / (3.0 * threshold)), 3)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def spike_detector(
    data: NDArray,
    sigma: float = 5.0,
    window_size: int = 64,
    min_region_pixels: int = 3,
) -> dict[str, Any]:
    """Detect bright outliers via local sigma-clipping.

    A pixel is flagged when its value exceeds the local median by more than
    *sigma* x local std.  Connected components are clustered and sorted by SNR.
    """
    local_mean, local_std = _local_stats(data, window_size)
    excess = data.astype(np.float64) - local_mean
    mask = excess > (sigma * np.maximum(local_std, 1e-9))

    # Suppress single-pixel / tiny regions
    labeled = scipy_ndimage.label(mask)[0]
    for lbl in range(1, labeled.max() + 1):
        if np.sum(labeled == lbl) < min_region_pixels:
            mask[labeled == lbl] = False

    regions = _extract_regions(mask, data, local_mean, local_std)
    snrs = [r["snr"] for r in regions]
    conf = _confidence(snrs, sigma)

    return {
        "type": "spike",
        "confidence": conf,
        "pixel_regions": regions,
        "description": (
            f"{len(regions)} spike region{'s' if len(regions) != 1 else ''} "
            f"detected above {sigma}σ threshold" if regions
            else f"No spike anomalies detected at {sigma}σ"
        ),
        "wcs_issues": [],
    }


def dip_detector(
    data: NDArray,
    sigma: float = 5.0,
    window_size: int = 64,
    min_region_pixels: int = 3,
) -> dict[str, Any]:
    """Detect dark defects (dead pixels, missing data, bad columns).

    Symmetric inverse of spike_detector: flags pixels where the local median
    exceeds the pixel value by more than *sigma* x local std.
    """
    local_mean, local_std = _local_stats(data, window_size)
    deficit = local_mean - data.astype(np.float64)
    mask = deficit > (sigma * np.maximum(local_std, 1e-9))

    labeled = scipy_ndimage.label(mask)[0]
    for lbl in range(1, labeled.max() + 1):
        if np.sum(labeled == lbl) < min_region_pixels:
            mask[labeled == lbl] = False

    regions = _extract_regions(mask, data, local_mean, local_std)
    snrs = [r["snr"] for r in regions]
    conf = _confidence(snrs, sigma)

    return {
        "type": "dip",
        "confidence": conf,
        "pixel_regions": regions,
        "description": (
            f"{len(regions)} dip region{'s' if len(regions) != 1 else ''} "
            f"detected above {sigma}σ threshold" if regions
            else f"No dip anomalies detected at {sigma}σ"
        ),
        "wcs_issues": [],
    }


def pattern_break_detector(
    data: NDArray,
    sigma: float = 4.0,
) -> dict[str, Any]:
    """Detect row / column artefacts via gradient analysis and 2-D FFT.

    1. Compute row-wise and column-wise median profiles.
    2. Flag rows / columns whose gradient exceeds *sigma* x gradient std.
    3. Run a 2-D FFT and check for abnormally concentrated high-frequency power
       (periodic striping, scan-line noise).
    """
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

    hf_power = power[hf_mask]
    lf_mask = ~hf_mask
    lf_mask[cy - 2:cy + 2, cx - 2:cx + 2] = False  # exclude DC centre
    lf_power = power[lf_mask]

    hf_median = float(np.median(hf_power))
    lf_median = float(np.median(lf_power))
    hf_ratio = hf_median / max(lf_median, 1e-9)

    has_gradient_issue = len(bad_rows) > 0 or len(bad_cols) > 0
    has_hf_issue = hf_ratio > 3.0

    grad_score = min(1.0, max(len(bad_rows), len(bad_cols)) / 20.0)
    fft_score = min(1.0, (hf_ratio - 1.0) / 4.0) if hf_ratio > 1.0 else 0.0
    conf = round(max(grad_score, fft_score), 3)

    # Synthesise pixel regions for bad rows / columns (cap at 10 each)
    regions: list[PixelRegion] = []
    for r in bad_rows[:10]:
        regions.append({
            "x_min": 0, "x_max": w - 1,
            "y_min": r, "y_max": r,
            "peak_value": float(row_profile[r]),
            "snr": round(float(row_grad[r]) / max(np.nanstd(row_grad), 1e-9), 2),
        })
    for c in bad_cols[:10]:
        regions.append({
            "x_min": c, "x_max": c,
            "y_min": 0, "y_max": h - 1,
            "peak_value": float(col_profile[c]),
            "snr": round(float(col_grad[c]) / max(np.nanstd(col_grad), 1e-9), 2),
        })

    parts: list[str] = []
    if bad_rows:
        parts.append(f"{len(bad_rows)} anomalous row{'s' if len(bad_rows) > 1 else ''}")
    if bad_cols:
        parts.append(f"{len(bad_cols)} anomalous column{'s' if len(bad_cols) > 1 else ''}")
    if has_hf_issue:
        parts.append(f"high-frequency excess (HF/LF ratio={hf_ratio:.2f})")

    return {
        "type": "pattern_break",
        "confidence": conf,
        "pixel_regions": regions,
        "description": (
            ", ".join(parts) if parts
            else "No pattern-break anomalies detected"
        ),
        "wcs_issues": [],
        "fft_hf_lf_ratio": round(hf_ratio, 3),
    }


def wcs_mismatch_detector(wcs_info: dict[str, Any] | None) -> dict[str, Any]:
    """Validate WCS metadata for common integrity problems.

    Parameters
    ----------
    wcs_info : dict or None
        The dict returned by ``fits_core.wcs_info()``, or ``None`` if WCS is absent.
        Expected keys: ``reference_value`` ([RA, Dec]), ``pixel_scale_arcsec``,
        ``projection``, ``cd_determinant``.

    Returns
    -------
    dict with ``type``, ``confidence``, ``wcs_issues``, ``description``.
    """
    if wcs_info is None:
        return {
            "type": "wcs_mismatch",
            "confidence": 1.0,
            "pixel_regions": [],
            "description": "WCS metadata missing - no WCS header found in FITS file",
            "wcs_issues": ["missing_wcs"],
        }

    issues: list[str] = []

    # 1. CRVAL range (reference_value = [RA, Dec] from wcs_info)
    ref_val = wcs_info.get("reference_value")
    if ref_val and len(ref_val) >= 2:
        crval_ra, crval_dec = ref_val[0], ref_val[1]
        if crval_ra is not None and (crval_ra < 0 or crval_ra > 360):
            issues.append(f"CRVAL RA out of range [0, 360]: {crval_ra}")
        if crval_dec is not None and (crval_dec < -90 or crval_dec > 90):
            issues.append(f"CRVAL Dec out of range [-90, 90]: {crval_dec}")

    # 2. Pixel scale (arcsec / px)
    pix_scale = wcs_info.get("pixel_scale_arcsec")
    if pix_scale:
        ps_x = pix_scale[0] if len(pix_scale) >= 1 else None
        ps_y = pix_scale[1] if len(pix_scale) >= 2 else ps_x
        if ps_x is not None and (ps_x < 0.01 or ps_x > 10.0):
            issues.append(f"Pixel scale X out of range (0.01-10 arcsec/px): {ps_x}")
        if ps_y is not None and (ps_y < 0.01 or ps_y > 10.0):
            issues.append(f"Pixel scale Y out of range (0.01-10 arcsec/px): {ps_y}")

    # 3. CD matrix singularity
    cd_det = wcs_info.get("cd_determinant")
    if cd_det is not None and abs(cd_det) < 1e-10:
        issues.append(f"CD matrix near-singular (|det|={abs(cd_det):.2e})")

    # 4. Projection type
    projection = wcs_info.get("projection", "")
    if projection and "UNKNOWN" in str(projection).upper():
        issues.append(f"Unknown WCS projection: {projection}")

    conf = min(1.0, len(issues) * 0.4) if issues else 0.0

    return {
        "type": "wcs_mismatch",
        "confidence": round(conf, 3),
        "pixel_regions": [],
        "description": (
            f"{len(issues)} WCS issue{'s' if len(issues) != 1 else ''} found" if issues
            else "WCS metadata appears valid"
        ),
        "wcs_issues": issues,
    }


# ---------------------------------------------------------------------------
# Main entry point - called from the FastAPI endpoint
# ---------------------------------------------------------------------------

def classify_anomalies(
    data: NDArray,
    wcs_info: dict[str, Any] | None = None,
    *,
    spike_sigma: float = 5.0,
    dip_sigma: float = 5.0,
    pattern_break_sigma: float = 4.0,
    window_size: int = 64,
) -> dict[str, Any]:
    """Run all four detectors and return a unified result dict.

    Parameters
    ----------
    data : 2-D ndarray
        FITS pixel data (float or int).
    wcs_info : dict or None
        WCS metadata dict from ``fits_core.wcs_info()``.
    spike_sigma : float
    dip_sigma : float
    pattern_break_sigma : float
    window_size : int
        Sliding-window size for local-statistics detectors.

    Returns
    -------
    dict suitable for JSON serialisation::

        {
            "detection_time_ms": float,
            "image_stats": {"mean", "median", "std"},
            "anomalies": [ ... ],
            "parameters_used": { ... },
        }
    """
    t0 = time.perf_counter()

    # Basic image statistics (reuses sigma_clipped_stats from astropy)
    global_mean, global_median, global_std = sigma_clipped_stats(data, sigma=3.0)

    # Ensure float for stable arithmetic
    work = data.astype(np.float64)

    # Run detectors (each is independent - could be parallelised, but for
    # ~200 ms total the threading overhead isn't worth it)
    anomalies: list[dict[str, Any]] = [
        spike_detector(work, sigma=spike_sigma, window_size=window_size),
        dip_detector(work, sigma=dip_sigma, window_size=window_size),
        pattern_break_detector(work, sigma=pattern_break_sigma),
        wcs_mismatch_detector(wcs_info),
    ]

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "detection_time_ms": elapsed_ms,
        "image_stats": {
            "mean": round(float(global_mean), 6),
            "median": round(float(global_median), 6),
            "std": round(float(global_std), 6),
        },
        "anomalies": anomalies,
        "parameters_used": {
            "spike_sigma": spike_sigma,
            "dip_sigma": dip_sigma,
            "pattern_break_sigma": pattern_break_sigma,
            "window_size": window_size,
        },
    }
