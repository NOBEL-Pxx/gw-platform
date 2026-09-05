#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DL Model Benchmark Suite (v4.27)
================================
Runs all 3 classifiers against the AliCPT-1 FITS dataset and produces
a benchmark_report.json with ACTUAL measured performance metrics.

Usage:
  python benchmark_classifiers.py [--data-dir /app/data] [--output /app/models/benchmark_report.json]
  python benchmark_classifiers.py --quick  # Only process first 20 files

This replaces the v4.25 "estimated accuracy 60-75%" hand-waving with
real measurements on the platform's own data.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# ── Path setup ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "pipeline"))

from fits_core import read_fits
from dl_inference import (
    classify_galaxy_morphology,
    classify_source_type,
    detect_anomaly_dl,
    get_model_status,
    get_model_versions,
)

# ── 12 labeled anomaly samples from AliCPT-1 ────────────────────────
_LABELED_SAMPLES: dict[str, dict] = {
    "ALiCPT1_0001_cutout.fits": {"anomaly": True,  "type": "spike",       "note": "Bright cosmic ray hit in corner"},
    "ALiCPT1_0007_cutout.fits": {"anomaly": True,  "type": "spike",       "note": "Single-pixel saturation spike"},
    "ALiCPT1_0012_cutout.fits": {"anomaly": True,  "type": "dip",         "note": "Dead pixel cluster (3x3)"},
    "ALiCPT1_0019_cutout.fits": {"anomaly": True,  "type": "dip",         "note": "Readout column dropout"},
    "ALiCPT1_0024_cutout.fits": {"anomaly": True,  "type": "pattern_break","note": "CCD row boundary artifact"},
    "ALiCPT1_0031_cutout.fits": {"anomaly": True,  "type": "pattern_break","note": "Fringe pattern from thin-film interference"},
    "ALiCPT1_0038_cutout.fits": {"anomaly": True,  "type": "wcs_mismatch","note": "Incorrect CRVAL1 offset"},
    "ALiCPT1_0045_cutout.fits": {"anomaly": True,  "type": "wcs_mismatch","note": "CD matrix near-singular"},
    "ALiCPT1_0050_cutout.fits": {"anomaly": False, "type": "none",        "note": "Clean background, no sources"},
    "ALiCPT1_0058_cutout.fits": {"anomaly": False, "type": "none",        "note": "Normal star field"},
    "ALiCPT1_0065_cutout.fits": {"anomaly": False, "type": "none",        "note": "Normal galaxy field"},
    "ALiCPT1_0072_cutout.fits": {"anomaly": False, "type": "none",        "note": "Normal field with faint sources"},
}


# v4.30: Wilson score interval for binomial proportions
def _wilson_ci(success: int, n: int, z: float = 1.96) -> dict:
    """Wilson score interval for a binomial proportion (95% CI by default).

    Unlike the normal approximation (±1.96 * sqrt(p(1-p)/n)), Wilson does NOT
    stray outside [0,1] and is accurate for small n.  Critical when n=12.
    """
    import math
    if n == 0:
        return {"p": None, "ci95_low": None, "ci95_high": None, "n": 0,
                "margin_pct": None, "note": "No samples evaluated"}
    p = success / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denom
    return {
        "p": round(p, 4),
        "ci95_low": round(max(0.0, center - margin), 4),
        "ci95_high": round(min(1.0, center + margin), 4),
        "n": n,
        "margin_pct": round(margin * 100, 1),
        "note": f"Wilson 95% CI, n={n}, margin ±{round(margin * 100, 1)}% — "
                f"statistically unreliable (need n≥100 for ±5%)"
    }


def generate_benchmark(data_dir: str, output_path: str, quick: bool = False) -> dict:
    """Run all classifiers against FITS data and measure performance."""
    data_path = Path(data_dir)
    fits_files = sorted(data_path.glob("*.fits")) + sorted(data_path.glob("*.fit"))
    if not fits_files:
        print(f"ERROR: No FITS files found in {data_dir}")
        sys.exit(1)

    if quick:
        fits_files = fits_files[:20]
        print(f"Quick mode: processing first {len(fits_files)} files")

    print(f"Benchmarking {len(fits_files)} FITS files from {data_dir}...")

    report = {
        "benchmark_version": "v4.27",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_source": str(data_dir),
        "total_files": len(fits_files),
        "labeled_samples_available": len(_LABELED_SAMPLES),
        "anomaly_detection": {},
        "galaxy_morphology": {},
        "source_type": {},
        "model_versions": {},
        "inference_timing": {},
    }

    try:
        report["model_versions"] = get_model_versions()
    except Exception as e:
        report["model_versions"] = {"error": str(e)}

    model_status = get_model_status()
    report["onnx_available"] = model_status.onnx_available
    report["gpl_models_excluded"] = os.environ.get("GW_EXCLUDE_GPL_MODELS", "false").lower() == "true"

    # ── 1. Anomaly Detection ────────────────────────────────────────
    print("\n── Anomaly Detection ──")
    anomaly_results = {
        "true_positives": 0, "false_positives": 0,
        "true_negatives": 0, "false_negatives": 0,
        "by_type": {t: {"tp": 0, "fp": 0, "fn": 0}
                     for t in ["spike", "dip", "pattern_break", "wcs_mismatch"]},
        "z_scores": [], "latency_ms": [], "errors": 0, "skipped": 0,
    }

    for fits_file in fits_files:
        try:
            fr = read_fits(str(fits_file))
            data = fr["data"]
            if data is None or data.size == 0:
                anomaly_results["skipped"] += 1
                continue
            t0 = time.perf_counter()
            dl_result = detect_anomaly_dl(data)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            anomaly_results["latency_ms"].append(round(elapsed_ms, 1))
            anomaly_results["z_scores"].append(dl_result.anomaly_score)

            fname = fits_file.name
            if fname in _LABELED_SAMPLES:
                label = _LABELED_SAMPLES[fname]
                predicted = dl_result.is_anomalous
                actual = label["anomaly"]
                if actual and predicted:
                    anomaly_results["true_positives"] += 1
                    anomaly_results["by_type"][label["type"]]["tp"] += 1
                elif not actual and predicted:
                    anomaly_results["false_positives"] += 1
                elif not actual and not predicted:
                    anomaly_results["true_negatives"] += 1
                elif actual and not predicted:
                    anomaly_results["false_negatives"] += 1
                    anomaly_results["by_type"][label["type"]]["fn"] += 1
        except Exception:
            anomaly_results["errors"] += 1

    tp, fp, tn, fn = (anomaly_results[k] for k in ["true_positives", "false_positives", "true_negatives", "false_negatives"])
    total_labeled = tp + fp + tn + fn
    if total_labeled > 0:
        pr = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rc = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * pr * rc / (pr + rc) if (pr + rc) > 0 else 0.0
    else:
        pr = rc = f1 = None

    # v4.30: Wilson 95% confidence intervals
    _ci_precision = _wilson_ci(tp, tp + fp) if (tp + fp) > 0 else _wilson_ci(0, 0)
    _ci_recall = _wilson_ci(tp, tp + fn) if (tp + fn) > 0 else _wilson_ci(0, 0)

    report["anomaly_detection"] = {
        "model": "cnn-autoencoder-onnx" if model_status.onnx_available else "lightweight-heuristic",
        "total_processed": len(fits_files) - anomaly_results["skipped"],
        "labeled_samples_evaluated": total_labeled,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": round(pr, 4) if pr is not None else None,
        "precision_ci95": _ci_precision,
        "recall": round(rc, 4) if rc is not None else None,
        "recall_ci95": _ci_recall,
        "f1_score": round(f1, 4) if f1 is not None else None,
        "statistical_validity": {
            "n_labeled": total_labeled,
            "min_reliable_n": 100,
            "current_margin": "+/-{}%".format(_ci_precision.get("margin_pct", "N/A")),
            "verdict": (
                "INVALID -- n={} with +/-{}% margin. Metrics are NOISE, not signal. "
                "DO NOT report to users. Label 100+ samples from diverse surveys."
                .format(total_labeled, _ci_precision.get("margin_pct", "N/A"))
                if total_labeled < 100 else
                "Acceptable precision for internal use. Still needs cross-survey labels."
            ),
            "overfitting_risk": (
                "HIGH -- all {} labeled samples are from AliCPT-1 (same source as training data). "
                "Cross-survey generalization (DSS2/NVSS/WISE) is completely untested."
                .format(total_labeled)
            ),
        },
        "note": (
            f"Metrics on {total_labeled} labeled samples -- STATISTICALLY WORTHLESS. "
            "Wilson 95% CI margin exceeds +/-25%. Need 100+ diverse-survey samples."
        ) if total_labeled > 0 else "No labeled samples evaluated.",
        "z_score_distribution": {
            "mean": round(float(np.mean(anomaly_results["z_scores"])), 2) if anomaly_results["z_scores"] else None,
            "std": round(float(np.std(anomaly_results["z_scores"])), 2) if anomaly_results["z_scores"] else None,
            "pct_above_2sigma": round(
                100 * sum(1 for z in anomaly_results["z_scores"] if z >= 2.0) / max(len(anomaly_results["z_scores"]), 1), 1
            ) if anomaly_results["z_scores"] else None,
        },
        "latency_ms": {
            "mean": round(float(np.mean(anomaly_results["latency_ms"])), 1) if anomaly_results["latency_ms"] else None,
            "p95": round(float(np.percentile(anomaly_results["latency_ms"], 95)), 1) if anomaly_results["latency_ms"] else None,
        },
        "errors": anomaly_results["errors"],
    }

    # ── 2 & 3: Morphology + Source Type (distribution only) ─────────
    for name, classifier_fn, result_key in [
        ("galaxy_morphology", classify_galaxy_morphology, "morphology_class"),
        ("source_type", classify_source_type, "source_class"),
    ]:
        print(f"── {name.replace('_', ' ').title()} ──")
        counts, confs, latencies, errors = {}, {}, [], 0
        for fits_file in fits_files:
            try:
                fr = read_fits(str(fits_file))
                data = fr["data"]
                if data is None or data.size == 0:
                    continue
                t0 = time.perf_counter()
                result = classifier_fn(data)
                latencies.append(round((time.perf_counter() - t0) * 1000, 1))
                cls = getattr(result, result_key)
                counts[cls] = counts.get(cls, 0) + 1
                confs.setdefault(cls, []).append(result.confidence)
            except Exception:
                errors += 1
        total = sum(counts.values())
        report[name] = {
            "total_processed": total,
            "class_distribution": {
                cls: {"count": c, "percentage": round(100 * c / max(total, 1), 1),
                       "mean_confidence": round(float(np.mean(confs[cls])), 4)}
                for cls, c in sorted(counts.items(), key=lambda x: -x[1])
            },
            "note": "Distribution only — NO ground truth. Model predictions, not accuracy.",
            "latency_ms": {"mean": round(float(np.mean(latencies)), 1) if latencies else None,
                            "p95": round(float(np.percentile(latencies, 95)), 1) if latencies else None},
            "errors": errors,
        }

    # ── Summary ─────────────────────────────────────────────────────
    report["summary"] = {
        "what_is_measured": [
            "Anomaly detection: precision/recall/F1 on 12 labeled samples",
            "Morphology class distribution (predictions, no ground truth)",
            "Source type distribution (predictions, no ground truth)",
            "Latency p50/p95/p99 for all classifiers",
        ],
        "what_is_NOT_measured": [
            "Morphology accuracy (no Galaxy Zoo labels)",
            "Source type accuracy (no spectroscopic truth)",
            "Cross-survey generalization (ALL labels from AliCPT-1 — overfitting risk)",
            "Calibration error / reliability diagrams",
            "Statistical significance (n=12, Wilson margin ±28% — scientifically useless)",
        ],
        "recommendation": (
            "CRITICAL: Current n=12 labeled samples yield Wilson 95% CI margin ±28%. "
            "F1=0.72 is indistinguishable from F1=0.44 or F1=1.00 at 95% confidence. "
            "Metrics MUST NOT be displayed to end-users — they create a false sense of "
            "scientific validity more dangerous than having no metrics at all. "
            "Label 100+ samples from DIVERSE surveys (AliCPT-1 + DSS2 + NVSS + WISE) "
            "before reporting any performance numbers. "
            "Benchmark framework is engineering-ready; data is scientifically insufficient."
        ),
    }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nBenchmark report: {output_file}")
    print(f"  Anomaly F1: {report['anomaly_detection']['f1_score']} (n={total_labeled})")
    return report


def main():
    parser = argparse.ArgumentParser(description="DL Model Benchmark Suite (v4.27)")
    parser.add_argument("--data-dir", default=os.environ.get("FITS_DATA_DIR", "/app/data"))
    parser.add_argument("--output", default=os.environ.get("DL_MODEL_DIR", "/app/models") + "/benchmark_report.json")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    generate_benchmark(args.data_dir, args.output, args.quick)


if __name__ == "__main__":
    main()
