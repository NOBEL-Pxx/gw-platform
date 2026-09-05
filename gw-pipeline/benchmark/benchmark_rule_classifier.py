#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rule-Based Anomaly Classifier — Synthetic Benchmark (v4.28)
===========================================================
Generates synthetic FITS images with controlled anomaly injections and
measures the rule classifier's actual detection performance.

Each anomaly type gets:
  - N positive samples (anomaly injected at known location + intensity)
  - N negative samples (clean data, no anomaly)
  - Precision/Recall/F1 computed per type and globally

Output: benchmark_rule_report.json written to DL_MODEL_DIR.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "pipeline"))
from anomaly_classifier import classify_anomalies

# ── Synthetic FITS generation parameters ────────────────────────────
_IMAGE_SIZE = 256          # pixels (square)
_N_SAMPLES_PER_TYPE = 50   # positive + negative samples per anomaly type
_BACKGROUND_MEAN = 100.0
_BACKGROUND_STD = 5.0
_RNG = np.random.RandomState(42)


def _make_clean_fits() -> np.ndarray:
    """Generate a clean synthetic FITS image with Gaussian background noise."""
    return _RNG.normal(_BACKGROUND_MEAN, _BACKGROUND_STD, (_IMAGE_SIZE, _IMAGE_SIZE))


def _inject_spike(data: np.ndarray, intensity: float = 50.0) -> tuple[np.ndarray, dict]:
    """Inject a bright spike (cosmic ray) at a random location."""
    x = _RNG.randint(10, _IMAGE_SIZE - 10)
    y = _RNG.randint(10, _IMAGE_SIZE - 10)
    radius = _RNG.randint(1, 4)
    result = data.copy()
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx*dx + dy*dy <= radius*radius:
                ny, nx = y + dy, x + dx
                if 0 <= ny < _IMAGE_SIZE and 0 <= nx < _IMAGE_SIZE:
                    result[ny, nx] += intensity * (1 - (dx*dx + dy*dy) / (radius*radius + 1))
    return result, {"type": "spike", "x": x, "y": y, "intensity": intensity, "radius": radius}


def _inject_dip(data: np.ndarray, depth: float = 40.0) -> tuple[np.ndarray, dict]:
    """Inject a dark dip (dead pixel cluster)."""
    x = _RNG.randint(10, _IMAGE_SIZE - 10)
    y = _RNG.randint(10, _IMAGE_SIZE - 10)
    rx = _RNG.randint(1, 3)
    ry = _RNG.randint(1, 3)
    result = data.copy()
    result[y:y+ry, x:x+rx] -= depth
    return result, {"type": "dip", "x": x, "y": y, "width": rx, "height": ry, "depth": depth}


def _inject_pattern_break(data: np.ndarray, amplitude: float = 30.0) -> tuple[np.ndarray, dict]:
    """Inject a row artifact (bad scan line)."""
    row = _RNG.randint(20, _IMAGE_SIZE - 20)
    width = _RNG.randint(1, 3)
    result = data.copy()
    for w in range(width):
        if row + w < _IMAGE_SIZE:
            result[row + w, :] += _RNG.normal(amplitude, 3, _IMAGE_SIZE)
    return result, {"type": "pattern_break", "row": row, "width": width, "amplitude": amplitude}


def _inject_wcs_mismatch() -> tuple[dict, dict]:
    """Generate a WCS metadata anomaly (no pixel injection needed)."""
    issue_type = _RNG.choice(["crval", "cd_matrix", "pixel_scale"])
    if issue_type == "crval":
        wcs_bad = {"CRVAL1": 999.0, "CRVAL2": 999.0}  # out of range
    elif issue_type == "cd_matrix":
        wcs_bad = {"CD1_1": 0.0, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.0}  # singular
    else:
        wcs_bad = {"CDELT1": 10.0, "CDELT2": 10.0}  # absurd pixel scale
    return wcs_bad, {"type": "wcs_mismatch", "issue": issue_type}


# Normal WCS metadata
_NORMAL_WCS = {"CRVAL1": 180.0, "CRVAL2": 45.0, "CDELT1": 0.00028, "CDELT2": 0.00028,
               "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRPIX1": 128, "CRPIX2": 128}


def run_benchmark(output_path: str) -> dict:
    """Run the full synthetic benchmark and write report."""
    n = _N_SAMPLES_PER_TYPE
    results = {"spike": [], "dip": [], "pattern_break": [], "wcs_mismatch": []}
    latencies = []

    for anomaly_type, injector in [
        ("spike", _inject_spike),
        ("dip", _inject_dip),
        ("pattern_break", _inject_pattern_break),
    ]:
        print(f"  Benchmarking {anomaly_type}...")
        for i in range(n):
            # Positive: anomaly injected
            clean = _make_clean_fits()
            injected, truth = injector(clean)
            t0 = time.perf_counter()
            r = classify_anomalies(injected, _NORMAL_WCS, spike_sigma=4.0, dip_sigma=4.0, pattern_break_sigma=3.5)
            latencies.append((time.perf_counter() - t0) * 1000)

            # Check if anomaly was detected (any anomaly of that type found)
            detected = any(a["type"] == anomaly_type and a["confidence"] > 0.3 for a in r["anomalies"])
            results[anomaly_type].append({"truth": "positive", "detected": detected, "confidence": r.get("anomalies", [{}])[0].get("confidence", 0) if r.get("anomalies") else 0})

            # Negative: clean data
            clean2 = _make_clean_fits()
            r_neg = classify_anomalies(clean2, _NORMAL_WCS, spike_sigma=4.0, dip_sigma=4.0, pattern_break_sigma=3.5)
            latencies.append((time.perf_counter() - t0) * 1000)
            false_alarm = any(a["type"] == anomaly_type and a["confidence"] > 0.3 for a in r_neg["anomalies"])
            results[anomaly_type].append({"truth": "negative", "detected": false_alarm, "confidence": r_neg.get("anomalies", [{}])[0].get("confidence", 0) if r_neg.get("anomalies") else 0})

    # WCS mismatch: only needs metadata injection, no pixel changes
    print("  Benchmarking wcs_mismatch...")
    for i in range(n):
        wcs_bad, truth = _inject_wcs_mismatch()
        clean = _make_clean_fits()
        t0 = time.perf_counter()
        r = classify_anomalies(clean, wcs_bad, spike_sigma=4.0, dip_sigma=4.0, pattern_break_sigma=3.5)
        latencies.append((time.perf_counter() - t0) * 1000)
        detected = any(a["type"] == "wcs_mismatch" for a in r["anomalies"])
        results["wcs_mismatch"].append({"truth": "positive", "detected": detected})

        r_neg = classify_anomalies(clean, _NORMAL_WCS)
        false_alarm = any(a["type"] == "wcs_mismatch" for a in r_neg["anomalies"])
        results["wcs_mismatch"].append({"truth": "negative", "detected": false_alarm})

    # ── Compute metrics ────────────────────────────────────────────
    report = {
        "benchmark_version": "v4.28",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "synthetic_injection",
        "total_test_samples": n * 2 * 4,  # 4 types x n positives + n negatives
        "samples_per_type": n,
        "image_size": _IMAGE_SIZE,
        "thresholds_used": {"spike_sigma": 4.0, "dip_sigma": 4.0, "pattern_break_sigma": 3.5},
        "per_type": {},
        "global": {},
        "latency_ms": {},
    }

    global_tp = global_fp = global_fn = global_tn = 0
    for atype in ["spike", "dip", "pattern_break", "wcs_mismatch"]:
        res = results[atype]
        tp = sum(1 for r in res if r["truth"] == "positive" and r["detected"])
        fp = sum(1 for r in res if r["truth"] == "negative" and r["detected"])
        fn = sum(1 for r in res if r["truth"] == "positive" and not r["detected"])
        tn = sum(1 for r in res if r["truth"] == "negative" and not r["detected"])
        pr = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rc = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * pr * rc / (pr + rc) if (pr + rc) > 0 else 0.0
        report["per_type"][atype] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(pr, 4),
            "recall": round(rc, 4),
            "f1": round(f1, 4),
            "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0,
        }
        global_tp += tp; global_fp += fp; global_fn += fn; global_tn += tn

    gpr = global_tp / (global_tp + global_fp) if (global_tp + global_fp) > 0 else 0.0
    grc = global_tp / (global_tp + global_fn) if (global_tp + global_fn) > 0 else 0.0

    report["global"] = {
        "tp": global_tp, "fp": global_fp, "fn": global_fn, "tn": global_tn,
        "precision": round(gpr, 4),
        "recall": round(grc, 4),
        "f1": round(2 * gpr * grc / (gpr + grc), 4) if (gpr + grc) > 0 else 0.0,
    }

    lats = np.array(latencies)
    report["latency_ms"] = {
        "mean": round(float(lats.mean()), 1),
        "p50": round(float(np.percentile(lats, 50)), 1),
        "p95": round(float(np.percentile(lats, 95)), 1),
        "max": round(float(lats.max()), 1),
    }
    report["note"] = (
        f"Measured on {n*2*4} synthetic FITS images ({_IMAGE_SIZE}x{_IMAGE_SIZE}). "
        "Synthetic data is cleaner than real survey data — real-world performance "
        "may be LOWER due to noise, source confusion, and instrumental artifacts. "
        "These metrics replace the v4.26 'benchmark unknown' hand-waving with "
        "actual controlled measurements."
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nRule Classifier Benchmark Results:")
    for atype, m in report["per_type"].items():
        print(f"  {atype:18s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}")
    print(f"  {'GLOBAL':18s}  P={report['global']['precision']:.3f}  R={report['global']['recall']:.3f}  F1={report['global']['f1']:.3f}")
    print(f"\nReport: {output_file}")
    return report


if __name__ == "__main__":
    out = os.environ.get("DL_MODEL_DIR", "/app/models") + "/benchmark_rule_report.json"
    run_benchmark(out)
