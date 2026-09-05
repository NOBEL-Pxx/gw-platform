"""Source extraction pipeline for astronomical FITS images.

Provides: source detection (DAOStarFinder + segmentation),
photometry, and SNR estimation.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
import numpy as np

logger = logging.getLogger(__name__)


def detect_sources(
    filepath: str | Path,
    threshold_snr: float = 5.0,
    fwhm_pix: float = 3.0,
    max_sources: int = 500,
    kernel: str = "gaussian",
) -> Dict[str, Any]:
    """Detect point sources in a FITS image.

    Args:
        filepath: FITS image path.
        threshold_snr: Signal-to-noise threshold for detection.
        fwhm_pix: Approximate FWHM of sources in pixels.
        max_sources: Maximum number of sources to return.
        kernel: Detection kernel — "gaussian" (default), "mexicanhat", or "tophat".

    Returns:
        dict with sources list, detection params, and image statistics.
    """
    from astropy.io import fits
    from astropy.stats import sigma_clipped_stats
    from photutils.detection import DAOStarFinder

    filepath = Path(filepath)
    with fits.open(filepath) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                data = hdu.data.astype(np.float64)
                break
        else:
            raise ValueError(f"No data in {filepath}")

    # Image statistics
    mean, median, std = sigma_clipped_stats(data, sigma=3.0)

    # Convolution kernel for matched-filter detection (v4.12)
    from astropy.convolution import Gaussian2DKernel, convolve
    # Custom Mexican-hat kernel: difference of two Gaussians (DoG)
    if kernel == "mexicanhat":
        sigma = fwhm_pix / 2.355
        g1 = Gaussian2DKernel(sigma)
        g2 = Gaussian2DKernel(sigma * 2)
        selected_kernel = type(g1)(g1.array - g2.array)
    elif kernel == "tophat":
        radius = max(1, int(fwhm_pix))
        y, x = np.ogrid[-radius:radius+1, -radius:radius+1]
        selected_kernel = type(Gaussian2DKernel(1))(np.where(x**2 + y**2 <= radius**2, 1.0, 0.0).astype(float))
    else:
        selected_kernel = Gaussian2DKernel(fwhm_pix / 2.355)
    convolved = convolve(data - median, selected_kernel)

    # Source detection on convolved image
    finder = DAOStarFinder(
        fwhm=fwhm_pix,
        threshold=threshold_snr * std,
        n_brightest=max_sources,
    )
    sources = finder(convolved)

    results = []
    if sources is not None and len(sources) > 0:
        for row in sources[:max_sources]:
            flux = float(row["flux"])
            snr = flux / (std * np.pi * (fwhm_pix / 2.36) ** 2) if std > 0 else 0
            results.append({
                "id": int(row["id"]),
                "x": float(row["x_centroid"]),
                "y": float(row["y_centroid"]),
                "flux": flux,
                "snr": round(float(snr), 2),
                "fwhm": float(row.get("fwhm", row.get("sharpness", 3.0))),
                "ellipticity": float(row.get("ellipticity", row.get("roundness1", 0.0))),
            })

    return {
        "filename": filepath.name,
        "num_sources": len(results),
        "threshold_snr": threshold_snr,
        "kernel": kernel,
        "image_stats": {"mean": float(mean), "median": float(median), "std": float(std)},
        "sources": results,
    }


def detect_extended_sources(
    filepath: str | Path,
    nsig: float = 3.0,
    npixels: int = 10,
    contrast: float = 0.01,
) -> Dict[str, Any]:
    """Detect extended/blended sources using image segmentation.

    Useful for galaxies, nebulae, and gravitational wave optical counterparts.

    Args:
        filepath: FITS image path.
        nsig: Detection threshold in sigma.
        npixels: Minimum number of connected pixels for a source.
        contrast: Fraction of peak for deblending.

    Returns:
        dict with segmentation map info and source catalog.
    """
    from astropy.io import fits
    from astropy.stats import sigma_clipped_stats
    from photutils.segmentation import detect_sources, deblend_sources, SourceCatalog
    from photutils.background import Background2D, MedianBackground

    filepath = Path(filepath)
    with fits.open(filepath) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                data = hdu.data.astype(np.float64)
                break
        else:
            raise ValueError(f"No data in {filepath}")

    mean, median, std = sigma_clipped_stats(data, sigma=3.0)
    threshold = median + nsig * std

    # Background estimation
    try:
        bkg = Background2D(data, (50, 50), filter_size=(3, 3), bkg_estimator=MedianBackground())
        data_sub = data - bkg.background
    except Exception:
        data_sub = data - median

    segm = detect_sources(data_sub, threshold, npixels=npixels)
    if segm is None:
        return {"filename": filepath.name, "num_sources": 0, "sources": [], "threshold": threshold}

    segm_deblend = deblend_sources(data_sub, segm, npixels=npixels, contrast=contrast, nlevels=32)

    try:
        cat = SourceCatalog(data_sub, segm_deblend)
        tbl = cat.to_table()
    except Exception:
        return {
            "filename": filepath.name,
            "num_sources": segm_deblend.nlabels,
            "threshold_sigma": nsig,
            "image_stats": {"mean": float(mean), "median": float(median), "std": float(std)},
            "sources": [],
        }

    results = []
    for row in tbl[:200]:
        results.append({
            "label": int(row["label"]),
            "x": float(row["x_centroid"]),
            "y": float(row["y_centroid"]),
            "area": float(row["area"]) if "area" in row.columns else 0,
            "ellipticity": float(row.get("ellipticity", row.get("roundness1", 0.0))) if "ellipticity" in row.columns else 0,
            "semimajor_sigma": float(row["semimajor_sigma"]) if "semimajor_sigma" in row.columns else 0,
        })

    return {
        "filename": filepath.name,
        "num_sources": len(results),
        "total_segments": segm_deblend.nlabels,
        "threshold_sigma": nsig,
        "image_stats": {"mean": float(mean), "median": float(median), "std": float(std)},
        "sources": results,
    }


def compute_snr_map(filepath: str | Path, return_heatmap: bool = False) -> Dict[str, Any]:
    """Generate a signal-to-noise ratio map for a FITS image.

    Args:
        filepath: FITS image path.
        return_heatmap: If True, includes a base64 PNG heatmap in the response.

    Returns SNR statistics useful for assessing image quality.
    """
    from astropy.io import fits
    from astropy.stats import sigma_clipped_stats
    from scipy.ndimage import uniform_filter
    import numpy as np

    filepath = Path(filepath)
    with fits.open(filepath) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                data = hdu.data.astype(np.float64)
                break
        else:
            raise ValueError(f"No data in {filepath}")

    _, median, std = sigma_clipped_stats(data, sigma=3.0)
    if std == 0:
        return {"filename": filepath.name, "snr_max": 0, "snr_median": 0, "detectable_sources_estimate": 0}

    # Smooth noise estimation
    noise_map = uniform_filter(np.abs(data - median), size=7)
    noise_map[noise_map < std * 0.5] = std
    snr_map = data / noise_map

    snr_flat = snr_map[~np.isnan(snr_map)].flatten()
    result_data = {
        "filename": filepath.name,
        "snr_max": float(np.nanmax(snr_map)),
        "snr_median": float(np.median(snr_flat)),
        "snr_mean": float(np.nanmean(snr_flat)),
        "pixels_above_3sigma": int(np.sum(snr_flat > 3)),
        "fraction_above_3sigma": float(np.mean(snr_flat > 3)),
        "detectable_sources_estimate": int(np.sum(snr_flat > 5) / 10),
    }

    if return_heatmap:
        import io, base64
        from PIL import Image as PILImage
        snr_clipped = np.clip(snr_map, 0, 10)
        if snr_clipped.size > 2_000_000:
            snr_clipped = snr_clipped[::2, ::2]
        try:
            from matplotlib import cm
            import matplotlib
            matplotlib.use('Agg')
            cmap = cm.get_cmap('viridis')
            colored = cmap(snr_clipped / 10.0)
            colored = (colored[:, :, :3] * 255).astype(np.uint8)
        except ImportError:
            normalized = (snr_clipped / 10.0 * 255).astype(np.uint8)
            colored = np.stack([normalized, normalized // 3, normalized // 6], axis=-1)
        img = PILImage.fromarray(colored, mode='RGB')
        img = img.resize((512, 512), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        result_data["heatmap_png_base64"] = base64.b64encode(buf.getvalue()).decode()

    return result_data
