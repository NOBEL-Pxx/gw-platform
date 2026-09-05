"""
v4.38: Engineering + Quality Routes (Fixes #3, #4, #6)

New endpoints registered on the FastAPI app:
  ── Fix #3: Visual Config Admin ──
  GET  /pipeline/admin/config                  — List all config namespaces
  GET  /pipeline/admin/config/{namespace}      — Get config values
  PUT  /pipeline/admin/config/{namespace}      — Update config values
  POST /pipeline/admin/config/{namespace}/reset — Reset to defaults

  ── Fix #4: Data Provenance & DOI ──
  POST /pipeline/provenance/doi                — Register new DOI
  GET  /pipeline/provenance/doi/{doi}          — Get DOI record
  GET  /pipeline/provenance/dois               — List DOI records
  GET  /pipeline/provenance/chain/{obs_id}     — Provenance chain
  POST /pipeline/provenance/doi/{doi}/link     — Link observation to DOI

  ── Fix #6: Batch Export ──
  GET  /pipeline/export/anomalies              — Export anomaly results (CSV/JSON)
  GET  /pipeline/export/photometry             — Export photometry stats (CSV)
  GET  /pipeline/export/sources                — Export source catalog (CSV)

Usage: Import in server.py and call register_routes(app)
"""

from __future__ import annotations
import json, logging, io, csv, time as _time
from typing import Optional

from fastapi import Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

logger = logging.getLogger("gw.routes-v438")


def register_routes(app):
    """Register all v4.38 routes on the FastAPI app."""

    # ═════════════════════════════════════════════════════════════════════
    # Fix #3: Configuration Management
    # ═════════════════════════════════════════════════════════════════════

    @app.get("/pipeline/admin/config")
    async def list_config_namespaces(request: Request):
        """List all config namespaces with source info."""
        try:
            from .config_manager import get_config_manager
            mgr = get_config_manager()
            namespaces = await mgr.list_namespaces()
            return {"namespaces": namespaces, "count": len(namespaces)}
        except ImportError:
            return JSONResponse({"error": "Config manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.get("/pipeline/admin/config/{namespace}")
    async def get_config(namespace: str, request: Request):
        """Get full config for a namespace."""
        valid = {"ai", "thresholds", "bands"}
        if namespace not in valid:
            return JSONResponse(
                {"error": f"Unknown namespace: {namespace}. Valid: {', '.join(sorted(valid))}"},
                status_code=400,
            )
        try:
            from .config_manager import get_config_manager
            mgr = get_config_manager()
            cfg = await mgr.get_config(namespace)
            return {"namespace": namespace, "config": cfg}
        except ImportError:
            return JSONResponse({"error": "Config manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.put("/pipeline/admin/config/{namespace}")
    async def update_config(namespace: str, request: Request):
        """Update config values for a namespace. Admin only (enforced by RBAC)."""
        valid = {"ai", "thresholds", "bands"}
        if namespace not in valid:
            return JSONResponse(
                {"error": f"Unknown namespace: {namespace}"}, status_code=400
            )
        try:
            body = await request.json()
            if not body or not isinstance(body, dict):
                return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

            from .config_manager import get_config_manager
            mgr = get_config_manager()
            result = await mgr.update_config(namespace, body)
            return {"namespace": namespace, "config": result, "updated_keys": list(body.keys())}
        except ImportError:
            return JSONResponse({"error": "Config manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.post("/pipeline/admin/config/{namespace}/reset")
    async def reset_config(namespace: str, request: Request):
        """Reset a namespace to hardcoded defaults."""
        valid = {"ai", "thresholds", "bands"}
        if namespace not in valid:
            return JSONResponse({"error": f"Unknown namespace: {namespace}"}, status_code=400)
        try:
            from .config_manager import get_config_manager
            mgr = get_config_manager()
            result = await mgr.reset_to_default(namespace)
            return {"namespace": namespace, "config": result, "reset": True}
        except ImportError:
            return JSONResponse({"error": "Config manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    # ═════════════════════════════════════════════════════════════════════
    # Fix #4: Data Provenance & DOI
    # ═════════════════════════════════════════════════════════════════════

    @app.post("/pipeline/provenance/doi")
    async def register_doi(request: Request):
        """Register a new DOI reference record."""
        try:
            body = await request.json()
            required = ["title"]
            for field in required:
                if field not in body:
                    return JSONResponse(
                        {"error": f"Missing required field: {field}"}, status_code=400
                    )

            from .provenance import get_provenance_manager
            mgr = get_provenance_manager()
            record = await mgr.register_doi(body)

            # Convert datetime to string for JSON
            if "created_at" in record and hasattr(record["created_at"], "isoformat"):
                record["created_at"] = record["created_at"].isoformat() + "Z"
            if "updated_at" in record and hasattr(record["updated_at"], "isoformat"):
                record["updated_at"] = record["updated_at"].isoformat() + "Z"

            return {"success": True, "doi": record}
        except ImportError:
            return JSONResponse({"error": "Provenance manager not available"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @app.get("/pipeline/provenance/doi/{doi:path}")
    async def get_doi(doi: str, request: Request):
        """Get a DOI record by identifier."""
        try:
            from .provenance import get_provenance_manager
            mgr = get_provenance_manager()
            record = await mgr.get_doi(doi)
            if record is None:
                return JSONResponse({"error": "DOI not found"}, status_code=404)
            return {"doi": record}
        except ImportError:
            return JSONResponse({"error": "Provenance manager not available"}, status_code=500)

    @app.get("/pipeline/provenance/dois")
    async def list_dois(
        request: Request,
        survey: Optional[str] = Query(default=None, description="Filter by survey"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        """List DOI records with optional survey filter."""
        try:
            from .provenance import get_provenance_manager
            mgr = get_provenance_manager()
            result = await mgr.list_dois(survey=survey, page=page, page_size=page_size)
            return result
        except ImportError:
            return {"dois": [], "total": 0}

    @app.get("/pipeline/provenance/chain/{observation_id}")
    async def get_provenance_chain(observation_id: str, request: Request):
        """Get the provenance chain for an observation UUID."""
        try:
            from .provenance import get_provenance_manager
            mgr = get_provenance_manager()
            chain = await mgr.get_provenance_chain(observation_id)
            return {"observation_id": observation_id, "chain": chain, "length": len(chain)}
        except ImportError:
            return {"chain": [], "length": 0}

    @app.post("/pipeline/provenance/doi/{doi:path}/link")
    async def link_observation_to_doi(doi: str, request: Request):
        """Link an observation UUID to a DOI record."""
        try:
            body = await request.json()
            observation_id = body.get("observation_id", "")
            if not observation_id:
                return JSONResponse({"error": "observation_id required"}, status_code=400)

            from .provenance import get_provenance_manager
            mgr = get_provenance_manager()
            ok = await mgr.link_observation(doi, observation_id)
            return {"success": ok, "doi": doi, "observation_id": observation_id}
        except ImportError:
            return JSONResponse({"error": "Provenance manager not available"}, status_code=500)

    # ═════════════════════════════════════════════════════════════════════
    # Fix #6: Batch Export
    # ═════════════════════════════════════════════════════════════════════

    @app.get("/pipeline/export/anomalies")
    async def export_anomalies(
        request: Request,
        filename: Optional[str] = Query(default=None, description="FITS filename"),
        format: str = Query(default="csv", pattern="^(csv|json)$"),
    ):
        """Export anomaly classification results as CSV or JSON."""
        try:
            from .anomaly_classifier import classify_anomalies
            from .fits_core import read_fits

            if not filename:
                return JSONResponse({"error": "filename parameter required"}, status_code=400)

            # Read FITS and run classifier
            fits_data = read_fits(filename)
            result = classify_anomalies(fits_data["data"], fits_data.get("header", {}))

            if format == "json":
                return {
                    "filename": filename,
                    "exported_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "results": result,
                }

            # CSV format
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "anomaly_type", "confidence", "description",
                "image_mean", "image_std",
                "spike_sigma", "dip_sigma", "pattern_break_sigma",
            ])
            params = result.get("parameters_used", {})
            img_stats = result.get("image_stats", {})
            for anomaly in result.get("anomalies", []):
                writer.writerow([
                    anomaly.get("type", ""),
                    round(anomaly.get("confidence", 0), 4),
                    anomaly.get("description", ""),
                    round(img_stats.get("mean", 0), 6),
                    round(img_stats.get("std", 0), 6),
                    params.get("spike_sigma", ""),
                    params.get("dip_sigma", ""),
                    params.get("pattern_break_sigma", ""),
                ])

            csv_content = output.getvalue()
            return StreamingResponse(
                iter([csv_content]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=anomalies_{filename}.csv"},
            )
        except ImportError as e:
            return JSONResponse({"error": f"Module not available: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=500)

    @app.get("/pipeline/export/photometry")
    async def export_photometry(
        request: Request,
        filenames: str = Query(default="", description="Comma-separated FITS filenames"),
        format: str = Query(default="csv", pattern="^(csv|json)$"),
    ):
        """Export photometric statistics as CSV or JSON."""
        if not filenames:
            return JSONResponse({"error": "filenames parameter required"}, status_code=400)

        file_list = [f.strip() for f in filenames.split(",") if f.strip()]
        if not file_list:
            return JSONResponse({"error": "filenames parameter required"}, status_code=400)

        try:
            from .fits_core import read_fits
            import numpy as np

            results = []
            for fname in file_list:
                try:
                    fits_data = read_fits(fname)
                    data = fits_data["data"]
                    header = fits_data.get("header", {})
                    results.append({
                        "filename": fname,
                        "shape": list(data.shape),
                        "flux_min": round(float(np.min(data)), 6),
                        "flux_max": round(float(np.max(data)), 6),
                        "flux_mean": round(float(np.mean(data)), 6),
                        "flux_std": round(float(np.std(data)), 6),
                        "flux_median": round(float(np.median(data)), 6),
                        "naxis": fits_data.get("naxis", 0),
                        "band": header.get("FILTER", header.get("BAND", "unknown")),
                        "telescope": header.get("TELESCOP", "unknown"),
                    })
                except Exception as e:
                    results.append({"filename": fname, "error": str(e)[:200]})

            if format == "json":
                return {
                    "exported_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "results": results,
                    "count": len(results),
                }

            # CSV format
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "filename", "band", "telescope", "naxis",
                "flux_min", "flux_max", "flux_mean", "flux_std", "flux_median",
            ])
            for r in results:
                if "error" in r:
                    writer.writerow([r["filename"], "", "", "", "", "", "", "", r["error"]])
                else:
                    writer.writerow([
                        r["filename"], r.get("band", ""), r.get("telescope", ""),
                        r.get("naxis", ""),
                        r["flux_min"], r["flux_max"], r["flux_mean"],
                        r["flux_std"], r["flux_median"],
                    ])

            csv_content = output.getvalue()
            return StreamingResponse(
                iter([csv_content]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=photometry_export.csv"},
            )
        except ImportError as e:
            return JSONResponse({"error": f"Module not available: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=500)

    @app.get("/pipeline/export/sources")
    async def export_sources(
        request: Request,
        filename: str = Query(default="", description="FITS filename"),
        snr_threshold: float = Query(default=5.0, ge=1.0, le=50.0),
        format: str = Query(default="csv", pattern="^(csv|json)$"),
    ):
        """Export source detection catalog as CSV or JSON."""
        if not filename:
            return JSONResponse({"error": "filename parameter required"}, status_code=400)

        try:
            from .fits_core import read_fits, wcs_info
            from .source_extraction import detect_sources

            fits_data = read_fits(filename)
            data = fits_data["data"]
            sources = detect_sources(data, snr_threshold=snr_threshold)

            wcs = None
            try:
                wcs = wcs_info(filename)
            except Exception:
                pass

            results = []
            for i, src in enumerate(sources.get("sources", sources.get("results", []))):
                entry = {
                    "id": i + 1,
                    "x": round(float(src.get("x", 0)), 2),
                    "y": round(float(src.get("y", 0)), 2),
                    "flux": round(float(src.get("flux", 0)), 6),
                    "snr": round(float(src.get("snr", 0)), 2),
                    "fwhm": round(float(src.get("fwhm", 0)), 2) if src.get("fwhm") else "",
                }
                # Add sky coordinates if WCS available
                if wcs and src.get("x") and src.get("y"):
                    try:
                        from astropy.wcs import WCS
                        w = WCS(wcs)
                        sky = w.pixel_to_world(src["x"], src["y"])
                        entry["ra"] = round(float(sky.ra.deg), 6)
                        entry["dec"] = round(float(sky.dec.deg), 6)
                    except Exception:
                        entry["ra"] = ""
                        entry["dec"] = ""
                results.append(entry)

            if format == "json":
                return {
                    "filename": filename,
                    "snr_threshold": snr_threshold,
                    "exported_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "sources": results,
                    "count": len(results),
                }

            # CSV format
            output = io.StringIO()
            writer = csv.writer(output)
            has_sky = any("ra" in r for r in results)
            if has_sky:
                writer.writerow(["id", "ra", "dec", "x", "y", "flux", "snr", "fwhm"])
                for r in results:
                    writer.writerow([
                        r["id"], r.get("ra", ""), r.get("dec", ""),
                        r["x"], r["y"], r["flux"], r["snr"], r["fwhm"],
                    ])
            else:
                writer.writerow(["id", "x", "y", "flux", "snr", "fwhm"])
                for r in results:
                    writer.writerow([r["id"], r["x"], r["y"], r["flux"], r["snr"], r["fwhm"]])

            csv_content = output.getvalue()
            return StreamingResponse(
                iter([csv_content]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=sources_{filename}.csv"},
            )
        except ImportError as e:
            return JSONResponse({"error": f"Module not available: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=500)

    logger.info(
        "v4.38 routes registered: config admin (%s), provenance (%s), export (%s)",
        "Fix #3", "Fix #4", "Fix #6",
    )
