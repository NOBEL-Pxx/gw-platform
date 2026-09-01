"""
DL routes (R6.24+) -- DL inference / anomaly classifier dispatch.

Endpoints planned for this module:
    POST /dl/anomaly                -- run anomaly_classifier pipeline
    POST /dl/classify               -- run supervised classifier (model registry)
    POST /dl/inference              -- generic ONNX model inference
    GET  /dl/models                 -- list loaded models + versions

Helpers exported:
    dl_helpers.load_anomaly_detectors()      -- routes to anomaly.registry
    dl_helpers.run_classifier_pipeline()     -- wraps dl_inference
    dl_helpers.record_inference_metrics()    -- ai_metrics logging

Dependency on the new anomaly/ package:
    from pipeline.anomaly import load_detectors, classify_anomalies
    detectors = load_detectors(["spike", "wcs"])  # subset for fast path
    results = classify_anomalies(data, wcs, detectors=["spike", "wcs"])
"""
from __future__ import annotations

from typing import Any


class _DlHelpers:
    """Namespace for DL-related pure functions."""

    def load_anomaly_detectors(self, names: list[str] | None = None) -> list[Any]:
        # New code path (preferred):
        from pipeline.anomaly import load_detectors
        return load_detectors(names)

    def run_classifier_pipeline(self, data, model_name: str) -> dict[str, Any]:
        from pipeline.server import run_classifier_pipeline
        return run_classifier_pipeline(data, model_name)

    def record_inference_metrics(self, model_name: str, latency_ms: float,
                                  confidence: float) -> None:
        from pipeline.server import record_inference_metrics
        return record_inference_metrics(model_name, latency_ms, confidence)


dl_helpers = _DlHelpers()


try:
    from fastapi import APIRouter
    router = APIRouter()
    # R6.24.4: @router.post("/anomaly") etc.
except ImportError:
    router = None


__all__ = ["dl_helpers", "router"]
