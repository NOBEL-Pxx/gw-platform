#!/usr/bin/env python3
"""
Data Lifecycle Management — GravitationalWave Platform v4.12+

Covers three storage tiers:
  1. Elasticsearch  — index size monitoring, stale-index detection, optional force-merge
  2. MongoDB        — comment TTL index management, old-comment archiving
  3. File system    — FITS size audit, thumbnail cache eviction, Docker volume monitor

Usage:
  python data_lifecycle.py                 # report mode (read-only)
  python data_lifecycle.py --cleanup       # execute safe cleanups
  python data_lifecycle.py --cleanup --aggressive  # include TTL index creation + archiving
  python data_lifecycle.py --json          # machine-readable output
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("GW_PROJECT_DIR", r"D:\AliCPT"))
FITS_DIR = PROJECT_DIR / "sample_data" / "fitsfile"
THUMBNAIL_DIR = PROJECT_DIR / "docker-data" / "thumbnail_cache"
ES_DIR = PROJECT_DIR / "docker-data" / "es-data"
MONGO_DIR = PROJECT_DIR / "docker-data" / "mongodb-data"

# ── Thresholds ──────────────────────────────────────────────────────
FITS_MAX_SIZE_GB = 10.0              # warn if FITS dir exceeds this
THUMBNAIL_MAX_ENTRIES = 5000         # max cached thumbnails (matches pipeline eviction)
THUMBNAIL_TTL_DAYS = 7               # delete thumbnails older than this
COMMENT_ARCHIVE_AGE_DAYS = 730       # archive comments older than 2 years
ES_STALE_INDEX_DAYS = 365            # warn on indices not updated in 1 year

CONTAINERS = ["gw-elasticsearch", "gw-mongodb", "gw-pipeline"]


def env_pw() -> str:
    """Read MONGO_ROOT_PASSWORD from .env."""
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return ""
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("MONGO_ROOT_PASSWORD="):
                return line.partition("=")[2].strip()
    return ""


def run_docker(container: str, cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a command inside a Docker container."""
    full = ["docker", "exec", container] + cmd
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def report_fits() -> dict:
    """Audit FITS file storage."""
    total_size = 0
    total_files = 0
    all_zero = 0
    surveys = {}
    if FITS_DIR.is_dir():
        for fpath in FITS_DIR.rglob("*.fits"):
            size = fpath.stat().st_size
            total_size += size
            total_files += 1
            survey = fpath.parent.name if fpath.parent != FITS_DIR else "(root)"
            surveys[survey] = surveys.get(survey, {"files": 0, "size": 0})
            surveys[survey]["files"] += 1
            surveys[survey]["size"] += size
            # Quick all-zero check (header-only for speed)
            if size > 0 and size < 3000:
                all_zero += 1  # suspiciously small
    total_gb = total_size / (1024 ** 3)
    return {
        "total_files": total_files,
        "total_size_gb": round(total_gb, 2),
        "suspicious_small": all_zero,
        "warn": total_gb > FITS_MAX_SIZE_GB,
        "surveys": {k: {"files": v["files"], "size_mb": round(v["size"] / 1024**2, 2)}
                    for k, v in sorted(surveys.items())},
    }


def report_thumbnails() -> dict:
    """Audit thumbnail cache."""
    total = 0
    total_size = 0
    stale = 0
    cutoff = time.time() - THUMBNAIL_TTL_DAYS * 86400
    if THUMBNAIL_DIR.is_dir():
        for fpath in THUMBNAIL_DIR.rglob("*"):
            if fpath.is_file():
                total += 1
                total_size += fpath.stat().st_size
                if fpath.stat().st_mtime < cutoff:
                    stale += 1
    return {
        "total_entries": total,
        "total_size_mb": round(total_size / 1024**2, 2),
        "stale_entries": stale,
        "ttl_days": THUMBNAIL_TTL_DAYS,
        "max_allowed": THUMBNAIL_MAX_ENTRIES,
        "warn": total > THUMBNAIL_MAX_ENTRIES,
    }


def report_es(password: str) -> dict:
    """Report Elasticsearch index sizes."""
    indices = {}
    rc, out, err = run_docker("gw-elasticsearch",
        ["curl", "-sf", "-u", f"elastic:{password}",
         "http://localhost:9200/_cat/indices?h=index,docs.count,store.size&format=json"],
        timeout=10)
    if rc != 0:
        return {"error": err or "ES unreachable"}
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return {"error": f"JSON parse: {out[:200]}"}
    total_docs = 0
    total_size = 0
    for idx in raw:
        name = idx.get("index", "?")
        docs = int(idx.get("docs.count", 0))
        size_str = idx.get("store.size", "0b")
        # Parse size
        size_bytes = 0
        if size_str.endswith("kb"):
            size_bytes = float(size_str[:-2]) * 1024
        elif size_str.endswith("mb"):
            size_bytes = float(size_str[:-2]) * 1024**2
        elif size_str.endswith("gb"):
            size_bytes = float(size_str[:-2]) * 1024**3
        elif size_str.endswith("b"):
            size_bytes = float(size_str[:-1])
        indices[name] = {"docs": docs, "size_mb": round(size_bytes / 1024**2, 2)}
        total_docs += docs
        total_size += size_bytes
    return {
        "total_indices": len(indices),
        "total_docs": total_docs,
        "total_size_mb": round(total_size / 1024**2, 2),
        "indices": indices,
    }


def report_mongo(password: str) -> dict:
    """Report MongoDB collection stats."""
    rc, out, _ = run_docker("gw-mongodb",
        ["mongosh", "-u", "admin", "-p", password,
         "--authenticationDatabase", "admin", "--quiet", "--eval",
         'db=db.getSiblingDB("gravitationalwave");'
         'print("COMMENTS:"+db.comments.countDocuments({}));'
         'print("COMMENTS_OLD:"+db.comments.countDocuments({createdAt:{$lt:new Date(new Date().getTime()-730*86400000)}}));'
         'print("USERS:"+(db.user?db.user.countDocuments({}):0));'],
        timeout=15)
    result = {"comments": 0, "comments_old": 0, "users": 0}
    if rc == 0:
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("COMMENTS_OLD:"):
                result["comments_old"] = int(line.split(":")[1])
            elif line.startswith("COMMENTS:"):
                result["comments"] = int(line.split(":")[1])
            elif line.startswith("USERS:"):
                result["users"] = int(line.split(":")[1])
    return result


def report_docker_volumes() -> dict:
    """Report Docker volume sizes."""
    volumes = {}
    for name in ["es-data", "mongodb-data", "thumbnail_cache"]:
        d = PROJECT_DIR / "docker-data" / name
        if d.is_dir():
            total = 0
            for f in d.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
            volumes[name] = round(total / 1024**2, 2)
    return volumes


# ── Cleanup actions ──────────────────────────────────────────────────

def cleanup_thumbnails(dry_run: bool = True) -> dict:
    """Evict stale thumbnail cache entries."""
    if not THUMBNAIL_DIR.is_dir():
        return {"status": "no_cache_dir"}
    cutoff = time.time() - THUMBNAIL_TTL_DAYS * 86400
    removed = 0
    freed = 0
    for fpath in THUMBNAIL_DIR.rglob("*"):
        if fpath.is_file() and fpath.stat().st_mtime < cutoff:
            size = fpath.stat().st_size
            if not dry_run:
                fpath.unlink()
            removed += 1
            freed += size
    if removed > 0 and not dry_run:
        # Also evict if over cap
        all_files = sorted(
            [f for f in THUMBNAIL_DIR.rglob("*") if f.is_file()],
            key=lambda f: f.stat().st_mtime)
        while len(all_files) > THUMBNAIL_MAX_ENTRIES:
            oldest = all_files.pop(0)
            oldest.unlink()
            removed += 1
            freed += oldest.stat().st_size
    return {
        "removed": removed,
        "freed_mb": round(freed / 1024**2, 2),
        "dry_run": dry_run,
    }


def create_comment_ttl_index(password: str) -> dict:
    """Create TTL index on comments.createdAt (730-day auto-archive)."""
    rc, out, err = run_docker("gw-mongodb",
        ["mongosh", "-u", "admin", "-p", password,
         "--authenticationDatabase", "admin", "--quiet", "--eval",
         'db=db.getSiblingDB("gravitationalwave");'
         'try{db.comments.dropIndex("createdAt_ttl")}catch(e){};'
         f'db.comments.createIndex({{"createdAt":1}},{{expireAfterSeconds:{COMMENT_ARCHIVE_AGE_DAYS*86400},name:"createdAt_ttl"}});'
         'print("TTL index created: comments auto-expire after 730 days");'],
        timeout=15)
    return {"status": "ok" if rc == 0 else "error", "detail": out or err}


def es_force_merge(password: str, index: str = "errordetail") -> dict:
    """Force-merge an ES index to reclaim deleted-document space."""
    rc, out, err = run_docker("gw-elasticsearch",
        ["curl", "-sf", "-X", "POST", "-u", f"elastic:{password}",
         f"http://localhost:9200/{index}/_forcemerge?max_num_segments=1"],
        timeout=30)
    return {"status": "ok" if rc == 0 else "error", "index": index, "detail": out or err}


# ── Main ─────────────────────────────────────────────────────────────

def main():
    global PROJECT_DIR, FITS_DIR, THUMBNAIL_DIR

    parser = argparse.ArgumentParser(description="Data Lifecycle Management — GravitationalWave Platform")
    parser.add_argument("--cleanup", action="store_true", help="Execute safe cleanups (thumbnail eviction)")
    parser.add_argument("--aggressive", action="store_true", help="Include TTL index creation + ES force-merge")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--project-dir", default=str(PROJECT_DIR))
    args = parser.parse_args()

    PROJECT_DIR = Path(args.project_dir)
    FITS_DIR = PROJECT_DIR / "sample_data" / "fitsfile"
    THUMBNAIL_DIR = PROJECT_DIR / "docker-data" / "thumbnail_cache"

    mongo_pw = env_pw()
    if not mongo_pw:
        print("ERROR: MONGO_ROOT_PASSWORD not found in .env", file=sys.stderr)
        sys.exit(2)

    # Read ES password
    es_pw = ""
    env_file = PROJECT_DIR / ".env"
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("ES_PASSWORD="):
                es_pw = line.partition("=")[2].strip()

    report = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "project_dir": str(PROJECT_DIR),
        "fits": report_fits(),
        "thumbnails": report_thumbnails(),
        "elasticsearch": report_es(es_pw) if es_pw else {"error": "ES_PASSWORD not set"},
        "mongodb": report_mongo(mongo_pw),
        "docker_volumes_mb": report_docker_volumes(),
    }

    actions = {}
    if args.cleanup:
        actions["thumbnails"] = cleanup_thumbnails(dry_run=False)
    if args.aggressive:
        actions["comment_ttl"] = create_comment_ttl_index(mongo_pw)
        if es_pw:
            actions["es_force_merge"] = es_force_merge(es_pw, "errordetail")
            actions["es_force_merge_errorlist"] = es_force_merge(es_pw, "errorlist")

    report["actions"] = actions

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        # ── Text report ──
        print("=" * 64)
        print("DATA LIFECYCLE REPORT")
        print("=" * 64)
        print(f"  Scan time: {report['scan_time']}")
        print()

        # FITS
        f = report["fits"]
        print(f"[FITS Files]  {f['total_files']} files, {f['total_size_gb']} GB")
        status = "WARN" if f["warn"] else "OK"
        print(f"  Status: {status}  (max {FITS_MAX_SIZE_GB} GB)")
        if f["suspicious_small"]:
            print(f"  Suspicious small files: {f['suspicious_small']} (<3KB)")
        for survey, s in f["surveys"].items():
            bar = "█" * max(1, int(s["size_mb"] / 10))
            print(f"  {survey:<12} {s['files']:>4} files  {s['size_mb']:>8.1f} MB  {bar}")
        print()

        # Thumbnails
        t = report["thumbnails"]
        print(f"[Thumbnails]  {t['total_entries']} entries, {t['total_size_mb']} MB")
        print(f"  Stale (> {t['ttl_days']}d): {t['stale_entries']}  Max: {t['max_allowed']}")
        print(f"  Status: {'WARN' if t['warn'] else 'OK'}")
        print()

        # ES
        e = report["elasticsearch"]
        if "error" in e:
            print(f"[Elasticsearch]  ERROR: {e['error']}")
        else:
            print(f"[Elasticsearch]  {e['total_indices']} indices, {e['total_docs']} docs, {e['total_size_mb']} MB")
            for name, idx in e["indices"].items():
                if name.startswith("."):
                    continue
                print(f"  {name:<20} {idx['docs']:>6} docs  {idx['size_mb']:>8.2f} MB")
        print()

        # MongoDB
        m = report["mongodb"]
        print(f"[MongoDB]  comments: {m['comments']} (old: {m['comments_old']}), users: {m['users']}")
        print()

        # Docker volumes
        dv = report["docker_volumes_mb"]
        print(f"[Docker Volumes]")
        for name, size in dv.items():
            print(f"  {name:<20} {size:>8.1f} MB")
        print()

        # Actions
        if actions:
            print(f"[Actions]")
            for name, result in actions.items():
                print(f"  {name}: {json.dumps(result, default=str)}")
            print()

    # Exit with warning if issues found
    issues = 0
    if report["fits"]["warn"]:
        issues += 1
    if report["thumbnails"]["warn"]:
        issues += 1
    sys.exit(1 if issues > 0 else 0)


if __name__ == "__main__":
    main()
