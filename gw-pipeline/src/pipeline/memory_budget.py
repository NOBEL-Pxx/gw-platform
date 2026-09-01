#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R6.26 — Startup-time memory budget calculation.

Replaces hardcoded constants like THUMBNAIL_CACHE_SIZE=5000 and
DL_MAX_CONCURRENT_INFERENCE=3 with values derived from the actual container
memory limit (read at process startup from /sys/fs/cgroup or /proc/meminfo).

Budget allocation (default for a 1GB container):
  ┌─────────────────────────────────────────────────────┐
  │ OS + Python runtime + framework (FastAPI, etc.)    │ ~150 MB (fixed)
  │ ONNX models (3 loaded, ~150 MB each)               │ ~450 MB
  │ FITS decode buffers (peak)                         │ ~120 MB
  │ Free pool (for spikes, GC headroom)                │ ~80 MB
  │ Thumbnail LRU cache                                │ ~200 MB (tunable)
  └─────────────────────────────────────────────────────┘

The thumbnail cache size is computed as: budget_for_cache / avg_thumb_bytes.
The DL inference concurrency is bounded by both memory (model size) and CPU.

Usage (server.py startup):
    from memory_budget import print_budget_report, get_thumbnail_cache_size, get_max_concurrent_inferences
    print_budget_report()
    THUMBNAIL_CACHE_SIZE = get_thumbnail_cache_size()  # was hardcoded 5000
    DL_MAX_CONCURRENT = get_max_concurrent_inferences()  # was hardcoded 3

Environment overrides (all optional):
  GW_MEMORY_LIMIT_MB       — override detected container limit
  GW_THUMBNAIL_BUDGET_MB   — override thumbnail cache budget
  GW_DL_MODEL_SIZE_MB      — override per-ONNX-model size estimate
"""
from __future__ import annotations

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


# ── Detection helpers ────────────────────────────────────────────────────
def _detect_container_memory_limit_mb() -> int:
    """Detect the container memory limit from cgroup v1/v2.

    Tries in order:
      1. cgroup v2: /sys/fs/cgroup/memory.max
      2. cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes
      3. GW_MEMORY_LIMIT_MB env override
      4. /proc/meminfo total (fallback for non-container)
    """
    env_override = os.environ.get("GW_MEMORY_LIMIT_MB")
    if env_override:
        return int(env_override)

    # cgroup v2
    v2_path = "/sys/fs/cgroup/memory.max"
    try:
        v = Path_dummy = __import__("pathlib").Path(v2_path).read_text().strip()
        if v != "max" and v.isdigit():
            mb = int(v) // (1024 * 1024)
            if mb > 0:
                return mb
    except (FileNotFoundError, ValueError, PermissionError):
        pass

    # cgroup v1
    v1_path = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
    try:
        v = __import__("pathlib").Path(v1_path).read_text().strip()
        mb = int(v) // (1024 * 1024)
        # cgroup v1 often returns a huge value (no limit) -- sanity check
        if 0 < mb < 1024 * 1024:  # < 1 PB
            return mb
    except (FileNotFoundError, ValueError, PermissionError):
        pass

    # Host fallback
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except (FileNotFoundError, ValueError):
        pass

    # Last-resort default: assume 1 GB
    return 1024


def _cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        import multiprocessing
        return multiprocessing.cpu_count()


# ── Budget plan ─────────────────────────────────────────────────────────
class MemoryBudget:
    """Calculated budget for one gw-pipeline process.

    All values are in MB unless suffixed _count (integer).
    """

    def __init__(
        self,
        container_limit_mb: int,
        overhead_mb: int = 150,
        onnx_model_count: int = 3,
        onnx_model_size_mb: int = 150,
        fits_peak_mb: int = 120,
        free_pool_mb: int = 80,
        thumbnail_budget_mb: Optional[int] = None,
    ):
        self.container_limit_mb = container_limit_mb
        self.overhead_mb = overhead_mb
        self.onnx_model_count = onnx_model_count
        self.onnx_model_size_mb = onnx_model_size_mb
        self.fits_peak_mb = fits_peak_mb
        self.free_pool_mb = free_pool_mb
        self.cpu_count = _cpu_count()

        # DL concurrency is bounded by CPU AND memory
        # Each concurrent inference needs ~1 model in memory (paged but pined)
        dl_by_memory = max(1, (container_limit_mb - overhead_mb - fits_peak_mb - free_pool_mb) // onnx_model_size_mb)
        dl_by_cpu = max(1, self.cpu_count // 2)  # ONNX uses 2 threads each
        self.dl_max_concurrent = max(1, min(dl_by_memory, dl_by_cpu, 8))

        # Thumbnail cache: how many thumbs fit in remaining budget
        if thumbnail_budget_mb is None:
            thumbnail_budget_mb = int(os.environ.get("GW_THUMBNAIL_BUDGET_MB", "200"))
        self.thumbnail_budget_mb = thumbnail_budget_mb
        # avg thumbnail = 140px square JPEG ~ 12 KB on disk; in-memory decoded ~ 60 KB
        avg_thumb_bytes = 60 * 1024
        self.thumbnail_cache_size = max(100, (thumbnail_budget_mb * 1024 * 1024) // avg_thumb_bytes)

        # Heavy worker count: capped by CPU but also not over-saturating memory
        self.heavy_workers = min(self.cpu_count, 16, max(1, container_limit_mb // 128))

        # Process pool size for CPU-bound tasks (R6.26 Phase 3)
        self.process_pool_workers = max(1, self.cpu_count - 1)  # leave 1 CPU for IO

    def to_dict(self) -> dict:
        return {
            "container_limit_mb": self.container_limit_mb,
            "cpu_count": self.cpu_count,
            "overhead_mb": self.overhead_mb,
            "onnx_model_count": self.onnx_model_count,
            "onnx_model_size_mb": self.onnx_model_size_mb,
            "fits_peak_mb": self.fits_peak_mb,
            "free_pool_mb": self.free_pool_mb,
            "dl_max_concurrent": self.dl_max_concurrent,
            "thumbnail_budget_mb": self.thumbnail_budget_mb,
            "thumbnail_cache_size": self.thumbnail_cache_size,
            "heavy_workers": self.heavy_workers,
            "process_pool_workers": self.process_pool_workers,
        }


# ── Module-level singleton ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_budget() -> MemoryBudget:
    """Get the process-wide memory budget (computed once at startup)."""
    container_mb = _detect_container_memory_limit_mb()
    onnx_count = int(os.environ.get("GW_ONNX_MODEL_COUNT", "3"))
    onnx_size = int(os.environ.get("GW_DL_MODEL_SIZE_MB", "150"))
    return MemoryBudget(
        container_limit_mb=container_mb,
        onnx_model_count=onnx_count,
        onnx_model_size_mb=onnx_size,
    )


# ── Convenience accessors (drop-in replacements for hardcoded constants) ─
def get_thumbnail_cache_size() -> int:
    """Replacement for hardcoded `THUMBNAIL_CACHE_SIZE = 5000`."""
    return get_budget().thumbnail_cache_size


def get_max_concurrent_inferences() -> int:
    """Replacement for hardcoded `_DL_MAX_CONCURRENT = 3`."""
    return get_budget().dl_max_concurrent


def get_heavy_workers() -> int:
    """Replacement for hardcoded `_HEAVY_WORKERS = min(int(os.getenv(...)), 16)`."""
    return get_budget().heavy_workers


def get_process_pool_workers() -> int:
    """Replacement for hardcoded ProcessPoolExecutor max_workers."""
    return get_budget().process_pool_workers


# ── Diagnostic ──────────────────────────────────────────────────────────
def print_budget_report() -> None:
    """Log the budget report at startup. Call once after logging is configured."""
    b = get_budget()
    logger.info(
        "R6.26 memory budget: container=%dMB cpu=%d "
        "dl_concurrent=%d thumb_cache=%d (budget %dMB) "
        "heavy_workers=%d process_pool=%d",
        b.container_limit_mb,
        b.cpu_count,
        b.dl_max_concurrent,
        b.thumbnail_cache_size,
        b.thumbnail_budget_mb,
        b.heavy_workers,
        b.process_pool_workers,
    )
    # Also expose for /health and /status endpoints
    try:
        import server as _server  # late import to avoid circular
        _server._MEMORY_BUDGET_REPORT = b.to_dict()
    except Exception:
        pass


if __name__ == "__main__":
    # Standalone diagnostic
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print_budget_report()
    print()
    print("Drop-in replacements:")
    print(f"  THUMBNAIL_CACHE_SIZE    = {get_thumbnail_cache_size()}")
    print(f"  DL_MAX_CONCURRENT       = {get_max_concurrent_inferences()}")
    print(f"  HEAVY_WORKERS           = {get_heavy_workers()}")
    print(f"  PROCESS_POOL_WORKERS    = {get_process_pool_workers()}")
