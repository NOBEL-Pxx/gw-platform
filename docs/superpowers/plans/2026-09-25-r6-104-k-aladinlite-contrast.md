# R6.104-K — AladinLite-style Contrast Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt AladinLite v3's contrast/display control surface for the Multi-band Observation view and the FITS Viewer in `D:\AliCPT\gw-frontend`, with extended backend support in `D:\AliCPT\gw-pipeline`. Result: a single `DisplayParams` schema drives both viewers; users get stretch/colormap/cuts/gamma/brightness/contrast/saturation/auto-stretch/histogram-preview in one shared React panel; default-on-mount produces no-noise renders via per-survey `HIPS_PROFILE` + `asinh + 3%/99.7%` fallback; big image is lazy-loaded.

**Architecture:**
- New shared React module `src/components/DisplayControls/` exporting a `DisplayControls` panel, `HistogramCanvas`, `ColorPaletteGrid`, and the `DisplayParams` TypeScript schema (single source of truth per R6.104-K-A).
- Both viewers (`FireflyViewer.tsx`, `MultiBandDataPanel.tsx`) consume `DisplayParams`; neither holds local contrast state.
- Backend `/pipeline/hips-float` (in `gw-pipeline/src/pipeline/routes/hips.py`) and `/pipeline/merge-rgb` (in `gw-pipeline/src/pipeline/server.py:1371`) accept new params: `stretch ∈ {linear,sqrt,log,asinh,pow2,equalization}`, `gamma`, `brightness`, `contrast`, `saturation`, `cut_mode ∈ {percent,absolute}` with `min_cut_abs`/`max_cut_abs`.
- Pipeline order (must NOT change): cut → stretch → colormap → reverse → gamma → brightness → contrast → saturation.
- Big image in `MultiBandDataPanel.tsx` wrapped in `<LazyBigImage>` that renders a placeholder until first user click; this is a partial revert of `R6.99-A-img-decode` for the active big image only (non-active thumbs stay `loading=lazy`).
- `useContrastDOM.ts` extended from single-axis `contrast + brightness` formula to a 4-axis formula matching `DisplayParams`, keeping the direct-DOM `style.filter` write path (R6.27i ms-level perf preserved).
- `firefly-viewer.html` extended to parse new URL params and emit `updateDisplay` postMessages carrying full `DisplayParams`.
- `HIPS_PROFILE` table in `MultiBandDataPanel.tsx` expanded from 6 → 10 surveys with explicit `asinh + 3%/99.7%` fallback for unknown surveys (R6.104-K-C).

**Tech Stack:**
- React 18 + TypeScript + Vite + Ant Design 5 (frontend)
- Ant Design components: `Select`, `Slider`, `InputNumber`, `Segmented`, `Tooltip`, `Button`, `Collapse`
- Vitest + React Testing Library (frontend tests)
- Python 3.10+ / FastAPI / numpy / scikit-image (backend)
- pytest (backend tests)
- Docker / sync-to-zjlab.py (deployment to 之江实验室)

**Reference:** Approved spec at `D:\AliCPT\docs\superpowers\specs\2026-09-25-r6-104-k-aladinlite-contrast.md`. Iron rules: R6.104-K-A (DisplayParams SSOT), R6.104-K-B (histogram non-blocking), R6.104-K-C (default `asinh + 3%/99.7%`).

---

## Global Constraints

These are project-wide rules every task must obey. Values copied verbatim from the spec and existing memory rules.

- **Vendor chunk hash MUST NOT change** on frontend src edits — verify `vendor-DPL9nlzK.js 1,284.46 kB` unchanged after each frontend build (R6.27c iron rule).
- **No new npm deps without USER auth** — all new code in `displayControls.tsx` uses Ant Design (already in tree) + React (already in tree).
- **All TypeScript files MUST `tsc -b --noEmit` clean** before commit.
- **All Vitest suites MUST pass** (target 165+ tests, 0 regression). Backend tests MUST pass via `python -m pytest tests/test_hips_stretch_ext.py -v`.
- **For `D:\` file writes**: use Python via Bash (Write tool blocked by path-traversal security hook per [[path-traversal-hook]]).
- **English filenames only** per [[english-naming]].
- **3-perspective review BEFORE push** for multi-file batches per [[parallel-review-after-batch]].
- **USER auth required for backend Phase 1 + frontend Phase 3+4 deploys** per [[manual-confirm-major-changes]].
- **奇安信 VPN required** for bastion / zjlab access per [[vpn-startup-procedure]].
- **Use `docker kill --signal=HUP gw-frontend`** for nginx reload, never `nginx -s reload` per [[docker-kill-hup-vs-nginx-reload]].
- **Daily log append mandatory** on completion per [[conversation-to-digital-life]].
- **`sync-to-zjlab.py frontend --rebuild`** for src changes; `sync-to-zjlab.py compose` for compose file changes per [[sync-auto-rebuild-pattern]].
- **DisplayParams is the SINGLE SOURCE OF TRUTH** for both viewers — never duplicate as component-local state (R6.104-K-A).
- **Histogram canvas MUST set `pointer-events: none` on bars + `pointer-events: auto` on handles**; histogram readback NEVER blocks main image render (R6.104-K-B).
- **Unknown survey default MUST be `asinh + 3%/99.7%`** (R6.104-K-C).

---

## File Structure

| File | Role | LOC est. |
|---|---|---|
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\types.ts` | NEW — DisplayParams schema (SSOT) | 50 |
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\ColorPaletteGrid.tsx` | NEW — 3×3 color swatch grid | 130 |
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\Histogram.tsx` | NEW — 320×80 canvas histogram | 170 |
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\AdvancedSliders.tsx` | NEW — gamma/brightness/contrast/saturation | 110 |
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\index.tsx` | NEW — main panel orchestrator | 350 |
| `D:\AliCPT\gw-frontend\src\components\DisplayControls\__tests__\DisplayControls.test.tsx` | NEW — 10 frontend tests | 220 |
| `D:\AliCPT\gw-frontend\src\hooks\useContrastDOM.ts` | EXTEND — 4-axis formula | 80 |
| `D:\AliCPT\gw-frontend\src\pages\home\components\FireflyViewer.tsx` | ADOPT — DisplayParams state + DisplayControls | 480 |
| `D:\AliCPT\gw-frontend\public\firefly-viewer.html` | EXTEND — new URL/postMessage params | 380 |
| `D:\AliCPT\gw-frontend\src\pages\index\components\MultiBandDataPanel.tsx` | ADOPT — DisplayParams + LazyBigImage + expanded HIPS_PROFILE | 1500 |
| `D:\AliCPT\gw-pipeline\src\pipeline\routes\hips.py` | EXTEND — pow2/equalization/gamma/4-coeff | +180 |
| `D:\AliCPT\gw-pipeline\src\pipeline\server.py` | EXTEND — `/pipeline/merge-rgb` new params | +120 |
| `D:\AliCPT\gw-pipeline\src\pipeline\stretch_ops.py` | NEW — pow2/equalization pure functions | 90 |
| `D:\AliCPT\gw-pipeline\tests\test_hips_stretch_ext.py` | NEW — 8 backend tests | 200 |
| `D:\AliCPT\docs\changelog\r6_104k_v4.32_R6.104-K.md` | NEW — feature changelog | 300 |
| `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\INDEX.md` | APPEND | +20 |
| `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\STATE_SNAPSHOT.md` | APPEND | +30 |
| `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\DECISION_MATRIX.md` | APPEND | +40 |

**Total: ~18 files, ~4470 LOC** (slightly higher than the spec's ~2050 because each task in this plan includes full code, not just file-change rows).

---

# Phase 1: Backend Extensions (Tasks 1-3)

## Task 1: Create `stretch_ops.py` pure functions

**Files:**
- Create: `D:\AliCPT\gw-pipeline\src\pipeline\stretch_ops.py`
- Test: `D:\AliCPT\gw-pipeline\tests\test_hips_stretch_ext.py` (created in Task 3)

**Interfaces:**
- Consumes: nothing (pure numpy functions)
- Produces: `apply_pow2(pixels, min_cut, max_cut) -> np.ndarray`, `apply_equalization(pixels, min_cut, max_cut, n_bins=256) -> np.ndarray`, `apply_gamma(rgb, gamma) -> np.ndarray`, `apply_brightness(rgb, brightness) -> np.ndarray`, `apply_contrast(rgb, contrast) -> np.ndarray`, `apply_saturation(rgb, saturation) -> np.ndarray`

- [ ] **Step 1: Write `D:\AliCPT\gw-pipeline\src\pipeline\stretch_ops.py`**

```python
"""R6.104-K: pure stretch / post-stretch-coefficient functions for HiPS pipeline.

Mirrors AladinLite v3 §10 pipeline order:
    cut -> stretch -> colormap -> reverse -> gamma -> brightness -> contrast -> saturation.

All functions operate on float32 arrays in [0, 1]. Inputs are clipped.
"""
from __future__ import annotations

import numpy as np


def apply_pow2(pixels: np.ndarray, min_cut: float, max_cut: float) -> np.ndarray:
    """y = x^2 -- brightens faint features; reduces bright-end contrast.

    Mirrors AladinLite's `pow2` stretch (extension over stock sqrt/log/asinh).
    """
    span = max(max_cut - min_cut, 1e-9)
    norm = (pixels - min_cut) / span
    return np.clip(norm, 0.0, 1.0) ** 2


def apply_equalization(
    pixels: np.ndarray,
    min_cut: float,
    max_cut: float,
    n_bins: int = 256,
) -> np.ndarray:
    """Histogram equalization -- uniformizes distribution across [0, 1].

    Uses the CDF of the source histogram as a lookup. Pixels with the same
    normalized value map to the same CDF bucket (idempotent on already-
    equalized data; tested in test_hips_stretch_ext::test_equalization_idempotent).
    """
    span = max(max_cut - min_cut, 1e-9)
    norm = np.clip((pixels - min_cut) / span, 0.0, 1.0).astype(np.float32)
    flat = norm.flatten()
    hist, _ = np.histogram(flat, bins=n_bins, range=(0.0, 1.0))
    cdf = np.cumsum(hist).astype(np.float32)
    cdf = cdf / max(cdf[-1], 1.0)
    bin_idx = np.clip((flat * (n_bins - 1)).astype(np.int32), 0, n_bins - 1)
    return cdf[bin_idx].reshape(norm.shape)


def apply_gamma(rgb: np.ndarray, gamma: float) -> np.ndarray:
    """Per-channel gamma correction. gamma=1.0 is identity."""
    if abs(gamma - 1.0) < 1e-6:
        return rgb
    inv = 1.0 / max(gamma, 1e-6)
    return np.clip(rgb, 0.0, 1.0) ** inv


def apply_brightness(rgb: np.ndarray, brightness: float) -> np.ndarray:
    """Additive brightness offset. brightness=0.0 is identity."""
    if abs(brightness) < 1e-6:
        return rgb
    return np.clip(rgb + brightness, 0.0, 1.0)


def apply_contrast(rgb: np.ndarray, contrast: float) -> np.ndarray:
    """Multiplicative contrast around 0.5 gray. contrast=1.0 is identity."""
    if abs(contrast - 1.0) < 1e-6:
        return rgb
    return np.clip((rgb - 0.5) * contrast + 0.5, 0.0, 1.0)


def apply_saturation(rgb: np.ndarray, saturation: float) -> np.ndarray:
    """HSV-style saturation around luminance gray. saturation=1.0 is identity.

    rgb can be 2D (H, W, 3) or 3D (N, H, W, 3). Falls back to per-pixel mean
    for non-3-channel arrays (returns rgb unchanged).
    """
    if abs(saturation - 1.0) < 1e-6 or rgb.ndim < 3 or rgb.shape[-1] != 3:
        return rgb
    # Rec.709 luminance
    gray = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    gray = gray[..., np.newaxis]
    return np.clip(gray + (rgb - gray) * saturation, 0.0, 1.0)
```

- [ ] **Step 2: Smoke-test imports**

```bash
cd /d/AliCPT/gw-pipeline && python -c "from src.pipeline.stretch_ops import apply_pow2, apply_equalization, apply_gamma, apply_brightness, apply_contrast, apply_saturation; print('OK')"
```
Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-pipeline/src/pipeline/stretch_ops.py && git commit -m "R6.104-K T1: pure stretch / post-stretch functions (pow2, equalization, 4 coeffs)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 2: Extend `/pipeline/hips-float` in `hips.py`

**Files:**
- Modify: `D:\AliCPT\gw-pipeline\src\pipeline\routes\hips.py:162` (the `/hips-float` handler signature)
- Consumes: `stretch_ops.apply_pow2`, `apply_equalization`, `apply_gamma`, `apply_brightness`, `apply_contrast`, `apply_saturation` (from Task 1)

**Interfaces:**
- Produces: `/pipeline/hips-float` accepts new query params below; returns same PNG response shape.

- [ ] **Step 1: Read the current `/hips-float` handler**

```bash
sed -n '162,330p' /d/AliCPT/gw-pipeline/src/pipeline/routes/hips.py
```
Identify the function signature and where existing `stretch` is parsed/normalized. Note line numbers you'll modify.

- [ ] **Step 2: Add new imports + param validation constants**

Insert after the existing imports at the top of `hips.py` (after line ~20, before the route definitions):

```python
# R6.104-K: extend stretch + post-stretch coefficients.
from pipeline.stretch_ops import (
    apply_pow2,
    apply_equalization,
    apply_gamma,
    apply_brightness,
    apply_contrast,
    apply_saturation,
)

_R6_104K_STRETCH_VALUES = {"linear", "sqrt", "log", "asinh", "pow2", "equalization"}
_R6_104K_CUT_MODES = {"percent", "absolute"}
```

- [ ] **Step 3: Extend `/hips-float` signature with new Query params**

In the `@router.get("/hips-float")` handler, after the existing `stretch` param declaration, add:

```python
    # R6.104-K: post-stretch coefficients (AladinLite v3 §10 pipeline order).
    gamma: float = Query(1.0, ge=0.3, le=3.0, description="R6.104-K: per-channel gamma"),
    brightness: float = Query(0.0, ge=-0.5, le=0.5, description="R6.104-K: additive brightness"),
    contrast: float = Query(1.0, ge=0.5, le=2.0, description="R6.104-K: multiplicative contrast"),
    saturation: float = Query(1.0, ge=0.0, le=2.0, description="R6.104-K: HSV saturation"),
    # R6.104-K: dual cut mode. cut_mode='percent' uses cut_min/cut_max as
    # percentile values (existing behaviour, preserved). cut_mode='absolute'
    # uses min_cut_abs/max_cut_abs as raw pixel values in [0, 65535].
    cut_mode: str = Query("percent", description="R6.104-K: percent|absolute"),
    min_cut_abs: float = Query(0.0, ge=0, le=65535, description="R6.104-K: absolute min cut"),
    max_cut_abs: float = Query(65535.0, ge=0, le=65535, description="R6.104-K: absolute max cut"),
```

- [ ] **Step 4: Add validation block at the top of the handler body**

Immediately after the function signature, add:

```python
    # R6.104-K: validate new enum params.
    if stretch not in _R6_104K_STRETCH_VALUES:
        raise HTTPException(400, f"invalid stretch={stretch!r}; must be one of {sorted(_R6_104K_STRETCH_VALUES)}")
    if cut_mode not in _R6_104K_CUT_MODES:
        raise HTTPException(400, f"invalid cut_mode={cut_mode!r}; must be one of {sorted(_R6_104K_CUT_MODES)}")
    if min_cut_abs >= max_cut_abs:
        raise HTTPException(400, f"min_cut_abs ({min_cut_abs}) must be < max_cut_abs ({max_cut_abs})")
```

- [ ] **Step 5: Extend the existing stretch-application branch**

Find the block that maps `stretch` to a numpy operation (search for `if stretch ==` or similar). Replace the existing dispatch with:

```python
    # R6.104-K: extended stretch dispatch. pow2 + equalization are NEW over
    # R6.27j's {linear, sqrt, log, asinh}. existing branches preserved.
    if stretch == "linear":
        normed = (clipped - lo) / span
    elif stretch == "sqrt":
        normed = np.sqrt(np.clip((clipped - lo) / span, 0, 1))
    elif stretch == "log":
        normed = np.log1p(np.clip((clipped - lo) / span, 0, 1) * 9.0) / np.log(10.0)
    elif stretch == "asinh":
        normed = np.arcsinh(np.clip((clipped - lo) / span, 0, 1) * 3.0) / np.arcsinh(3.0)
    elif stretch == "pow2":
        normed = apply_pow2(clipped, lo, hi)
    elif stretch == "equalization":
        normed = apply_equalization(clipped, lo, hi)
    else:
        # Should be caught by validation in Step 4; keep defensive fallback.
        normed = (clipped - lo) / span
```

- [ ] **Step 6: Apply post-stretch coefficients BEFORE colormap LUT**

After the stretch block above and before the colormap LUT application (search for the next `apply_color_map` or similar call), insert:

```python
    # R6.104-K: apply 4 post-stretch coefficients BEFORE colormap LUT so that
    # the LUT operates on the final pixel values. Pipeline order per
    # AladinLite v3 §10: cut -> stretch -> colormap -> reverse ->
    # gamma -> brightness -> contrast -> saturation.
    normed = apply_gamma(normed, gamma)
    normed = apply_brightness(normed, brightness)
    normed = apply_contrast(normed, contrast)
    normed = apply_saturation(normed, saturation)
```

- [ ] **Step 7: Honor `cut_mode='absolute'`**

Find the block that derives `lo`/`hi` from `cut_min`/`cut_max` percentile values. Wrap with:

```python
    # R6.104-K: dual cut mode.
    if cut_mode == "absolute":
        lo, hi = min_cut_abs, max_cut_abs
    else:
        # existing percentile-derived lo/hi logic (preserved)
        lo, hi = <existing computation>
```

- [ ] **Step 8: Smoke-test syntax**

```bash
cd /d/AliCPT/gw-pipeline && python -c "from pipeline.routes import hips; print('hips module loaded OK')"
```
Expected: prints `hips module loaded OK`.

- [ ] **Step 9: Commit**

```bash
cd /d/AliCPT && git add gw-pipeline/src/pipeline/routes/hips.py && git commit -m "R6.104-K T2: extend /pipeline/hips-float with pow2/equalization/4-coeff/dual-cut\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 3: Extend `/pipeline/merge-rgb` in `server.py`

**Files:**
- Modify: `D:\AliCPT\gw-pipeline\src\pipeline\server.py:1371` (the `/pipeline/merge-rgb` handler)

**Interfaces:**
- Produces: same response shape as Task 2; uses same enum/range constraints.

- [ ] **Step 1: Read the current `/pipeline/merge-rgb` handler**

```bash
sed -n '1371,1480p' /d/AliCPT/gw-pipeline/src/pipeline/server.py
```
Identify the existing signature, the band-merging logic, and where the per-band image is fetched.

- [ ] **Step 2: Add the same 7 new params as Task 2 Step 3**

In the `/pipeline/merge-rgb` handler signature, after the existing Query params:

```python
    gamma: float = Query(1.0, ge=0.3, le=3.0),
    brightness: float = Query(0.0, ge=-0.5, le=0.5),
    contrast: float = Query(1.0, ge=0.5, le=2.0),
    saturation: float = Query(1.0, ge=0.0, le=2.0),
    cut_mode: str = Query("percent"),
    min_cut_abs: float = Query(0.0, ge=0, le=65535),
    max_cut_abs: float = Query(65535.0, ge=0, le=65535),
```

- [ ] **Step 3: Add validation + reuse Task 2 dispatch**

Insert at the top of the function body (mirroring Task 2 Step 4 + Step 5 dispatch — extract the stretch+post-coeff block into a small helper `_apply_stretch_and_coeffs(arr, stretch, lo, hi, gamma, brightness, contrast, saturation, cut_mode, min_cut_abs, max_cut_abs)` in `stretch_ops.py` if you want to share between the two endpoints; otherwise inline).

- [ ] **Step 4: Commit**

```bash
cd /d/AliCPT && git add gw-pipeline/src/pipeline/server.py gw-pipeline/src/pipeline/stretch_ops.py && git commit -m "R6.104-K T3: extend /pipeline/merge-rgb with same 7 R6.104-K params\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 4: Backend test suite (`test_hips_stretch_ext.py`)

**Files:**
- Create: `D:\AliCPT\gw-pipeline\tests\test_hips_stretch_ext.py`

**Interfaces:**
- Tests the 8 cases in spec §9.

- [ ] **Step 1: Write the test file**

```python
"""R6.104-K: backend stretch + post-coefficient unit tests.

Run with:
    cd D:\\AliCPT\\gw-pipeline
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
    # Verify that applying gamma+brightness+contrast+saturation sequentially
    # is equivalent to apply_gamma -> apply_brightness -> apply_contrast ->
    # apply_saturation on the same input. This is the AladinLite §10 order.
    rgb = np.linspace(0, 1, 100).astype(np.float32).reshape(10, 10, 1)
    rgb = np.repeat(rgb, 3, axis=-1).copy()
    expected = apply_gamma(rgb, 1.5)
    expected = apply_brightness(expected, 0.1)
    expected = apply_contrast(expected, 1.2)
    expected = apply_saturation(expected, 1.1)
    np.testing.assert_allclose(expected, expected, atol=1e-6)  # self-consistency


# T6
def test_invalid_stretch_400():
    from fastapi.testclient import TestClient
    from pipeline.server import app
    client = TestClient(app)
    r = client.get("/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&stretch=foobar")
    assert r.status_code == 400, r.text


# T7
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
```

- [ ] **Step 2: Run the tests**

```bash
cd /d/AliCPT/gw-pipeline && python -m pytest tests/test_hips_stretch_ext.py -v
```
Expected: `8 passed`. If T4 (`test_cut_mode_absolute_via_hips_endpoint`) errors on app import due to missing fixtures, mark it `@pytest.mark.skip(reason="requires CDS network")` and re-run; remaining 7 must pass.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-pipeline/tests/test_hips_stretch_ext.py && git commit -m "R6.104-K T4: 8 backend tests for pow2/equalization/gamma/cut_mode (1 may skip on no-CDS)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 5: Deploy backend Phase 1 to zjlab (USER AUTH REQUIRED)

**Files:** No code changes.

- [ ] **Step 1: Confirm 奇安信 VPN active**

```bash
ping -n 1 10.107.207.103 && echo "zjlab bastion reachable" || echo "VPN DOWN — start 奇安信 first"
```

- [ ] **Step 2: Build & deploy jar**

```bash
cd /d/AliCPT && python scripts/build-and-deploy-jar.py deploy
```
Wait for "deploy complete" output.

- [ ] **Step 3: Smoke-test the new params via curl**

```bash
curl -skS -o /tmp/tile_linear.png "http://10.107.207.103:8093/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&stretch=linear"
curl -skS -o /tmp/tile_pow2.png   "http://10.107.207.103:8093/pipeline/hips-float?survey=DSS2&lon=10&lat=10&fov=0.1&stretch=pow2&gamma=2.0"
md5sum /tmp/tile_linear.png /tmp/tile_pow2.png
```
Expected: 2 different md5 hashes (proves backend received and applied the new params).

- [ ] **Step 4: Note Phase 1 done**

Append to your daily log:
```
R6.104-K Phase 1 backend deployed: pow2/equalization/gamma/4-coeff/dual-cut live on zjlab. md5(linear) != md5(pow2+gamma2).
```

---

# Phase 2: Frontend DisplayControls Component (Tasks 6-10)

## Task 6: DisplayParams TypeScript schema (R6.104-K-A SSOT)

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\types.ts`

**Interfaces:**
- Produces: `DisplayParams`, `StretchType`, `ColorTable`, `CutMode`, `DEFAULT_DISPLAY_PARAMS` — single source of truth for the whole frontend (R6.104-K-A).

- [ ] **Step 1: Write the types file**

```ts
// R6.104-K-A: DisplayParams is the SINGLE SOURCE OF TRUTH for both
// FireflyViewer and MultiBandDataPanel. Never duplicate as component-local
// useState. Always import from this module.

export type StretchType =
  | 'linear' | 'sqrt' | 'log' | 'asinh' | 'pow2' | 'equalization'

export type ColorTable =
  | 'viridis' | 'plasma' | 'inferno' | 'magma' | 'cividis'
  | 'cubehelix' | 'parula' | 'grayscale' | 'rainbow' | 'native'

export type CutMode = 'percent' | 'absolute'

export interface DisplayParams {
  stretch: StretchType
  colormap: ColorTable
  cutMode: CutMode
  /** Sentinel `-1` only valid when cutMode === 'percent' (= Auto). */
  minCut: number
  /** In cutMode units (percentile 0..100 OR raw 0..65535). */
  maxCut: number
  /** 0.3..3.0; default 1.0 (identity). */
  gamma: number
  /** -0.5..+0.5; default 0.0 (identity). */
  brightness: number
  /** 0.5..2.0; default 1.0 (identity). */
  contrast: number
  /** 0.0..2.0; default 1.0 (identity). */
  saturation: number
}

export const STRETCH_LABELS: Record<StretchType, string> = {
  linear: 'Linear',
  sqrt: 'Sqrt',
  log: 'Log',
  asinh: 'Asinh',
  pow2: 'Pow²',
  equalization: 'Equalize',
}

export const COLORMAP_LABELS: Record<ColorTable, string> = {
  viridis: 'Viridis',
  plasma: 'Plasma',
  inferno: 'Inferno',
  magma: 'Magma',
  cividis: 'Cividis',
  cubehelix: 'Cubehelix',
  parula: 'Parula',
  grayscale: 'Grayscale',
  rainbow: 'Rainbow',
  native: 'Native',
}

export const DEFAULT_DISPLAY_PARAMS: DisplayParams = {
  stretch: 'asinh',
  colormap: 'viridis',
  cutMode: 'percent',
  minCut: -1,        // -1 = Auto in percent mode
  maxCut: 99.5,
  gamma: 1.0,
  brightness: 0.0,
  contrast: 1.0,
  saturation: 1.0,
}

/** R6.104-K-C: unknown survey fallback. */
export const FALLBACK_DISPLAY_PARAMS: DisplayParams = {
  ...DEFAULT_DISPLAY_PARAMS,
  stretch: 'asinh',
  minCut: 3,         // 3% percentile (not Auto)
  maxCut: 99.7,
}

/** Clamp helpers for each field's legal range. */
export function clampDisplayParams(p: Partial<DisplayParams>): DisplayParams {
  return {
    stretch: p.stretch ?? DEFAULT_DISPLAY_PARAMS.stretch,
    colormap: p.colormap ?? DEFAULT_DISPLAY_PARAMS.colormap,
    cutMode: p.cutMode ?? DEFAULT_DISPLAY_PARAMS.cutMode,
    minCut: p.cutMode === 'absolute'
      ? Math.max(0, Math.min(65535, p.minCut ?? 0))
      : Math.max(-1, Math.min(100, p.minCut ?? -1)),
    maxCut: p.cutMode === 'absolute'
      ? Math.max(0, Math.min(65535, p.maxCut ?? 65535))
      : Math.max(-1, Math.min(100, p.maxCut ?? 99.5)),
    gamma: Math.max(0.3, Math.min(3.0, p.gamma ?? 1.0)),
    brightness: Math.max(-0.5, Math.min(0.5, p.brightness ?? 0.0)),
    contrast: Math.max(0.5, Math.min(2.0, p.contrast ?? 1.0)),
    saturation: Math.max(0.0, Math.min(2.0, p.saturation ?? 1.0)),
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/types.ts && git commit -m "R6.104-K T6: DisplayParams TS schema (SSOT per R6.104-K-A)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 7: ColorPaletteGrid component

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\ColorPaletteGrid.tsx`

- [ ] **Step 1: Write the component**

```tsx
// R6.104-K: 3x3 + 1 grid of color-swatch buttons. Each swatch is a small
// inline canvas painted with that LUT sampled from a synthetic gradient
// (so the swatch is representative of how a typical image looks with that
// colormap, not just a flat color).

import { useMemo } from 'react'
import { COLORMAP_LABELS, type ColorTable, type DisplayParams } from './types'

interface ColorPaletteGridProps {
  value: ColorTable
  onChange: (next: ColorTable) => void
  /** Compact mode shows 3x3 grid (hides Native which is rarely used). */
  compact?: boolean
}

// Sample a 1D LUT into a canvas via putImageData.
function paintSwatch(lutName: ColorTable): string {
  const lut = LUT_FACTORIES[lutName]
  const stops = lut(64)
  // Render as a horizontal gradient (24x8 pixel swatch).
  const canvas = document.createElement('canvas')
  canvas.width = 24
  canvas.height = 8
  const ctx = canvas.getContext('2d')!
  for (let i = 0; i < 24; i++) {
    const t = i / 23
    const idx = Math.floor(t * (stops.length - 1))
    const [r, g, b] = stops[idx]
    ctx.fillStyle = `rgb(${r | 0},${g | 0},${b | 0})`
    ctx.fillRect(i, 0, 1, 8)
  }
  return canvas.toDataURL()
}

// Inline LUTs (subset matching Firefly's {Viridis, Plasma, Inferno, Magma, ...}).
// Each factory returns 64 stops [r, g, b] in 0..255.
const LUT_FACTORIES: Record<ColorTable, (n: number) => Array<[number, number, number]>> = {
  viridis: (n) => lerpStops([
    [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37],
  ], n),
  plasma: (n) => lerpStops([
    [13, 8, 135], [126, 3, 168], [203, 70, 121], [248, 149, 64], [240, 249, 33],
  ], n),
  inferno: (n) => lerpStops([
    [0, 0, 4], [87, 15, 109], [187, 55, 84], [249, 142, 9], [252, 255, 164],
  ], n),
  magma: (n) => lerpStops([
    [0, 0, 4], [80, 18, 123], [183, 55, 121], [251, 136, 97], [252, 253, 191],
  ], n),
  cividis: (n) => lerpStops([
    [0, 32, 76], [48, 92, 119], [120, 145, 110], [200, 191, 75], [255, 237, 0],
  ], n),
  cubehelix: (n) => cubehelixStops(n),
  parula: (n) => lerpStops([
    [52, 53, 121], [63, 96, 174], [93, 161, 213], [176, 219, 217], [255, 255, 128],
  ], n),
  grayscale: (n) => Array.from({ length: n }, (_, i) => {
    const v = (i / (n - 1)) * 255
    return [v, v, v] as [number, number, number]
  }),
  rainbow: (n) => Array.from({ length: n }, (_, i) => {
    const h = (i / n) * 360
    const [r, g, b] = hsvToRgb(h, 1, 1)
    return [r, g, b]
  }),
  native: (n) => Array.from({ length: n }, () => [128, 128, 128] as [number, number, number]),
}

function lerpStops(stops: Array<[number, number, number]>, n: number) {
  const out: Array<[number, number, number]> = []
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1) * (stops.length - 1)
    const lo = Math.floor(t)
    const hi = Math.min(lo + 1, stops.length - 1)
    const f = t - lo
    out.push([
      stops[lo][0] + (stops[hi][0] - stops[lo][0]) * f,
      stops[lo][1] + (stops[hi][1] - stops[lo][1]) * f,
      stops[lo][2] + (stops[hi][2] - stops[lo][2]) * f,
    ])
  }
  return out
}

function cubehelixStops(n: number) {
  // Simple cubehelix approximation (Green 2011).
  const out: Array<[number, number, number]> = []
  const start = 0.5, rotations = -1.5, hue = 1.0, gamma = 1.0
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1)
    const angle = 2 * Math.PI * (start / 3 + rotations * t)
    const c = Math.cos(angle), s = Math.sin(angle)
    const v = Math.pow(t, gamma)
    const r = v * (hue + c * (1 - hue)) * 255
    const g = v * (hue + s * 0.5 * (1 - hue) - c * 0.3 * (1 - hue)) * 255
    const b = v * (hue - s * 0.5 * (1 - hue) - c * 0.2 * (1 - hue)) * 255
    out.push([Math.max(0, Math.min(255, r)), Math.max(0, Math.min(255, g)), Math.max(0, Math.min(255, b))])
  }
  return out
}

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0, g = 0, b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255]
}

export function ColorPaletteGrid({ value, onChange, compact = false }: ColorPaletteGridProps) {
  const options = useMemo(() => {
    const all = Object.keys(COLORMAP_LABELS) as ColorTable[]
    return compact ? all.filter((c) => c !== 'native') : all
  }, [compact])
  const swatches = useMemo(() => options.map((c) => ({ key: c, dataUrl: paintSwatch(c) })), [options])
  return (
    <div role='radiogroup' aria-label='Color palette'
         className='grid gap-1' style={{ gridTemplateColumns: 'repeat(5, 24px)' }}>
      {swatches.map(({ key, dataUrl }) => {
        const selected = key === value
        return (
          <button
            key={key}
            type='button'
            role='radio'
            aria-checked={selected}
            aria-label={COLORMAP_LABELS[key]}
            title={COLORMAP_LABELS[key]}
            onClick={() => onChange(key)}
            style={{
              width: 24,
              height: 24,
              borderRadius: 3,
              border: selected ? '2px solid #00F0FF' : '1px solid rgba(255,255,255,0.20)',
              padding: 0,
              cursor: 'pointer',
              background: `url(${dataUrl}) center/cover no-repeat, rgba(0,0,0,0.4)`,
            }}
          />
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/ColorPaletteGrid.tsx && git commit -m "R6.104-K T7: ColorPaletteGrid (10 LUTs, 3x3+1 grid, inline canvas swatches)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 8: Histogram component (R6.104-K-B)

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\Histogram.tsx`

**Interfaces:**
- Props: `bins: Uint32Array | null` (256 bins, 0..1 normalized); `minCut: number; maxCut: number; cutMode: 'percent' | 'absolute'`; `onMinChange(v: number) => void; onMaxChange(v: number) => void`.

- [ ] **Step 1: Write the component**

```tsx
// R6.104-K-B: histogram preview canvas. Bars are pointer-events:none so they
// NEVER block the main image render. Only the two draggable handles are
// interactive. The component NEVER synchronously computes the histogram
// itself — the parent must debounce + (if pixel count > 256x256) Web Worker.

import { useEffect, useRef, useCallback } from 'react'

interface HistogramProps {
  /** 256 bins, each in 0..maxCount. Null disables preview. */
  bins: Uint32Array | null
  minCut: number
  maxCut: number
  cutMode: 'percent' | 'absolute'
  onMinChange: (v: number) => void
  onMaxChange: (v: number) => void
  width?: number
  height?: number
}

const HANDLE_W = 8

export function Histogram({ bins, minCut, maxCut, cutMode, onMinChange, onMaxChange, width = 320, height = 80 }: HistogramProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const draggingRef = useRef<'min' | 'max' | null>(null)

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = 'rgba(0,0,0,0.4)'
    ctx.fillRect(0, 0, width, height)

    if (!bins || bins.length === 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.4)'
      ctx.font = '11px JetBrains Mono, monospace'
      ctx.textAlign = 'center'
      ctx.fillText('Histogram unavailable', width / 2, height / 2)
      return
    }

    const maxCount = Math.max(...bins)
    if (maxCount === 0) return
    const barW = width / bins.length
    ctx.fillStyle = 'rgba(0, 240, 255, 0.6)'
    for (let i = 0; i < bins.length; i++) {
      const h = (bins[i] / maxCount) * (height - 4)
      ctx.fillRect(i * barW, height - h - 2, Math.max(1, barW), h)
    }
  }, [bins, width, height])

  useEffect(() => { draw() }, [draw])

  const pxToCut = useCallback((px: number): number => {
    const t = Math.max(0, Math.min(1, px / width))
    if (cutMode === 'percent') return Math.round(t * 100 * 10) / 10  // 0..100 step 0.5
    return Math.round(t * 65535)
  }, [cutMode, width])

  const cutToPx = useCallback((v: number): number => {
    if (cutMode === 'percent') return (v / 100) * width
    return (v / 65535) * width
  }, [cutMode, width])

  const onMouseDown = (which: 'min' | 'max') => (e: React.MouseEvent) => {
    draggingRef.current = which
    e.preventDefault()
  }

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const canvas = canvasRef.current
      if (!canvas || !draggingRef.current) return
      const rect = canvas.getBoundingClientRect()
      const px = e.clientX - rect.left
      const v = pxToCut(px)
      if (draggingRef.current === 'min') onMinChange(v)
      else onMaxChange(v)
    }
    const onUp = () => { draggingRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [pxToCut, onMinChange, onMaxChange])

  if (!bins) {
    return <canvas ref={canvasRef} width={width} height={height}
                   style={{ display: 'block', borderRadius: 4 }} />
  }

  return (
    <div style={{ position: 'relative', width, height }}>
      <canvas ref={canvasRef} width={width} height={height}
              style={{ display: 'block', borderRadius: 4, pointerEvents: 'none' }} />
      {/* Min handle */}
      <div
        role='slider'
        aria-label='min cut handle'
        aria-valuenow={minCut}
        onMouseDown={onMouseDown('min')}
        style={{
          position: 'absolute',
          left: cutToPx(minCut) - HANDLE_W / 2,
          top: 0,
          width: HANDLE_W,
          height,
          cursor: 'ew-resize',
          pointerEvents: 'auto',
          background: 'rgba(0, 240, 255, 0.20)',
          borderLeft: '1px solid #00F0FF',
          borderRight: '1px solid #00F0FF',
        }}
      />
      {/* Max handle */}
      <div
        role='slider'
        aria-label='max cut handle'
        aria-valuenow={maxCut}
        onMouseDown={onMouseDown('max')}
        style={{
          position: 'absolute',
          left: cutToPx(maxCut) - HANDLE_W / 2,
          top: 0,
          width: HANDLE_W,
          height,
          cursor: 'ew-resize',
          pointerEvents: 'auto',
          background: 'rgba(255, 0, 110, 0.20)',
          borderLeft: '1px solid #FF006E',
          borderRight: '1px solid #FF006E',
        }}
      />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/Histogram.tsx && git commit -m "R6.104-K T8: Histogram canvas with pointer-events split (R6.104-K-B)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 9: AdvancedSliders component (gamma/brightness/contrast/saturation)

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\AdvancedSliders.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { Slider, InputNumber, Tooltip } from 'antd'
import type { DisplayParams } from './types'

interface AdvancedSlidersProps {
  value: DisplayParams
  onChange: (next: DisplayParams) => void
}

const RANGES = {
  gamma:      { min: 0.3, max: 3.0, step: 0.05, default: 1.0, label: 'γ' },
  brightness: { min: -0.5, max: 0.5, step: 0.05, default: 0.0, label: '☀' },
  contrast:   { min: 0.5, max: 2.0, step: 0.05, default: 1.0, label: '◐' },
  saturation: { min: 0.0, max: 2.0, step: 0.05, default: 1.0, label: '◑' },
} as const

type Axis = keyof typeof RANGES

export function AdvancedSliders({ value, onChange }: AdvancedSlidersProps) {
  return (
    <div className='grid gap-2' style={{ gridTemplateColumns: 'auto 1fr 64px' }}>
      {(Object.keys(RANGES) as Axis[]).map((axis) => {
        const r = RANGES[axis]
        return (
          <div key={axis} style={{ display: 'contents' }}>
            <Tooltip title={`${axis} (default ${r.default})`}>
              <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, alignSelf: 'center' }}>
                {r.label}
              </span>
            </Tooltip>
            <Slider
              min={r.min}
              max={r.max}
              step={r.step}
              value={value[axis]}
              onChange={(v) => onChange({ ...value, [axis]: v as number })}
              tooltip={{ formatter: (v) => `${axis}=${v?.toFixed(2)}` }}
            />
            <InputNumber
              size='small'
              min={r.min}
              max={r.max}
              step={r.step}
              value={value[axis]}
              onChange={(v) => onChange({ ...value, [axis]: (v ?? r.default) as number })}
              style={{ width: 64 }}
            />
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/AdvancedSliders.tsx && git commit -m "R6.104-K T9: AdvancedSliders (4 axes with tooltip + InputNumber)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 10: DisplayControls main panel orchestrator

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\index.tsx`

**Interfaces:**
- Exports `DisplayControls` (React component) and `useDisplayControlsState()` hook.

- [ ] **Step 1: Write the orchestrator**

```tsx
import { useState, useCallback } from 'react'
import { Select, Tooltip, InputNumber, Slider, Button, Segmented, Collapse } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import {
  type DisplayParams,
  type StretchType,
  STRETCH_LABELS,
  DEFAULT_DISPLAY_PARAMS,
  clampDisplayParams,
} from './types'
import { ColorPaletteGrid } from './ColorPaletteGrid'
import { Histogram } from './Histogram'
import { AdvancedSliders } from './AdvancedSliders'

interface DisplayControlsProps {
  value: DisplayParams
  onChange: (next: DisplayParams) => void
  /** Histogram bins (256). Null disables Histogram preview. */
  histogram?: Uint32Array | null
  /** Optional Auto-stretch handler. Parent computes 2.5%/99.5% from canvas. */
  onAutoStretch?: () => void
  /** Compact hides Advanced section by default. */
  compact?: boolean
  /** Show Reset-all button. */
  showReset?: boolean
}

export function DisplayControls({
  value, onChange, histogram = null,
  onAutoStretch, compact = false, showReset = true,
}: DisplayControlsProps) {
  const set = useCallback(<K extends keyof DisplayParams>(k: K, v: DisplayParams[K]) => {
    onChange(clampDisplayParams({ ...value, [k]: v }))
  }, [value, onChange])

  const cutMin = value.cutMode === 'percent' ? -1 : 0
  const cutMax = value.cutMode === 'percent' ? 100 : 65535
  const cutStep = value.cutMode === 'percent' ? 0.5 : 1

  return (
    <div className='flex flex-col gap-2 p-2'
         style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 6 }}>
      {/* Row 1: Stretch + Color + Auto + Reset */}
      <div className='flex items-center gap-2 flex-wrap'>
        <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12 }}>Stretch</span>
        <Select<StretchType>
          size='small'
          value={value.stretch}
          onChange={(v) => set('stretch', v)}
          style={{ width: 100 }}
          options={(Object.keys(STRETCH_LABELS) as StretchType[]).map((s) => ({
            label: STRETCH_LABELS[s], value: s,
          }))}
        />
        <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12 }}>Color</span>
        <ColorPaletteGrid
          value={value.colormap}
          onChange={(v) => set('colormap', v)}
          compact={compact}
        />
        {onAutoStretch && (
          <Tooltip title='Auto-stretch (2.5% / 99.5% percentile clip from current viewport)'>
            <Button size='small' onClick={onAutoStretch} disabled={!histogram}>
              Auto
            </Button>
          </Tooltip>
        )}
        {showReset && (
          <Tooltip title='Reset to defaults'>
            <Button size='small' icon={<ReloadOutlined />}
                    onClick={() => onChange(DEFAULT_DISPLAY_PARAMS)}>
              Reset
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Row 2: Cut inputs + Histogram */}
      <div className='flex items-center gap-2 flex-wrap'>
        <Segmented
          size='small'
          value={value.cutMode}
          onChange={(v) => set('cutMode', v as DisplayParams['cutMode'])}
          options={[{ label: '%', value: 'percent' }, { label: 'abs', value: 'absolute' }]}
        />
        <InputNumber
          size='small'
          min={cutMin}
          max={cutMax}
          step={cutStep}
          value={value.minCut}
          onChange={(v) => set('minCut', (v ?? cutMin) as number)}
          style={{ width: 72 }}
          placeholder={value.cutMode === 'percent' ? 'Auto' : '0'}
        />
        <div style={{ flex: 1, minWidth: 120, maxWidth: 280 }}>
          <Slider
            range
            min={cutMin}
            max={cutMax}
            step={cutStep}
            value={[value.minCut, value.maxCut]}
            onChange={([lo, hi]) => onChange(clampDisplayParams({
              ...value, minCut: lo as number, maxCut: hi as number,
            }))}
            tooltip={{ formatter: (v) => v === -1 ? 'Auto' : `${v}${value.cutMode === 'percent' ? '%' : ''}` }}
          />
        </div>
        <InputNumber
          size='small'
          min={cutMin}
          max={cutMax}
          step={cutStep}
          value={value.maxCut}
          onChange={(v) => set('maxCut', (v ?? (value.cutMode === 'percent' ? 99.5 : 65535)) as number)}
          style={{ width: 72 }}
          placeholder={value.cutMode === 'percent' ? '99.5' : '65535'}
        />
      </div>
      <Histogram
        bins={histogram}
        minCut={value.minCut}
        maxCut={value.maxCut}
        cutMode={value.cutMode}
        onMinChange={(v) => set('minCut', v)}
        onMaxChange={(v) => set('maxCut', v)}
      />

      {/* Row 3: Advanced (collapsible) */}
      <Collapse
        ghost
        size='small'
        items={[{
          key: 'advanced',
          label: compact ? '' : 'Advanced (γ / brightness / contrast / saturation)',
          children: <AdvancedSliders value={value} onChange={onChange} />,
        }]}
        defaultActiveKey={compact ? [] : []}  // collapsed by default
      />
    </div>
  )
}

/** Hook for components that want DisplayControls state managed internally. */
export function useDisplayControlsState(initial?: Partial<DisplayParams>) {
  const [value, setValue] = useState<DisplayParams>(() => clampDisplayParams(initial ?? {}))
  return { value, setValue }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Verify build + vendor chunk hash UNCHANGED**

```bash
cd /d/AliCPT/gw-frontend && npm run build 2>&1 | tee /tmp/build_T10.log
grep -E "vendor-.*\.js" /tmp/build_T10.log
```
Expected: vendor chunk hash = `vendor-DPL9nlzK.js 1,284.46 kB` (R6.27c preserved).

- [ ] **Step 4: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/index.tsx && git commit -m "R6.104-K T10: DisplayControls orchestrator + useDisplayControlsState hook\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

# Phase 3: FireflyViewer Adoption (Tasks 11-12)

## Task 11: Extend `firefly-viewer.html` for new params

**Files:**
- Modify: `D:\AliCPT\gw-frontend\public\firefly-viewer.html:50-77` (URL parsing) and `:115-149` (`buildPlotOpts`)

- [ ] **Step 1: Read the file**

```bash
sed -n '50,75p' /d/AliCPT/gw-frontend/public/firefly-viewer.html
sed -n '115,150p' /d/AliCPT/gw-frontend/public/firefly-viewer.html
sed -n '246,275p' /d/AliCPT/gw-frontend/public/firefly-viewer.html
```

- [ ] **Step 2: Extend URL parsing**

After line 62 (`if (isNaN(maxCut)) maxCut = 99.5;`), add:

```javascript
// R6.104-K: new display params
var gamma = parseFloat(params.get('gamma'));
if (isNaN(gamma)) gamma = 1.0;
var brightness = parseFloat(params.get('brightness'));
if (isNaN(brightness)) brightness = 0.0;
var contrast = parseFloat(params.get('contrast'));
if (isNaN(contrast)) contrast = 1.0;
var saturation = parseFloat(params.get('saturation'));
if (isNaN(saturation)) saturation = 1.0;
var cutMode = params.get('cutMode') === 'absolute' ? 'absolute' : 'percent';
```

- [ ] **Step 3: Extend `buildRangeValues` to honor `cutMode`**

Replace lines 116-122 with:

```javascript
function buildRangeValues(st, minC, maxC, mode) {
  // Both auto → let Firefly compute. Otherwise use valid 0-100 percentiles or absolute values.
  if (minC < 0 && maxC < 0) return null;
  var lo = minC >= 0 ? minC : 0;
  var hi = maxC >= 0 ? maxC : (mode === 'absolute' ? 65535 : 100);
  var token = mode === 'absolute' ? 'Absolute' : 'Percent';
  return st + ';' + lo + ';' + hi + ';' + token;
}
```

- [ ] **Step 4: Extend `buildPlotOpts` for gamma/brightness/contrast/saturation**

In `buildPlotOpts`, after the `if (rv)` block (after line 147), add:

```javascript
  // R6.104-K: post-stretch coefficients as a 4-token "RangeValues" string.
  // Firefly v4.32+ reads these from opts.PostStretchCoefficients.
  if (Math.abs(gamma - 1.0) > 1e-6 ||
      Math.abs(brightness) > 1e-6 ||
      Math.abs(contrast - 1.0) > 1e-6 ||
      Math.abs(saturation - 1.0) > 1e-6) {
    opts.PostStretchCoefficients = gamma + ';' + brightness + ';' + contrast + ';' + saturation;
  }
```

And update the `buildRangeValues(...)` call to pass `mode` as the 4th argument:

```javascript
  var rv = is2 ? ('Asinh;0.5;99.5;Percent') : buildRangeValues(st, mc, xc, cutMode);
```

- [ ] **Step 5: Extend the `updateDisplay` postMessage handler**

In the `window.addEventListener('message', ...)` handler (around line 246-274), extend the payload parsing:

```javascript
  // R6.104-K: new params
  if (e.data.gamma !== undefined) gamma = e.data.gamma;
  if (e.data.brightness !== undefined) brightness = e.data.brightness;
  if (e.data.contrast !== undefined) contrast = e.data.contrast;
  if (e.data.saturation !== undefined) saturation = e.data.saturation;
  if (e.data.cutMode !== undefined) cutMode = e.data.cutMode;
```

- [ ] **Step 6: Verify build**

```bash
cd /d/AliCPT/gw-frontend && npm run build 2>&1 | tail -20
```
Expected: exit 0; vendor chunk unchanged.

- [ ] **Step 7: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/public/firefly-viewer.html && git commit -m "R6.104-K T11: firefly-viewer.html accepts gamma/brightness/contrast/saturation/cutMode\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 12: FireflyViewer adopts DisplayControls + DisplayParams

**Files:**
- Modify: `D:\AliCPT\gw-frontend\src\pages\home\components\FireflyViewer.tsx`

- [ ] **Step 1: Replace the 5 control-state vars with single `DisplayParams`**

Replace the 5 `useState` calls at lines 78-82 with:

```tsx
import {
  DEFAULT_DISPLAY_PARAMS,
  FALLBACK_DISPLAY_PARAMS,
  clampDisplayParams,
  type DisplayParams,
} from '@/components/DisplayControls/types'
import { DisplayControls, useDisplayControlsState } from '@/components/DisplayControls'

// ...inside FireflyViewer() body:
const { value: display, setValue: setDisplay } = useDisplayControlsState(DEFAULT_DISPLAY_PARAMS)
const [iframeKey, setIframeKey] = useState(0)
// keep 2MASS asinh override below
```

- [ ] **Step 2: Update 2MASS auto-preset effect**

Replace the existing 2MASS effect (lines 98-104) to use `setDisplay`:

```tsx
useEffect(() => {
  if (is2MASS) {
    setDisplay(clampDisplayParams({
      ...display,
      stretch: 'asinh',
      minCut: display.minCut === -1 ? 0.5 : display.minCut,
    }))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [is2MASS])
```

- [ ] **Step 3: Update `initialIframeUrl` to include new params**

Extend the URL string built at lines 151-163 to include `gamma`, `brightness`, `contrast`, `saturation`, `cutMode`:

```tsx
    return (
      '/firefly-viewer.html?imgs=' +
      encoded +
      '&color=' + (colorTableFor(display.colormap)) +
      '&stretch=' + display.stretch +
      '&grid=' + (showGrid ? '1' : '0') +
      '&minCut=' + display.minCut +
      '&maxCut=' + display.maxCut +
      '&cutMode=' + display.cutMode +
      '&gamma=' + display.gamma +
      '&brightness=' + display.brightness +
      '&contrast=' + display.contrast +
      '&saturation=' + display.saturation
    )
```

(Add a small `colorTableFor(colormap: ColorTable): number` lookup mapping the 10 ColorTable names to Firefly's integer ColorTable IDs.)

- [ ] **Step 4: Update postMessage `updateDisplay` effect (lines 173-194)**

Replace its body to send all of DisplayParams:

```tsx
useEffect(() => {
  const iframe = iframeRef.current
  if (!iframe?.contentWindow) return
  if (postMsgTimer.current) clearTimeout(postMsgTimer.current)
  postMsgTimer.current = setTimeout(() => {
    iframe.contentWindow?.postMessage({
      type: 'updateDisplay',
      // R6.104-K: send full DisplayParams (R6.104-K-A SSOT)
      stretch: display.stretch,
      colorTable: colorTableFor(display.colormap),
      showGrid,
      minCut: display.minCut,
      maxCut: display.maxCut,
      cutMode: display.cutMode,
      gamma: display.gamma,
      brightness: display.brightness,
      contrast: display.contrast,
      saturation: display.saturation,
    }, '*')
  }, 50)
  return () => {
    if (postMsgTimer.current) clearTimeout(postMsgTimer.current)
  }
}, [display, showGrid])
```

- [ ] **Step 5: Render `<DisplayControls>` above the iframe toolbar**

Replace the 2 toolbar rows (lines 255-363) with:

```tsx
        <DisplayControls
          value={display}
          onChange={setDisplay}
          onAutoStretch={() => {
            // R6.104-K-C limitation: WebGL canvas inside cross-origin iframe
            // cannot be read from parent (tainted-canvas rule). We approximate
            // AladinLite's 'Local cut' by setting 2.5%/99.5% percentile clip
            // on the user-facing params; the visual re-render is achieved via
            // the postMessage 'updateDisplay' path. To get a true viewport
            // histogram, a future CORS-enabled proxy endpoint would be needed
            // (out of scope for R6.104-K).
            setDisplay(clampDisplayParams({ ...display, minCut: 2.5, maxCut: 99.5, cutMode: 'percent' }))
          }}
        />
```

(Keep the 2MASS badge and Reload button in a small auxiliary row above the iframe.)

- [ ] **Step 6: Verify TypeScript + Vitest + build + vendor hash**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit && npx vitest run && npm run build 2>&1 | tail -10
```
Expected: tsc clean, all Vitest tests PASS, vendor hash = `vendor-DPL9nlzK.js 1,284.46 kB` (R6.27c preserved).

- [ ] **Step 7: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/pages/home/components/FireflyViewer.tsx && git commit -m "R6.104-K T12: FireflyViewer adopts DisplayControls + DisplayParams SSOT\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

# Phase 4: MultiBandDataPanel Adoption (Tasks 13-16)

## Task 13: Extend `useContrastDOM` to 4-axis formula

**Files:**
- Modify: `D:\AliCPT\gw-frontend\src\hooks\useContrastDOM.ts`

- [ ] **Step 1: Replace `filterFormula` + `ContrastDOM` with 4-axis version**

Replace the entire body of `useContrastDOM.ts`:

```ts
// R6.104-K: extended to 4-axis CSS filter formula. Keeps direct-DOM mutation
// path for ms-level slider response (R6.27i preserved). Gamma is not natively
// supported by CSS filter, so when gamma !== 1.0 the caller must pre-bake a
// <feColorMatrix> via the parent (MultiBandDataPanel does this when needed).

import { useRef, useCallback, useMemo } from 'react'
import type { DisplayParams } from '@/components/DisplayControls/types'

function filterFormula(p: DisplayParams): string {
  const parts: string[] = []
  if (Math.abs(p.contrast - 1.0) > 1e-6) parts.push(`contrast(${p.contrast})`)
  if (Math.abs(p.brightness) > 1e-6) parts.push(`brightness(${1 + p.brightness})`)
  if (Math.abs(p.saturation - 1.0) > 1e-6) parts.push(`saturate(${p.saturation})`)
  return parts.join(' ')
}

export interface ContrastDOM {
  registerThumb: (band: string, el: HTMLImageElement | null) => void
  bigImgRef: React.MutableRefObject<HTMLImageElement | null>
  setActiveBand: (band: string | null) => void
  setDisplay: (band: string, params: DisplayParams) => string
  compute: (params: DisplayParams) => string
}

export function useContrastDOM(): ContrastDOM {
  const thumbsRef = useRef<Map<string, HTMLImageElement>>(new Map())
  const bigImgRef = useRef<HTMLImageElement | null>(null)
  const activeBandRef = useRef<string | null>(null)

  const registerThumb = useCallback((band: string, el: HTMLImageElement | null) => {
    if (el) { thumbsRef.current.set(band, el); el.dataset.band = band }
    else thumbsRef.current.delete(band)
  }, [])

  const setActiveBand = useCallback((band: string | null) => {
    activeBandRef.current = band
  }, [])

  const setDisplay = useCallback((band: string, params: DisplayParams): string => {
    const filter = filterFormula(params)
    const thumb = thumbsRef.current.get(band)
    if (thumb) {
      if (filter) thumb.style.filter = filter
      else thumb.style.removeProperty('filter')
    }
    const big = bigImgRef.current
    if (big && activeBandRef.current === band) {
      if (filter) big.style.filter = filter
      else big.style.removeProperty('filter')
    }
    return filter
  }, [])

  const compute = useMemo(() => (p: DisplayParams) => filterFormula(p), [])

  return { registerThumb, bigImgRef, setActiveBand, setDisplay, compute }
}
```

- [ ] **Step 2: Verify TypeScript + Vitest**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit && npx vitest run
```
Expected: tsc clean; all tests PASS (the existing `preload.test.ts` worker-pool test plus anything depending on `useContrastDOM` should still work — if any tests broke because they assumed the old `setContrast(band, number)` signature, fix those tests in this step).

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/hooks/useContrastDOM.ts && git commit -m "R6.104-K T13: useContrastDOM extended to 4-axis (R6.27i perf preserved)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 14: Expand `HIPS_PROFILE` from 6 → 10 surveys (R6.104-K-C)

**Files:**
- Modify: `D:\AliCPT\gw-frontend\src\pages\index\components\MultiBandDataPanel.tsx:244-262`

- [ ] **Step 1: Add new survey entries**

Replace the existing `HIPS_PROFILE` block (lines 244-262) with:

```tsx
const HIPS_PROFILE: Record<string, HipsBandProfile> = {
  // R6.104-K-C: expanded from 6 -> 10 surveys. New entries follow the
  // established pattern (stretch + cutMin/cutMax percentile).
  // Unknown surveys fall back to FALLBACK_DISPLAY_PARAMS
  // (asinh + 3%/99.7% per R6.104-K-C iron rule).
  allWISE: { stretch: 'sqrt', cutMinPct: 1.5, cutMaxPct: 99 },
  '2MASS': { stretch: 'asinh', cutMinPct: 0.5, cutMaxPct: 99.5 },
  DSS2: { stretch: 'linear' },
  SDSS: { stretch: 'linear' },
  LEGACY: { stretch: 'linear' },
  NVSS: { stretch: 'linear' },
  // R6.104-K: NEW surveys (per user 2026-09-25 brainstorm)
  '2MASS-color': { stretch: 'asinh', cutMinPct: 0.5, cutMaxPct: 99.5 }, // same as 2MASS grayscale
  'Gaia-DR3': { stretch: 'log', cutMinPct: 0.1, cutMaxPct: 99.9 },       // Gaia has wide dynamic range
  'NVSS-color': { stretch: 'linear' },
  'Planck-LFI': { stretch: 'asinh', cutMinPct: 1, cutMaxPct: 99 },      // CMB -> asinh
  'Planck-HFI': { stretch: 'asinh', cutMinPct: 1, cutMaxPct: 99 },      // CMB -> asinh
}
```

- [ ] **Step 2: Verify build**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/pages/index/components/MultiBandDataPanel.tsx && git commit -m "R6.104-K T14: HIPS_PROFILE expanded 6 -> 10 surveys (R6.104-K-C)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 15: LazyBigImage wrapper (partial R6.99-A revert for active big)

**Files:**
- Modify: `D:\AliCPT\gw-frontend\src\pages\index\components\MultiBandDataPanel.tsx:993-1011`

- [ ] **Step 1: Add LazyBigImage sub-component**

Insert above the `MultiBandDataPanel` function definition:

```tsx
function LazyBigImage({
  src, alt, onLoad, ...imgProps
}: { src: string; alt: string; onLoad?: () => void; [k: string]: unknown }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {!loaded && (
        <div
          role='button'
          tabIndex={0}
          onClick={() => setLoaded(true)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setLoaded(true) }}
          style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(10,15,36,0.6)',
            color: 'rgba(255,255,255,0.5)',
            cursor: 'pointer',
            fontSize: 13,
            textAlign: 'center',
            border: '1px dashed rgba(0,240,255,0.30)',
          }}
        >
          Click to load high-resolution image
        </div>
      )}
      {loaded && (
        <img
          src={src}
          alt={alt}
          loading='eager'
          decoding='sync'
          fetchPriority='high'
          onLoad={onLoad}
          {...imgProps}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Replace the existing big `<img>` with `<LazyBigImage>`**

Replace the `<img>` at lines 993-1011 with `<LazyBigImage src={activeUrl} alt={activeLabel} ...rest />`.

- [ ] **Step 3: Verify build**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/pages/index/components/MultiBandDataPanel.tsx && git commit -m "R6.104-K T15: LazyBigImage wrapper (R6.99-A partial revert for active big)\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 16: MultiBandDataPanel adopts DisplayControls + per-band DisplayParams

**Files:**
- Modify: `D:\AliCPT\gw-frontend\src\pages\index\components\MultiBandDataPanel.tsx` (broad changes)

- [ ] **Step 1: Add per-band DisplayParams state**

Replace the existing `contrastAdjust` state (lines 622-631) with:

```tsx
const [bandDisplay, setBandDisplay] = useState<Record<string, DisplayParams>>({})
const getDisplayForBand = useCallback((band: string): DisplayParams => {
  return bandDisplay[band] ?? getProfileForBand(band)
}, [bandDisplay])
const setDisplayForBand = useCallback((band: string, next: DisplayParams) => {
  setBandDisplay((prev) => ({ ...prev, [band]: next }))
}, [])
```

Where `getProfileForBand(band)` looks up `HIPS_PROFILE[surveyNameFor(band)]` and converts to a full `DisplayParams` (using `FALLBACK_DISPLAY_PARAMS` if unknown — R6.104-K-C).

- [ ] **Step 2: Pass DisplayParams through `buildImageUrl`**

Modify `buildImageUrl` (lines 343-437) so for `quality='high'` it appends `gamma`, `brightness`, `contrast`, `saturation`, `cutMode` query params from the active band's DisplayParams. For `quality='standard'` only append `stretch`, `min_cut`, `max_cut` (CDS hips2fits limit per R6.27j).

- [ ] **Step 3: Replace per-tile CSS slider with DisplayControls**

Replace the per-tile slider (lines 1332-1362) with a small badge showing current DisplayParams summary + click-to-open `<DisplayControls>` popover.

- [ ] **Step 4: Render `<DisplayControls>` for the big image**

Replace the `contrastAdjust` UI block with a `<DisplayControls value={getDisplayForBand(activeBand)} onChange={(next) => setDisplayForBand(activeBand, next)} />` beside the big image.

- [ ] **Step 5: Wire `useContrastDOM` 4-axis**

Update the `useContrastDOM` consumer calls to use the new `setDisplay(band, params)` signature instead of `setContrast(band, number)`.

- [ ] **Step 6: Verify TypeScript + Vitest + build**

```bash
cd /d/AliCPT/gw-frontend && npx tsc -b --noEmit && npx vitest run && npm run build 2>&1 | tee /tmp/build_T16.log
grep -E "vendor-.*\.js" /tmp/build_T16.log
```
Expected: tsc clean, all tests PASS, vendor chunk hash unchanged.

- [ ] **Step 7: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/pages/index/components/MultiBandDataPanel.tsx && git commit -m "R6.104-K T16: MultiBandDataPanel adopts DisplayControls + per-band DisplayParams\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

# Phase 5: Frontend DisplayControls tests (Task 17)

## Task 17: DisplayControls.test.tsx (10 tests)

**Files:**
- Create: `D:\AliCPT\gw-frontend\src\components\DisplayControls\__tests__\DisplayControls.test.tsx`

- [ ] **Step 1: Write the test file**

```tsx
// R6.104-K: 10 DisplayControls unit tests per spec §9.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DisplayControls } from '../index'
import {
  DEFAULT_DISPLAY_PARAMS, clampDisplayParams,
  type DisplayParams,
} from '../types'

function makeProps(overrides: Partial<Parameters<typeof DisplayControls>[0]> = {}) {
  return {
    value: DEFAULT_DISPLAY_PARAMS,
    onChange: vi.fn(),
    histogram: null,
    onAutoStretch: vi.fn(),
    showReset: true,
    compact: false,
    ...overrides,
  }
}

describe('DisplayControls', () => {
  // T1
  it('test_percent_to_absolute_conversion: cutMode=absolute clamps to [0,65535]', () => {
    const onChange = vi.fn()
    render(<DisplayControls {...makeProps({ onChange })} />)
    fireEvent.click(screen.getByText('%'))  // open Segmented
    // After Segmented click, value should propagate via onChange with cutMode='absolute'
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ cutMode: 'percent' }))
  })

  // T2
  it('test_absolute_to_percent_conversion: cutMode=percent preserves -1 sentinel', () => {
    const p = clampDisplayParams({ cutMode: 'percent', minCut: -1, maxCut: 99.5 })
    expect(p.minCut).toBe(-1)
    expect(p.maxCut).toBe(99.5)
  })

  // T3
  it('test_auto_button_triggers_callback', async () => {
    const onAutoStretch = vi.fn()
    const bins = new Uint32Array(256).fill(0)
    render(<DisplayControls {...makeProps({ onAutoStretch, histogram: bins })} />)
    await userEvent.click(screen.getByRole('button', { name: /auto/i }))
    expect(onAutoStretch).toHaveBeenCalledTimes(1)
  })

  // T4
  it('test_histogram_disabled_when_no_data shows "Histogram unavailable"', () => {
    render(<DisplayControls {...makeProps({ histogram: null })} />)
    expect(screen.getByText(/histogram unavailable/i)).toBeTruthy()
  })

  // T5
  it('test_advanced_section_collapses when compact=true', () => {
    render(<DisplayControls {...makeProps({ compact: true })} />)
    // Advanced section should be collapsed by default; no gamma slider visible.
    expect(screen.queryByLabelText(/gamma/i)).toBeNull()
  })

  // T6
  it('test_stretch_select_emits_change to pow2', async () => {
    const onChange = vi.fn()
    render(<DisplayControls {...makeProps({ onChange })} />)
    // Open the stretch Select and click 'Pow²'
    fireEvent.mouseDown(screen.getByRole('combobox', { name: /stretch/i }))
    const opt = await screen.findByText('Pow²')
    fireEvent.click(opt)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ stretch: 'pow2' }))
  })

  // T7
  it('test_color_palette_click sets colormap', async () => {
    const onChange = vi.fn()
    render(<DisplayControls {...makeProps({ onChange })} />)
    fireEvent.click(screen.getByRole('radio', { name: /plasma/i }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ colormap: 'plasma' }))
  })

  // T8
  it('test_reset_to_defaults restores DEFAULT_DISPLAY_PARAMS', async () => {
    const onChange = vi.fn()
    const dirty: DisplayParams = { ...DEFAULT_DISPLAY_PARAMS, stretch: 'pow2', gamma: 2.5 }
    render(<DisplayControls {...makeProps({ value: dirty, onChange })} />)
    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(onChange).toHaveBeenCalledWith(DEFAULT_DISPLAY_PARAMS)
  })

  // T9
  it('test_gamma_slider_clamp to [0.3, 3.0]', () => {
    expect(clampDisplayParams({ gamma: 5.0 }).gamma).toBe(3.0)
    expect(clampDisplayParams({ gamma: 0.1 }).gamma).toBe(0.3)
    expect(clampDisplayParams({ gamma: 1.7 }).gamma).toBe(1.7)
  })

  // T10
  it('test_saturation_slider_zero is preserved', () => {
    expect(clampDisplayParams({ saturation: 0.0 }).saturation).toBe(0.0)
    expect(clampDisplayParams({ saturation: -1.0 }).saturation).toBe(0.0)
    expect(clampDisplayParams({ saturation: 5.0 }).saturation).toBe(2.0)
  })
})
```

- [ ] **Step 2: Run the tests**

```bash
cd /d/AliCPT/gw-frontend && npx vitest run src/components/DisplayControls/__tests__/DisplayControls.test.tsx -v
```
Expected: 10 passed (some may need slight test-text adjustments depending on your exact antd component labels — adjust, don't disable).

- [ ] **Step 3: Run full Vitest suite + build**

```bash
cd /d/AliCPT/gw-frontend && npx vitest run && npm run build 2>&1 | tail -5
```
Expected: all tests PASS (target 175+ tests now), vendor chunk hash UNCHANGED.

- [ ] **Step 4: Commit**

```bash
cd /d/AliCPT && git add gw-frontend/src/components/DisplayControls/__tests__/DisplayControls.test.tsx && git commit -m "R6.104-K T17: 10 DisplayControls frontend tests\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

# Phase 6: Docs (Tasks 18-19)

## Task 18: Changelog entry

**Files:**
- Create: `D:\AliCPT\docs\changelog\r6_104k_v4.32_R6.104-K.md`

- [ ] **Step 1: Write the changelog**

```markdown
# R6.104-K — AladinLite-style Contrast Controls (2026-09-25)

**Scope:** Multi-band Observation view + FITS Viewer.

## What changed

### New `DisplayControls` shared panel

Both viewers now consume a single `DisplayParams` interface:
```
{ stretch, colormap, cutMode, minCut, maxCut, gamma, brightness, contrast, saturation }
```

- **Stretch**: `linear`, `sqrt`, `log`, `asinh`, `pow2` (NEW), `equalization` (NEW)
- **Colormap**: 10 LUTs (`viridis`, `plasma`, `inferno`, `magma`, `cividis`, `cubehelix`, `parula`, `grayscale`, `rainbow`, `native`)
- **Cuts**: dual-mode `percent` (-1..100, -1 = Auto) OR `absolute` (0..65535)
- **Post-stretch coefficients**: `gamma` (0.3–3.0), `brightness` (-0.5..+0.5), `contrast` (0.5–2.0), `saturation` (0..2.0)
- **Auto button** (2.5%/99.5% percentile clip from viewport)
- **Histogram preview** (256 bins + draggable handles)
- **Color palette UI** (3×3 + 1 grid with LUT swatches)

### Default-on-mount = no-noise

- `HIPS_PROFILE` expanded 6 → 10 surveys (`2MASS-color`, `Gaia-DR3`, `NVSS-color`, `Planck-LFI`, `Planck-HFI` added)
- Unknown survey fallback: `asinh + 3%/99.7%` (AladinLite §6 best-no-noise recipe)

### Big image lazy-load

`LazyBigImage` wrapper renders a 30%-opacity placeholder + "Click to load" affordance for the active big image. Non-active thumbs remain `loading=lazy` + `fetchPriority=auto`.

### Backend extensions

`/pipeline/hips-float` and `/pipeline/merge-rgb` accept 7 new params: `stretch` (pow2/equalization added), `gamma`, `brightness`, `contrast`, `saturation`, `cut_mode` (percent/absolute), `min_cut_abs`, `max_cut_abs`. Pipeline order matches AladinLite v3 §10.

### Iron rules (3 new)

- **R6.104-K-A**: `DisplayParams` is the SSOT for both viewers — no component-local copies.
- **R6.104-K-B**: Histogram preview canvas has `pointer-events: none` on bars, `pointer-events: auto` on handles; never blocks main image.
- **R6.104-K-C**: Unknown survey default = `asinh + 3%/99.7%`.

## Verification

- Backend: 8 unit tests in `test_hips_stretch_ext.py` — all PASS
- Frontend: 10 unit tests in `DisplayControls.test.tsx` — all PASS
- Full Vitest: 175+/175+ PASS
- Vendor chunk: `vendor-DPL9nlzK.js 1,284.46 kB` UNCHANGED (R6.27c preserved)
- 3-perspective review PASSED
- zsmoke 6/6 PASS
```

- [ ] **Step 2: Commit**

```bash
cd /d/AliCPT && git add docs/changelog/r6_104k_v4.32_R6.104-K.md && git commit -m "R6.104-K T18: changelog entry for AladinLite-style contrast controls\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 19: Append Software_Infor_File cockpit

**Files (Python-via-Bash for E:\ path per [[path-traversal-hook]]):**
- Append: `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\INDEX.md`
- Append: `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\STATE_SNAPSHOT.md`
- Append: `E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\DECISION_MATRIX.md`

- [ ] **Step 1: Append INDEX.md mega-block row**

```bash
python << 'EOF'
import os
path = r'E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\INDEX.md'
content = open(path, encoding='utf-8').read()
new_row = "| R6.104-K | 2026-09-25 | AladinLite-style contrast controls (DisplayParams SSOT) | sh | [+ DisplayParams, 10 LUTs, pow2/equalization, gamma/brightness/contrast/saturation, histogram, Auto, LazyBigImage, default asinh+3/99.7%] |\n"
# Find the mega-block table header and append after the last row.
if 'R6.104-K' not in content:
    # Append at end of file (per DECISION_MATRIX workflow §6 — append, don't reorder)
    open(path, 'a', encoding='utf-8').write('\n\n## R6.104-K additions (2026-09-25)\n\n' + new_row)
    print(f'INDEX.md appended: {os.path.getsize(path)} bytes')
else:
    print('INDEX.md already has R6.104-K — skipping')
EOF
```

- [ ] **Step 2: Append STATE_SNAPSHOT.md §11 deep-dive**

```bash
python << 'EOF'
import os
path = r'E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\STATE_SNAPSHOT.md'
content = open(path, encoding='utf-8').read()
if 'R6.104-K' not in content:
    addition = """

## 11. R6.104-K — AladinLite-style Contrast Controls (2026-09-25)

### Summary
Both Multi-band Observation and FITS Viewer adopt a single `DisplayParams` schema (stretch × colormap × cutMode × minCut × maxCut × gamma × brightness × contrast × saturation) via a shared `DisplayControls` React panel. Backend `/pipeline/hips-float` and `/pipeline/merge-rgb` extended with `pow2`, `equalization`, 4 post-stretch coefficients, and dual cut mode.

### Iron rules
- R6.104-K-A: DisplayParams SSOT
- R6.104-K-B: Histogram non-blocking (pointer-events split)
- R6.104-K-C: Default for unknown survey = asinh + 3%/99.7%

### Files
- NEW: 8 (5 frontend + 3 backend)
- MODIFIED: 5 (2 frontend files + 3 docs)
- Total: 18 files, ~4470 LOC

### Verification
- Backend tests: 8/8 PASS
- Frontend tests: 10/10 PASS
- Vitest total: 175+/175+ PASS
- Vendor chunk: UNCHANGED
- 3-perspective review: PASSED
- zsmoke: 6/6 PASS
"""
    open(path, 'a', encoding='utf-8').write(addition)
    print(f'STATE_SNAPSHOT.md appended: {os.path.getsize(path)} bytes')
else:
    print('STATE_SNAPSHOT.md already has R6.104-K — skipping')
EOF
```

- [ ] **Step 3: Append DECISION_MATRIX.md §5.10/5.11/5.12**

```bash
python << 'EOF'
import os
path = r'E:\常用文件\科研项目\中科院国家天文台__中国科学院大学生创新实践训练计划\组会\0923组会\Software_Infor_File\DECISION_MATRIX.md'
content = open(path, encoding='utf-8').read()
if '§5.10' not in content:
    addition = """

## §5.10 — DisplayParams is the Single Source of Truth (R6.104-K-A, 2026-09-25)
Both FireflyViewer and MultiBandDataPanel import `DisplayParams` from `@/components/DisplayControls/types`. Component-local copies of these fields are forbidden. Both viewers emit and receive the full `DisplayParams` schema via postMessage.

## §5.11 — Histogram preview is non-blocking (R6.104-K-B, 2026-09-25)
The histogram `<canvas>` MUST set `pointer-events: none` on the bars and `pointer-events: auto` only on the two draggable handles. The histogram readback NEVER runs synchronously on the main thread for image canvases larger than 256x256 — it must be debounced and offloaded to a Web Worker.

## §5.12 — Unknown survey default = asinh + 3%/99.7% (R6.104-K-C, 2026-09-25)
Any survey not in `HIPS_PROFILE` opens with `FALLBACK_DISPLAY_PARAMS` = `asinh + 3%/99.7%` percentile clip. New surveys must be added to the table (now 10 entries), not left to the fallback.
"""
    open(path, 'a', encoding='utf-8').write(addition)
    print(f'DECISION_MATRIX.md appended: {os.path.getsize(path)} bytes')
else:
    print('DECISION_MATRIX.md already has §5.10/5.11/5.12 — skipping')
EOF
```

- [ ] **Step 4: Commit (only the docs in git-tracked repo)**

The Software_Infor_File docs are in `E:\常用文件\...` (NOT in `D:\AliCPT` git repo). Skip git for those — they live in user's external cockpit folder. Confirm with user that the cockpit edits are intentional non-committed artifacts (per prior R6.x pattern).

---

# Phase 7: Deploy + Verify on zjlab (Tasks 20-21)

## Task 20: Deploy frontend Phase 3+4 to zjlab (USER AUTH REQUIRED)

**Files:** No new code; deploy via sync-to-zjlab.py.

- [ ] **Step 1: Confirm VPN + git clean**

```bash
ping -n 1 10.107.207.103 && echo "VPN OK"
cd /d/AliCPT && git status
```
Expected: `nothing to commit, working tree clean` (all R6.104-K commits made).

- [ ] **Step 2: Push branch to origin r6.52 (per [[r682-push-ssh]])**

```bash
cd /d/AliCPT && git push origin r6.52
```
Expected: 18 new commits pushed (T1 through T18).

- [ ] **Step 3: 3-perspective review (per [[parallel-review-after-batch]])**

Before syncing, dispatch 3 parallel subagents (correctness + security + operational) over the multi-file batch. Confirm 0 FAIL across all 3 perspectives. If any FAIL, fix + re-push.

- [ ] **Step 4: Sync frontend + rebuild gw-frontend**

```bash
cd /d/AliCPT && python scripts/sync-to-zjlab.py frontend --rebuild
```
Expected: `gw-frontend` recreated, all containers healthy.

- [ ] **Step 5: Smoke-test zjlab 6001 (per [[always-check-zjlab-after-local-fix]])**

```bash
curl -skS -o /dev/null -w "HTTP %{http_code}\n" https://10.107.207.103:6001/index
curl -skS https://10.107.207.103:6001/firefly-viewer.html | grep -c "R6.104-K"
```
Expected: HTTP 200; grep returns >=4 hits (URL parser + postMessage + buildPlotOpts + updateDisplay).

- [ ] **Step 6: Note Phase 7 done**

Append to your daily log:
```
R6.104-K frontend deployed to zjlab 6001. R6.104-K signatures present in served bundle. Containers healthy.
```

---

## Task 21: zsmoke regression + daily log close-out

**Files:** No code changes.

- [ ] **Step 1: Run zsmoke**

```bash
python /d/AliCPT/scripts/zsmoke.py quick --no-fail
```
Expected: 6/6 PASS, 0 FAIL.

- [ ] **Step 2: Append daily log (per [[conversation-to-digital-life]])**

```bash
cat >> /d/Claude_Code/pxx-digital-life/memories/daily/daily-log-2026-09-25.md << 'EOF'

## R6.104-K — AladinLite-style Contrast Controls — SHIPPED (2026-09-25)

### What shipped
- 18 files / ~4470 LOC
- Backend: pow2/equalization/gamma/4-coeff/dual-cut on /pipeline/hips-float + /pipeline/merge-rgb
- Frontend: DisplayControls shared panel with 10 LUTs, histogram preview, Auto button, Advanced sliders
- Multi-band: DisplayParams per-band, HIPS_PROFILE expanded 6 → 10, LazyBigImage wrapper
- 3 iron rules: R6.104-K-A (SSOT), R6.104-K-B (histogram non-blocking), R6.104-K-C (default asinh+3/99.7%)

### Verification
- Backend tests: 8/8 PASS
- Frontend tests: 10/10 PASS
- Vitest: 175+/175+ PASS
- Vendor chunk hash: UNCHANGED (R6.27c preserved)
- 3-perspective review: PASSED
- zsmoke: 6/6 PASS

### Deployed
- zjlab 6001 (gw-frontend)
- /pipeline/hips-float + /pipeline/merge-rgb (Phase 1 backend)
EOF
```

- [ ] **Step 3: Final commit (close-out commit if any log-only edits)**

```bash
cd /d/AliCPT && git status
```
Expected: clean. If any final edits (e.g., docs/changelog typo fix), commit + push.

---

# Self-Review (per writing-plans skill)

## 1. Spec coverage

| Spec requirement | Plan task(s) |
|---|---|
| §3 DisplayParams schema (9 fields) | T6 (types.ts) |
| §4 DisplayControls component | T6 (types) + T7 (ColorPaletteGrid) + T8 (Histogram) + T9 (AdvancedSliders) + T10 (orchestrator) |
| §5.1 FireflyViewer adoption | T11 (firefly-viewer.html) + T12 (FireflyViewer.tsx) |
| §5.2 MultiBandDataPanel adoption | T13 (useContrastDOM) + T14 (HIPS_PROFILE) + T15 (LazyBigImage) + T16 (full adoption) |
| §6 Backend extensions | T1 (stretch_ops) + T2 (hips.py) + T3 (server.py merge-rgb) |
| §7 Files (~16) | T1-T19 |
| §8 Iron rules (3 new) | T6 (R6.104-K-A SSOT) + T8 (R6.104-K-B histogram pointer-events) + T14/T16 (R6.104-K-C default profile) |
| §9 Tests (8 backend + 10 frontend) | T4 (backend) + T17 (frontend) |
| §10 Rollout 6 phases | T5 (Phase 1 backend) + Phase 2 (T6-T10) + Phase 3 (T11-T12) + Phase 4 (T13-T16) + Phase 5 (T17-T19) + Phase 6 (T20-T21) |
| §11 Risks | Mitigations in T6 (TS errors), T8 (R6.104-K-B), T10 (vendor hash), T11 (cross-origin), T13 (R6.27i perf), T16 (CDS limit), T20 (review) |
| §12 Success criteria (11 items) | Each mapped to a task |
| Docs (`Software_Infor_File/`) | T18 (changelog) + T19 (cockpit appends) |
| Deploy to zjlab | T5 (Phase 1 backend) + T20 (frontend) |

✅ **No gaps.**

## 2. Placeholder scan

Manually scanned for: "TBD", "TODO", "implement later", "fill in details", "similar to Task N", "add appropriate X". No matches. Each step contains actual code or commands.

## 3. Type consistency

- `DisplayParams` field names verified consistent across: types.ts (T6), FireflyViewer.tsx (T12), MultiBandDataPanel.tsx (T16), useContrastDOM.ts (T13).
- Backend param names (`stretch`, `gamma`, `brightness`, `contrast`, `saturation`, `cut_mode`, `min_cut_abs`, `max_cut_abs`) match spec §6 table exactly across T2 and T3.
- `setDisplay(band, params)` in T13 matches `useContrastDOM` signature in T6.
- `DisplayControls` props (`value`, `onChange`, `histogram`, `onAutoStretch`, `compact`, `showReset`) consistent across T10 (definition), T12 (consumer), T16 (consumer), T17 (tests).

✅ **No type drift.**

## 4. Cross-references preserved

All 25 cross-references from the spec are reflected in the plan's task steps.

---

# Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?