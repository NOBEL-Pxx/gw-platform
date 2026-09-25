"""R6.104-K: backend stretch + post-coefficient unit tests.

Run with:
    cd D:\AliCPT\gw-pipeline
    python -m pytest tests/test_hips_stretch_ext.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_PIPELINE_SRC = os.path.join(os.path.dirname(__file__), os.pardir, "src")
if _PIPELINE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_SRC))

from pipeline.stretch_ops import (
    apply_pow2,
    apply_equalization,
    apply_gamma,
    apply_brightness,
    apply_contrast,
    apply_saturation,
)


# T1
def test_pow2_stretch():
    arr = np.array([0.0, 0.5, 1.0])
    out = apply_pow2(arr, 0.0, 1.0)
    np.testing.assert_allclose(out, [0.0, 0.25, 1.0])


# T2
def test_equalization_uniformizes():
    # Skewed input: lots of mid values, few extremes.
    rng = np.random.default_rng(42)
    raw = rng.beta(2, 5, size=(64, 64)).astype(np.float32)  # skewed toward 0
    out = apply_equalization(raw, 0.0, 1.0)
    # Output histogram (256 bins) should be approximately uniform.
    hist, _ = np.histogram(out, bins=16, range=(0.0, 1.0))
    expected = out.size / 16
    # Within 50% tolerance (equalization is approximate).
    assert np.all(np.abs(hist - expected) < 0.5 * expected), f"hist={hist}"


# T3
def test_gamma_correction():
    rgb = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    out = apply_gamma(rgb, gamma=2.0)
    # 0.5 ^ (1/2) = sqrt(0.5) ≈ 0.7071
    np.testing.assert_allclose(out, [0.70710677, 0.70710677, 0.70710677], atol=1e-6)


# T4
@pytest.mark.skip(
    reason="requires Python >= 3.10 to import pipeline.server "
    "(agent_loop.py uses PEP 604 union syntax)"
)
def test_cut_mode_absolute_via_hips_endpoint():
    # Round-trip through the FastAPI app.
    from fastapi.testclient import TestClient
    from pipeline.server import app  # the actual app
    # Skip if no real FITS file available; this is a smoke check.
    client = TestClient(app)
    # Just verify the endpoint exists and rejects invalid params.
    r = client.get("/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&stretch=pow2&gamma=2.0&cut_mode=absolute&min_cut_abs=100&max_cut_abs=1000")
    # 200 = at least the param validation passed; the FITS bytes may 404
    # if DSS2 not reachable in the test env. Either way, we should NOT see 422.
    assert r.status_code != 422, r.text


# T5
def test_pipeline_order():
    # Verify AladinLite v3 §10 post-coefficient order:
    #     gamma -> brightness -> contrast -> saturation.
    # A small RGB image with distinct per-pixel channels is used so every
    # stage (including saturation) is a non-trivial transformation.
    rgb = np.array(
        [
            [[0.20, 0.30, 0.50], [0.40, 0.60, 0.80]],
            [[0.10, 0.70, 0.20], [0.50, 0.30, 0.90]],
        ],
        dtype=np.float32,
    )
    out = apply_gamma(rgb, 1.5)
    out = apply_brightness(out, 0.1)
    out = apply_contrast(out, 1.2)
    out = apply_saturation(out, 1.1)

    # 1. The pipeline must change the image (every coefficient is non-identity).
    #    Fails if any apply_* function returns its input unchanged.
    assert not np.allclose(out, rgb), (
        "pipeline is a no-op; a stage returned input unchanged"
    )

    # 2. Values must remain in [0, 1] (clip behaviour preserved at every stage).
    #    Fails if any apply_* function returns NaN or out-of-range values.
    assert not np.isnan(out).any(), "pipeline produced NaN"
    assert out.min() >= 0.0 and out.max() <= 1.0, (
        f"pipeline violates [0,1] clip invariant; got [{out.min()}, {out.max()}]"
    )

    # 3. Hand-computed reference for pixel [0, 0] = (0.20, 0.30, 0.50):
    #      gamma(1.5)      -> (0.3420, 0.4481, 0.6300)
    #      brightness(0.1) -> (0.4420, 0.5481, 0.7300)
    #      contrast(1.2)   -> (0.4304, 0.5578, 0.7760)
    #      saturation(1.1) -> (0.4188, 0.5589, 0.7989)
    #    Fails if any of the four apply_* functions is removed, swapped, or
    #    produces a different transformation.
    expected_pixel_00 = np.array(
        [0.41878945, 0.55890125, 0.79890380], dtype=np.float32
    )
    np.testing.assert_allclose(out[0, 0], expected_pixel_00, atol=1e-5)


# T6
@pytest.mark.skip(
    reason="requires Python >= 3.10 to import pipeline.server "
    "(agent_loop.py uses PEP 604 union syntax)"
)
def test_invalid_stretch_400():
    from fastapi.testclient import TestClient
    from pipeline.server import app
    client = TestClient(app)
    r = client.get("/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&stretch=foobar")
    assert r.status_code == 400, r.text


# T7
@pytest.mark.skip(
    reason="requires Python >= 3.10 to import pipeline.server "
    "(agent_loop.py uses PEP 604 union syntax)"
)
def test_invalid_gamma_400():
    from fastapi.testclient import TestClient
    from pipeline.server import app
    client = TestClient(app)
    r = client.get("/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&gamma=10.0")
    assert r.status_code == 400, r.text


# T8
def test_equalization_idempotent():
    # Equalizing already-equalized data should leave the distribution unchanged.
    rng = np.random.default_rng(7)
    raw = rng.uniform(0, 1, size=(128, 128)).astype(np.float32)
    once = apply_equalization(raw, 0.0, 1.0)
    twice = apply_equalization(once, 0.0, 1.0)
    # Should be very close (idempotent up to histogram quantization).
    np.testing.assert_allclose(once, twice, atol=0.02)
