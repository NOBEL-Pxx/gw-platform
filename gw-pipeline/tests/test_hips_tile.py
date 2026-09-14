"""R6.99-H: HiPS tile backend proxy cache - 8 unit tests.

Tests the new /pipeline/hips-tile/{z}/{x}/{y} endpoint that proxies HiPS tile
fetches from CDS Strasbourg through a backend disk cache.

Run with:
    cd D:\\AliCPT\\gw-pipeline
    python -m pytest tests/test_hips_tile.py -v
"""
from __future__ import annotations

import hashlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

# Add src to path so we can import pipeline.routes.hips
_PIPELINE_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "src")
if _PIPELINE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_SRC))


@pytest.fixture
def hips_app(tmp_path, monkeypatch):
    """Create a fresh FastAPI app with hips router, isolated cache dir per test."""
    monkeypatch.setenv("HIPS_TILE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("HIPS_TILE_CACHE_MAX_TILES", "200000")
    monkeypatch.setenv("HIPS_TILE_CACHE_MAX_BYTES", str(50 * 1024 * 1024 * 1024))
    import importlib
    if "pipeline.routes.hips" in sys.modules:
        mod = importlib.reload(sys.modules["pipeline.routes.hips"])
    else:
        from pipeline.routes import hips as mod
    # R6.99-H PERF HIGH-5: reset module-level httpx client cache so monkeypatch on httpx.AsyncClient
    # actually takes effect (otherwise the cached client is reused across tests)
    mod._hips_tile_client = None
    mod._hips_tile_client_lock = None
    mod._hips_tile_upstream_sem = None
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(mod.router, prefix="/pipeline")
    return app, mod, tmp_path


@pytest.fixture
def client(hips_app):
    app, _mod, _tmp = hips_app
    return TestClient(app)


def _seed_tile(tmp_path, survey, z, x, y, content):
    """Pre-populate cache with a tile."""
    key = hashlib.sha256(f"{survey}:{z}:{x}:{y}".encode()).hexdigest()[:16]
    (tmp_path / f"{key}.jpg").write_bytes(content)
    return key


def test_cache_hit(hips_app):
    """Case 1: cached tile returns HIT on second request."""
    app, _mod, tmp_path = hips_app
    client = TestClient(app)
    survey, z, x, y = "DSS2/Blue", 3, 0, 0
    content = b"\xff\xd8\xff" + b"A" * 100
    _seed_tile(tmp_path, survey, z, x, y, content)
    r = client.get(f"/pipeline/hips-tile/{z}/{x}/{y}?survey={survey}")
    assert r.status_code == 200
    assert r.headers.get("X-Hips-Cache") == "HIT"
    assert r.content == content


def test_cache_miss(hips_app, monkeypatch):
    """Case 2: uncached tile fetches from CDS, caches, returns MISS."""
    app, mod, tmp_path = hips_app
    client = TestClient(app)
    survey, z, x, y = "DSS2/Blue", 3, 1, 1

    body_bytes = b"\xff\xd8\xff" + b"B" * 100

    class MockStreamResponse:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        async def aiter_bytes(self, chunk_size=65536):
            yield body_bytes

    class MockStreamContext:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return MockStreamResponse()
        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        def stream(self, method, url, **kwargs):
            return MockStreamContext(method, url)
        async def get(self, url, **kwargs):
            raise RuntimeError("patched code uses .stream(), not .get()")

    monkeypatch.setattr(mod.httpx, "AsyncClient", MockAsyncClient)

    r = client.get(f"/pipeline/hips-tile/{z}/{x}/{y}?survey={survey}")
    assert r.status_code == 200
    assert r.headers.get("X-Hips-Cache") == "MISS"
    key = hashlib.sha256(f"{survey}:{z}:{x}:{y}".encode()).hexdigest()[:16]
    assert (tmp_path / f"{key}.jpg").exists()


def test_path_traversal_blocked(hips_app):
    """Case 3: survey=../../etc/passwd must be rejected with 422 (FastAPI standard for query validation)."""
    app, _mod, _tmp = hips_app
    client = TestClient(app)
    r = client.get("/pipeline/hips-tile/3/0/0?survey=../../etc/passwd")
    assert r.status_code == 422  # FastAPI query validation rejection


def test_invalid_z_range(hips_app):
    """Case 4: z=99 must be rejected with 422 (FastAPI standard for path validation)."""
    app, _mod, _tmp = hips_app
    client = TestClient(app)
    r = client.get("/pipeline/hips-tile/99/0/0?survey=DSS2/Blue")
    assert r.status_code == 422  # FastAPI path validation rejection


def test_cds_down_returns_502(hips_app, monkeypatch):
    """Case 5: CDS unreachable must return 502."""
    app, mod, _tmp = hips_app
    client = TestClient(app)

    class MockStreamContext:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            raise mod.httpx.ConnectError("CDS unreachable")
        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        def stream(self, method, url, **kwargs):
            return MockStreamContext(method, url)
        async def get(self, url, **kwargs):
            raise RuntimeError("patched code uses .stream(), not .get()")

    monkeypatch.setattr(mod.httpx, "AsyncClient", MockAsyncClient)

    r = client.get("/pipeline/hips-tile/3/2/2?survey=DSS2/Blue")
    assert r.status_code == 502


def test_lru_eviction(hips_app, monkeypatch):
    """Case 6: when tile count > max_tiles, oldest is evicted."""
    app, mod, tmp_path = hips_app
    client = TestClient(app)
    mod.HIPS_TILE_MAX_TILES = 3

    for i in range(3):
        _seed_tile(tmp_path, "DSS2/Blue", 3, i, 0, b"X" * 50)
        time.sleep(0.05)

    body_bytes = b"\xff\xd8\xff" + b"C" * 100

    class MockStreamResponse:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        async def aiter_bytes(self, chunk_size=65536):
            yield body_bytes

    class MockStreamContext:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return MockStreamResponse()
        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        def stream(self, method, url, **kwargs):
            return MockStreamContext(method, url)
        async def get(self, url, **kwargs):
            raise RuntimeError("patched code uses .stream(), not .get()")

    monkeypatch.setattr(mod.httpx, "AsyncClient", MockAsyncClient)

    r = client.get("/pipeline/hips-tile/3/3/0?survey=DSS2/Blue")
    assert r.status_code == 200
    files = list(tmp_path.glob("*.jpg"))
    assert len(files) <= 3


def test_etag_returns_304(hips_app):
    """Case 7: matching If-None-Match returns 304 Not Modified."""
    app, _mod, tmp_path = hips_app
    client = TestClient(app)
    survey, z, x, y = "DSS2/Blue", 3, 4, 4
    content = b"\xff\xd8\xff" + b"D" * 100
    _seed_tile(tmp_path, survey, z, x, y, content)
    etag = hashlib.sha256(content).hexdigest()[:16]

    r = client.get(
        f"/pipeline/hips-tile/{z}/{x}/{y}?survey={survey}",
        headers={"If-None-Match": etag},
    )
    assert r.status_code == 304


def test_endpoint_allowlist(hips_app):
    """Case 8: endpoint=evil.com must be rejected with 400."""
    app, _mod, _tmp = hips_app
    client = TestClient(app)
    r = client.get(
        "/pipeline/hips-tile/3/0/0?survey=DSS2/Blue&endpoint=evil.com"
    )
    assert r.status_code == 400
