#!/usr/bin/env python3
"""Batch FITS Validation Script — GravitationalWave Platform v4.8+"""
import argparse, json, os, sys, time
from collections import defaultdict
from pathlib import Path
import numpy as np

try:
    from astropy.io import fits as pyfits
    HAS_ASTROPY = True
except ImportError:
    HAS_ASTROPY = False

NEAR_ZERO_MEAN_THRESHOLD = 1e-6
NAN_FRACTION_THRESHOLD = 0.5
MIN_FILE_SIZE_BYTES = 2880
CONSTANT_STD_THRESHOLD = 1e-10
CRITICAL_HEADERS = ["NAXIS", "NAXIS1", "NAXIS2", "BITPIX"]


def find_fits_files(data_dir):
    fits_files = []
    for ext in (".fits", ".fit", ".fits.gz", ".fit.gz", ".fts"):
        fits_files.extend(data_dir.rglob("*" + ext))
    return sorted(fits_files)


def check_file_size(filepath):
    issues = []
    try:
        size = filepath.stat().st_size
        if size == 0:
            issues.append("ZERO_BYTES: file is empty")
        elif size < MIN_FILE_SIZE_BYTES:
            issues.append(f"TOO_SMALL: {size} bytes (min FITS block = {MIN_FILE_SIZE_BYTES})")
    except OSError as e:
        issues.append(f"UNREADABLE: {e}")
    return issues


def check_fits_content(filepath):
    issues, stats = [], {}
    if not HAS_ASTROPY:
        return issues, stats
    try:
        with pyfits.open(filepath, memmap=True) as hdul:
            for hdu_idx, hdu in enumerate(hdul):
                for key in CRITICAL_HEADERS:
                    if key not in hdu.header:
                        issues.append(f"HDU{hdu_idx}: missing header {key}")
            data_hdu = None
            for hdu in hdul:
                if hdu.data is not None and hdu.is_image and hdu.data.size > 0:
                    data_hdu = hdu
                    break
            if data_hdu is None:
                issues.append("NO_IMAGE_DATA")
                return issues, stats
            data = data_hdu.data.astype(np.float64)
            if hasattr(data, "filled"):
                data = data.filled(np.nan)
            data = np.nan_to_num(data, nan=np.nan, posinf=np.nan, neginf=np.nan)
            total = data.size
            nan_count = int(np.sum(np.isnan(data)))
            nan_frac = nan_count / total if total > 0 else 0.0
            finite = data[~np.isnan(data)]
            fc = finite.size
            if nan_frac < 0.01:
                zc = int(np.sum(data == 0))
                zf = zc / total if total > 0 else 0.0
                if zf > 0.9999:
                    issues.append(f"ALL_ZERO: {zc}/{total} px ({zf*100:.1f}%) — LEGACY export error")
                elif zf > 0.95:
                    issues.append(f"MOSTLY_ZERO: {zc}/{total} px ({zf*100:.1f}%)")
            if nan_frac > NAN_FRACTION_THRESHOLD:
                issues.append(f"NAN_DOMINANT: {nan_count}/{total} px ({nan_frac*100:.1f}%)")
            if fc > 1:
                std = float(np.std(finite))
                if std < CONSTANT_STD_THRESHOLD:
                    issues.append(f"CONSTANT_VALUE: std={std:.2e}")
            if fc > 0:
                mean = float(np.mean(np.abs(finite)))
                if mean < NEAR_ZERO_MEAN_THRESHOLD:
                    issues.append(f"NEAR_ZERO_SIGNAL: mean(|px|)={mean:.2e}")
            stats = {
                "shape": list(data.shape),
                "min": float(np.min(finite)) if fc else None,
                "max": float(np.max(finite)) if fc else None,
                "mean": float(np.mean(finite)) if fc else None,
                "std": float(np.std(finite)) if fc else None,
                "nan_frac": round(nan_frac, 4),
                "zero_frac": round(float(np.sum(data == 0)) / total, 4) if nan_frac < 0.01 else None,
            }
    except Exception as e:
        issues.append(f"CORRUPT: {e}")
    return issues, stats


def get_survey(filepath, data_dir):
    try:
        parts = filepath.relative_to(data_dir).parts
        return parts[0] if len(parts) > 1 else "(root)"
    except ValueError:
        return "(unknown)"


def main():
    p = argparse.ArgumentParser(description="Batch FITS Validation — GravitationalWave Platform")
    p.add_argument("--data-dir", default=os.environ.get("FITS_DATA_DIR", "./sample_data/fitsfile"))
    p.add_argument("--output", choices=["text", "json"], default="text")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--report-file")
    args = p.parse_args()
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.is_dir():
        print(f"ERROR: {data_dir}", file=sys.stderr)
        sys.exit(2)
    print(f"Scanning: {data_dir}")
    t0 = time.time()
    files = find_fits_files(data_dir)
    n = len(files)
    print(f"Found {n} FITS file(s)\n")
    if n == 0:
        print("No FITS files found.")
        sys.exit(0)
    results = {}
    surveys = defaultdict(lambda: {"total": 0, "clean": 0, "dirty": 0})
    for i, fp in enumerate(files, 1):
        sv = get_survey(fp, data_dir)
        surveys[sv]["total"] += 1
        rp = str(fp.relative_to(data_dir))
        issues = check_file_size(fp)
        ci, st = check_fits_content(fp)
        issues.extend(ci)
        if issues:
            surveys[sv]["dirty"] += 1
            if args.output == "text":
                print(f"[{i}/{n}] FAIL {rp}")
                for iss in issues:
                    print(f"       -> {iss}")
                if args.verbose and st:
                    print(f"       stats: {json.dumps(st, default=str)}")
                print()
        else:
            surveys[sv]["clean"] += 1
            if args.verbose:
                detail = json.dumps(st, default=str) if st else ""
                print(f"[{i}/{n}] OK   {rp}  {detail}")
        results[rp] = {"survey": sv, "issues": issues, "stats": st, "status": "dirty" if issues else "clean"}
    elapsed = time.time() - t0
    dirty = sum(1 for r in results.values() if r["status"] == "dirty")
    clean = n - dirty
    if args.output == "json":
        out = {
            "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "data_dir": str(data_dir),
            "total_files": n, "clean": clean, "dirty": dirty,
            "elapsed_seconds": round(elapsed, 2),
            "surveys": {s: {"total": v["total"], "clean": v["clean"], "dirty": v["dirty"]}
                        for s, v in sorted(surveys.items())},
            "issues": {rel: r for rel, r in sorted(results.items()) if r["status"] == "dirty"},
        }
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        print("=" * 72)
        print("SUMMARY")
        print("=" * 72)
        print(f"  Files: {n}  Clean: {clean}  Issues: {dirty}  Time: {elapsed:.1f}s\n")
        print(f"  {'Survey':<16} {'Total':>6} {'Clean':>6} {'Dirty':>6} {'Rate':>8}")
        print(f"  {'-'*16} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
        for sv in sorted(surveys):
            s = surveys[sv]
            rate = s["clean"] / s["total"] * 100 if s["total"] else 0
            print(f"  {sv:<16} {s['total']:>6} {s['clean']:>6} {s['dirty']:>6} {rate:>7.1f}%")
        if dirty:
            print(f"\nFiles with issues ({dirty}):")
            for rel, r in sorted(results.items()):
                if r["status"] == "dirty":
                    print(f"  [{r['survey']}] {rel}")
                    for iss in r["issues"]:
                        print(f"    -> {iss}")
    if args.report_file:
        report = {
            "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "data_dir": str(data_dir),
            "total_files": n, "clean": clean, "dirty": dirty,
            "elapsed_seconds": round(elapsed, 2),
            "surveys": {s: {"total": v["total"], "clean": v["clean"], "dirty": v["dirty"]}
                        for s, v in sorted(surveys.items())},
            "issues": {rel: {"survey": r["survey"], "issues": r["issues"]}
                       for rel, r in sorted(results.items()) if r["status"] == "dirty"},
        }
        with open(args.report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nReport saved: {args.report_file}")
    if dirty:
        print(f"\nWARNING: {dirty} file(s) have issues.")
        sys.exit(1)
    else:
        print("\nAll FITS files pass validation.")
        sys.exit(0)


if __name__ == "__main__":
    main()
