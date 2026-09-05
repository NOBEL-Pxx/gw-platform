"""Core FITS file operations using Astropy.

Provides: FITS I/O, header inspection, data cutout, WCS coordinate transforms.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import logging
import numpy as np

logger = logging.getLogger(__name__)


class FITSError(Exception):
    """Base exception for FITS processing errors."""


def read_fits(filepath: str | Path) -> Dict[str, Any]:
    """Read a FITS file and return data array + header metadata.

    Args:
        filepath: Path to .fits or .fit file.

    Returns:
        dict with keys: data (ndarray), header (dict), shape, dtype, naxis.

    Raises:
        FITSError: If file cannot be read or has no data.
    """
    from astropy.io import fits

    filepath = Path(filepath)
    if not filepath.exists():
        raise FITSError(f"FITS file not found: {filepath}")

    # Quick binary integrity: check FITS magic bytes before full parse
    try:
        size = filepath.stat().st_size
        if size < 2880:
            raise FITSError(f"FITS file too small: {size} bytes (min 2880)")
        with open(filepath, "rb") as fh:
            header_start = fh.read(80).decode("ascii", errors="replace")
        if not header_start.startswith("SIMPLE  ="):
            raise FITSError(
                f"Not a valid FITS file: missing 'SIMPLE  =' "
                f"(got: {header_start[:30].strip()})"
            )
    except FITSError:
        raise
    except Exception as e:
        raise FITSError(f"Cannot read FITS file header: {e}")

    try:
        with fits.open(filepath) as hdul:
            hdul.verify("exception")  # strict: raise on any standard violation
            # Find first HDU with data
            for hdu in hdul:
                if hdu.data is not None:
                    data = hdu.data.astype(np.float64)
                    header = dict(hdu.header)
                    return {
                        "data": data,
                        "header": header,
                        "shape": data.shape,
                        "dtype": str(data.dtype),
                        "naxis": header.get("NAXIS", 0),
                        "filename": filepath.name,
                    }
            raise FITSError(f"No image data found in {filepath}")
    except Exception as e:
        if isinstance(e, FITSError):
            raise
        raise FITSError(f"Failed to read FITS file {filepath}: {e}")


def fits_cutout(
    filepath: str | Path,
    ra: float,
    dec: float,
    size_arcmin: float = 5.0,
    output_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Extract a cutout around sky coordinates using WCS.

    Args:
        filepath: Input FITS file.
        ra: Right Ascension in degrees.
        dec: Declination in degrees.
        size_arcmin: Cutout size in arcminutes.
        output_path: If provided, write cutout FITS to this path.

    Returns:
        dict with cutout data, header, WCS info, and pixel coordinates.
    """
    from astropy.io import fits
    from astropy.wcs import WCS
    from astropy.nddata import Cutout2D
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    filepath = Path(filepath)
    if not filepath.exists():
        raise FITSError(f"FITS file not found: {filepath}")

    with fits.open(filepath) as hdul:
        hdul.verify("exception")
        hdu = None
        for h in hdul:
            if h.data is not None:
                hdu = h
                break
        if hdu is None:
            raise FITSError(f"No image data in {filepath}")

        wcs = WCS(hdu.header)
        if not wcs.has_celestial:
            raise FITSError(f"FITS file has no valid WCS: {filepath}")

        coord = SkyCoord(ra=ra, dec=dec, unit="deg", frame="icrs")
        size_pix = int(size_arcmin * 60 / abs(wcs.proj_plane_pixel_scales()[0].value * 3600))
        size_pix = max(size_pix, 10)
        size = u.Quantity((size_pix, size_pix), u.pixel)

        try:
            cutout = Cutout2D(hdu.data, coord, size, wcs=wcs, mode="strict", fill_value=np.nan)
        except Exception:
            cutout = Cutout2D(hdu.data, coord, size, wcs=wcs, mode="partial", fill_value=np.nan)

        result = {
            "cutout_data": cutout.data,
            "wcs": str(wcs),
            "center_ra": ra,
            "center_dec": dec,
            "size_arcmin": size_arcmin,
            "pixel_center_x": float(cutout.position_original[0]),
            "pixel_center_y": float(cutout.position_original[1]),
            "cutout_shape": cutout.data.shape,
        }

        if output_path:
            output_path = Path(output_path)
            cutout_hdu = fits.PrimaryHDU(data=cutout.data, header=cutout.wcs.to_header())
            cutout_hdu.writeto(output_path, overwrite=True)
            result["output_path"] = str(output_path)

        return result


def wcs_info(filepath: str | Path) -> Dict[str, Any]:
    """Extract WCS metadata from a FITS file.

    Returns celestial WCS parameters: CRPIX, CRVAL, CTYPE, CD matrix,
    pixel scale, image footprint corners, projection type.
    """
    from astropy.io import fits
    from astropy.wcs import WCS
    import astropy.units as u

    filepath = Path(filepath)
    if not filepath.exists():
        raise FITSError(f"FITS file not found: {filepath}")

    with fits.open(filepath) as hdul:
        hdul.verify("exception")
        for hdu in hdul:
            if hdu.data is not None:
                w = WCS(hdu.header)
                if not w.has_celestial:
                    raise FITSError(f"No celestial WCS in {filepath}")

                shape = hdu.data.shape
                corners_pix = np.array([[0, 0], [0, shape[-2]], [shape[-1], 0], [shape[-1], shape[-2]]])
                corners_sky = w.pixel_to_world(corners_pix[:, 0], corners_pix[:, 1])

                return {
                    "filename": filepath.name,
                    "naxis": w.naxis,
                    "shape": shape,
                    "projection": w.wcs.ctype[0],
                    "reference_pixel": list(w.wcs.crpix),
                    "reference_value": list(w.wcs.crval),
                    "pixel_scale_arcsec": [float(abs(s.to(u.arcsec).value)) for s in w.proj_plane_pixel_scales()],
                    "image_size_arcmin": [
                        float(abs(shape[-1] * w.proj_plane_pixel_scales()[0].to(u.arcmin).value)),
                        float(abs(shape[-2] * w.proj_plane_pixel_scales()[1].to(u.arcmin).value)),
                    ],
                    "corner_coords": [
                        {"ra": float(c.ra.deg), "dec": float(c.dec.deg)} for c in corners_sky
                    ],
                }
        raise FITSError(f"No data HDU in {filepath}")


def sky_to_pixel(filepath: str | Path, ra: float, dec: float) -> Dict[str, Any]:
    """Convert sky coordinates to pixel coordinates using WCS.

    Args:
        filepath: FITS file with WCS.
        ra, dec: Sky coordinates in degrees.

    Returns:
        dict with pixel_x, pixel_y, and whether point is within image bounds.
    """
    from astropy.io import fits
    from astropy.wcs import WCS

    filepath = Path(filepath)
    with fits.open(filepath) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                w = WCS(hdu.header)
                px, py = w.wcs_world2pix([[ra, dec]], 1)[0]
                shape = hdu.data.shape
                in_bounds = 0 <= px < shape[-1] and 0 <= py < shape[-2]
                return {
                    "ra": ra, "dec": dec,
                    "pixel_x": float(px), "pixel_y": float(py),
                    "in_bounds": bool(in_bounds),
                    "image_shape": shape,
                }
        raise FITSError(f"No data HDU in {filepath}")
