"""
Anomaly detector package (R6.24+).

Replaces the monolithic `anomaly_classifier.py` with a strategy pattern:

    base.py             - AnomalyDetector abstract base class + AnomalyResult dataclass
    spike.py            - SpikeDetector   (bright outliers)
    dip.py              - DipDetector     (dark defects)
    pattern_break.py    - PatternBreakDetector (row/column artefacts + 2D-FFT)
    wcs.py              - WcsMismatchDetector   (CRVAL/CD matrix validation)
    registry.py         - DETECTOR_REGISTRY + load_all_detectors()

Backward compatibility:
    from pipeline.anomaly import classify_anomalies  # works (routes to registry)
    from pipeline.anomaly import spike_detector      # works (routes to SpikeDetector.detect)

Why strategy pattern:
- Each detector gets its own file (<200 lines, fits pipeline complexity budget)
- Adding a new detector = drop a file in this package, no edits to base/registry
- Easy to A/B test: load_detectors(['spike', 'wcs']) instead of all four
- Unit-testable in isolation
"""
from __future__ import annotations

from pipeline.anomaly.base import (
    AnomalyDetector,
    AnomalyResult,
    PixelRegion,
    confidence_from_snrs,
    extract_regions,
    local_stats,
)
from pipeline.anomaly.registry import (
    DETECTOR_REGISTRY,
    classify_anomalies,
    load_detectors,
)
from pipeline.anomaly.spike import SpikeDetector
from pipeline.anomaly.dip import DipDetector
from pipeline.anomaly.pattern_break import PatternBreakDetector
from pipeline.anomaly.wcs import WcsMismatchDetector


__all__ = [
    # Base / types
    "AnomalyDetector",
    "AnomalyResult",
    "PixelRegion",
    "local_stats",
    "extract_regions",
    "confidence_from_snrs",
    # Detectors
    "SpikeDetector",
    "DipDetector",
    "PatternBreakDetector",
    "WcsMismatchDetector",
    # Registry
    "DETECTOR_REGISTRY",
    "classify_anomalies",
    "load_detectors",
]
