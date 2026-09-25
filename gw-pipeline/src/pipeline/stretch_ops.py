"""R6.104-K: pure stretch / post-stretch-coefficient functions for HiPS pipeline.

Mirrors AladinLite v3 §10 pipeline order:
    cut -> stretch -> colormap -> reverse -> gamma -> brightness -> contrast -> saturation.

All functions operate on float32 arrays in [0, 1]. Inputs are clipped.
"""
from __future__ import annotations

import numpy as np


def apply_pow2(pixels: np.ndarray, min_cut: float, max_cut: float) -> np.ndarray:
    """y = x^2 -- brightens faint features; reduces bright-end contrast.

    Mirrors AladinLite's `pow2` stretch (extension over stock sqrt/log/asinh).
    """
    span = max(max_cut - min_cut, 1e-9)
    norm = (pixels - min_cut) / span
    return np.clip(norm, 0.0, 1.0) ** 2


def apply_equalization(
    pixels: np.ndarray,
    min_cut: float,
    max_cut: float,
    n_bins: int = 256,
) -> np.ndarray:
    """Histogram equalization -- uniformizes distribution across [0, 1].

    Uses the CDF of the source histogram as a lookup. Pixels with the same
    normalized value map to the same CDF bucket (idempotent on already-
    equalized data; tested in test_hips_stretch_ext::test_equalization_idempotent).
    """
    span = max(max_cut - min_cut, 1e-9)
    norm = np.clip((pixels - min_cut) / span, 0.0, 1.0).astype(np.float32)
    flat = norm.flatten()
    hist, _ = np.histogram(flat, bins=n_bins, range=(0.0, 1.0))
    cdf = np.cumsum(hist).astype(np.float32)
    cdf = cdf / max(cdf[-1], 1.0)
    bin_idx = np.clip((flat * (n_bins - 1)).astype(np.int32), 0, n_bins - 1)
    return cdf[bin_idx].reshape(norm.shape)


def apply_gamma(rgb: np.ndarray, gamma: float) -> np.ndarray:
    """Per-channel gamma correction. gamma=1.0 is identity."""
    if abs(gamma - 1.0) < 1e-6:
        return rgb
    inv = 1.0 / max(gamma, 1e-6)
    return np.clip(rgb, 0.0, 1.0) ** inv


def apply_brightness(rgb: np.ndarray, brightness: float) -> np.ndarray:
    """Additive brightness offset. brightness=0.0 is identity."""
    if abs(brightness) < 1e-6:
        return rgb
    return np.clip(rgb + brightness, 0.0, 1.0)


def apply_contrast(rgb: np.ndarray, contrast: float) -> np.ndarray:
    """Multiplicative contrast around 0.5 gray. contrast=1.0 is identity."""
    if abs(contrast - 1.0) < 1e-6:
        return rgb
    return np.clip((rgb - 0.5) * contrast + 0.5, 0.0, 1.0)


def apply_saturation(rgb: np.ndarray, saturation: float) -> np.ndarray:
    """HSV-style saturation around luminance gray. saturation=1.0 is identity.

    rgb can be 2D (H, W, 3) or 3D (N, H, W, 3). Falls back to per-pixel mean
    for non-3-channel arrays (returns rgb unchanged).
    """
    if abs(saturation - 1.0) < 1e-6 or rgb.ndim < 3 or rgb.shape[-1] != 3:
        return rgb
    # Rec.709 luminance
    gray = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    gray = gray[..., np.newaxis]
    return np.clip(gray + (rgb - gray) * saturation, 0.0, 1.0)
