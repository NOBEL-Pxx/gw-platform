"""R6.104-K review regression: the disk cache must count BOTH file types.

hips-float writes {key}.png into the same directory the .jpg thumbnail cache
uses, but the size cap only ever globbed "*.jpg". The evictor therefore saw a
total of 0 bytes forever and the PNG cache grew without bound -- one new file
per distinct parameter set, and R6.104-K multiplies the key cardinality
(gamma / brightness / contrast / saturation / cut_mode / min_cut_abs /
max_cut_abs are all part of the cache key).

The sibling tile cache already globs both extensions; this pins the same
contract for the cutout cache.

Run with:
    cd D:\AliCPT\gw-pipeline
    python -m pytest tests/test_hips_cache_eviction.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

_PIPELINE_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "src")
if _PIPELINE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_SRC))


def test_evict_if_needed_counts_png_files(tmp_path, monkeypatch):
    """1200 bytes of .png against a 1000-byte cap must evict down to <= 800."""
    import pipeline.routes.hips as hips

    monkeypatch.setattr(hips, "HIPS_CACHE_DIR", tmp_path)
    monkeypatch.setattr(hips, "MAX_HIPS_CACHE_BYTES", 1000)

    files = []
    for i in range(3):
        p = tmp_path / ("float%d.png" % i)
        p.write_bytes(b"x" * 400)
        files.append(p)
    # Distinct mtimes so the oldest-first sort is deterministic.
    for i, p in enumerate(files):
        os.utime(str(p), (1_700_000_000 + i, 1_700_000_000 + i))

    hips._evict_if_needed()

    remaining = list(tmp_path.glob("*.png"))
    assert len(remaining) == 2, (
        "expected eviction to 2 files (<= 80%% of 1000 B), got %d -- a .jpg-only "
        "glob leaves the float PNG cache unbounded" % len(remaining)
    )


def test_evict_if_needed_still_counts_jpg_files(tmp_path, monkeypatch):
    """The original .jpg behaviour must not regress."""
    import pipeline.routes.hips as hips

    monkeypatch.setattr(hips, "HIPS_CACHE_DIR", tmp_path)
    monkeypatch.setattr(hips, "MAX_HIPS_CACHE_BYTES", 1000)

    files = []
    for i in range(3):
        p = tmp_path / ("thumb%d.jpg" % i)
        p.write_bytes(b"x" * 400)
        files.append(p)
    for i, p in enumerate(files):
        os.utime(str(p), (1_700_000_000 + i, 1_700_000_000 + i))

    hips._evict_if_needed()

    assert len(list(tmp_path.glob("*.jpg"))) == 2


def test_evict_if_needed_counts_both_extensions_together(tmp_path, monkeypatch):
    """The cap is on the DIRECTORY, not per extension."""
    import pipeline.routes.hips as hips

    monkeypatch.setattr(hips, "HIPS_CACHE_DIR", tmp_path)
    monkeypatch.setattr(hips, "MAX_HIPS_CACHE_BYTES", 1000)

    (tmp_path / "a.jpg").write_bytes(b"x" * 400)
    (tmp_path / "b.png").write_bytes(b"x" * 400)
    (tmp_path / "c.png").write_bytes(b"x" * 400)

    hips._evict_if_needed()

    total = sum(p.stat().st_size for p in tmp_path.iterdir())
    assert total <= 800, "directory total must fall to <= 80%% of the cap"


async def test_hips_stats_counts_png_files(tmp_path, monkeypatch):
    """The diagnostic endpoint must not under-report the cache as empty."""
    import pipeline.routes.hips as hips

    monkeypatch.setattr(hips, "HIPS_CACHE_DIR", tmp_path)
    (tmp_path / "a.png").write_bytes(b"x" * 300)
    (tmp_path / "b.jpg").write_bytes(b"y" * 100)

    out = await hips.hips_stats()

    assert out["files"] == 2
    assert out["bytes"] == 400
