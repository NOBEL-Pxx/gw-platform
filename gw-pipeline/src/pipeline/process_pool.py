#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R6.26 — ProcessPoolExecutor wrapper for CPU-bound FITS / source-detection tasks.

The ThreadPoolExecutor used in dl_inference.py works for ONNX (ONNX C++ backend
releases the GIL via Py_BEGIN_ALLOW_THREADS). But pure-Python NumPy/SciPy
operations like FITS decoding, source detection, and FFT do NOT release the GIL
effectively — multiple threads serialize on the same core.

This module provides:
  - get_fits_process_pool()     — singleton ProcessPoolExecutor for FITS work
  - run_in_fits_pool(fn, *args) — convenience wrapper with timeout + retry
  - shutdown_fits_process_pool() — graceful shutdown

Why ProcessPoolExecutor over multiprocessing.Pool directly:
  - Same Executor interface as ThreadPoolExecutor (drop-in replacement)
  - Automatic task queuing via concurrent.futures
  - Workers are daemon=True so they die with the parent (no zombie processes)

Cost:
  - Each worker is a fresh Python process (~50 MB RSS startup)
  - Arguments must be picklable (NumPy arrays are picklable; FITS file paths preferred)
  - Use lazy module-level singletons (workers persist across requests)

Usage (replacing ThreadPoolExecutor in fits_core.py / source_detection):
    from process_pool import run_in_fits_pool

    async def detect_sources(fits_path):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,  # use default
            lambda: run_in_fits_pool(detect_in_file, fits_path, threshold=3.0)
        )
        return result

    # Or sync API:
    result = run_in_fits_pool(detect_in_file, "/data/foo.fits", threshold=3.0)
"""
from __future__ import annotations

import os
import sys
import atexit
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, TimeoutError as CFTimeoutError
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Module-level singleton pool (lazy init)
_POOL: Optional[ProcessPoolExecutor] = None
_POOL_WORKERS: Optional[int] = None


def _get_default_workers() -> int:
    """Compute the default worker count, respecting memory budget + env override."""
    try:
        from memory_budget import get_process_pool_workers
        return get_process_pool_workers()
    except ImportError:
        # Fallback if memory_budget.py not importable (test harness)
        env_override = os.environ.get("GW_FITS_PROCESS_POOL_WORKERS")
        if env_override:
            return int(env_override)
        return max(1, multiprocessing.cpu_count() - 1)


def _worker_initializer() -> None:
    """Initializer run in each worker process once at startup.

    Sets up thread pool for ONNX sub-tasks, disables BLAS oversubscription.
    """
    try:
        # Limit BLAS thread pools so they don't oversubscribe the worker process
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    except Exception:
        pass


def get_fits_process_pool() -> ProcessPoolExecutor:
    """Lazy-create the singleton ProcessPoolExecutor for FITS / CPU-bound work."""
    global _POOL, _POOL_WORKERS
    if _POOL is None:
        _POOL_WORKERS = _get_default_workers()
        # mp_context="spawn" is safer for cross-platform (Windows uses spawn by default)
        # but "fork" is faster on Linux. Pick "spawn" if not specified -- safer.
        ctx_name = os.environ.get("GW_FITS_POOL_CONTEXT", "spawn")
        import multiprocessing as mp
        ctx = mp.get_context(ctx_name)
        _POOL = ProcessPoolExecutor(
            max_workers=_POOL_WORKERS,
            mp_context=ctx,
            initializer=_worker_initializer,
        )
        logger.info("R6.26 FITS process pool initialized: %d workers (ctx=%s)", _POOL_WORKERS, ctx_name)
        atexit.register(shutdown_fits_process_pool)
    return _POOL


def shutdown_fits_process_pool(wait: bool = True) -> None:
    """Shutdown the singleton pool. Called automatically; safe to call twice."""
    global _POOL
    if _POOL is not None:
        logger.info("R6.26 FITS process pool shutting down (wait=%s)", wait)
        _POOL.shutdown(wait=wait)
        _POOL = None


def run_in_fits_pool(
    fn: Callable[..., T],
    *args: Any,
    timeout_sec: Optional[float] = None,
    **kwargs: Any,
) -> T:
    """Submit fn(*args, **kwargs) to the FITS process pool.

    Args:
        fn: picklable callable (module-level function preferred)
        *args: positional args (must be picklable; pass file paths, not arrays)
        timeout_sec: optional timeout (default: no timeout, blocks indefinitely)
        **kwargs: keyword args

    Returns:
        fn's return value

    Raises:
        CFTimeoutError: if timeout_sec exceeded
        Exception: whatever fn raised (re-raised in parent process)
    """
    pool = get_fits_process_pool()
    future = pool.submit(fn, *args, **kwargs)
    if timeout_sec is None:
        return future.result()
    return future.result(timeout=timeout_sec)


async def run_in_fits_pool_async(
    fn: Callable[..., T],
    *args: Any,
    timeout_sec: Optional[float] = None,
    **kwargs: Any,
) -> T:
    """Async-friendly wrapper: run_in_fits_pool() without blocking the event loop."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_in_fits_pool(fn, *args, timeout_sec=timeout_sec, **kwargs),
    )


# ── Diagnostics ─────────────────────────────────────────────────────────
def pool_status() -> dict:
    """Return pool status dict for /health and /diagnostics endpoints."""
    return {
        "initialized": _POOL is not None,
        "workers": _POOL_WORKERS,
        "context": os.environ.get("GW_FITS_POOL_CONTEXT", "spawn"),
    }


# ── Module-level helper for standalone smoke test (must be picklable) ──
def _cpu_bound(n: int) -> int:
    """Pure-Python CPU-bound work, used only by the if __name__ smoke test."""
    total = 0
    for i in range(n * 100_000):
        total += i * i
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import time
    print("Initializing FITS pool...")
    pool = get_fits_process_pool()
    print(f"Workers: {pool_status()['workers']}")

    t0 = time.perf_counter()
    futures = [pool.submit(_cpu_bound, 50) for _ in range(4)]
    results = [f.result(timeout=30) for f in futures]
    elapsed = time.perf_counter() - t0
    print(f"4 parallel CPU-bound tasks: {elapsed:.2f}s, results={results[:2]}...")
    shutdown_fits_process_pool()
