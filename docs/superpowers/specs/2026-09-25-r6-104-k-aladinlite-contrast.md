# R6.104-K — AladinLite-style Contrast Controls

> **Date**: 2026-09-25
> **Status**: 🟢 APPROVED (USER auth 2026-09-25; explicit "批准上轮的设计方案")
> **Reference**: https://aladin.cds.unistra.fr/AladinLite/?target=10%2031%2059.8110198526%2B44%2000%2000.261964830&fov=0.1333334&survey=P%2FDSS2%2Fcolor
> **Goal**: Adopt AladinLite v3's contrast/display control surface (parameter names, pipeline order, Auto-stretch, color palette UI) for both the **Multi-band Observation** view (`MultiBandDataPanel.tsx`) and the **FITS Viewer** (`FireflyViewer.tsx`); expand the range of cut adjustment (percent + absolute dual-input); default-open produces optimal no-noise rendering; thumbnails load normally; big image is lazy-loaded; docs in `Software_Infor_File/` reflect the new R6.x ship.

## 1. Problem

### Symptom (USER, 2026-09-25)
"模仿 https://aladin.cds.unistra.fr/AladinLite/ 的对比度参数以及参数调节方式,更新我们软件的 Multi-band Observation 与 FITS Viewer;扩大对比度的调节范围;确保每次默认打开都是最佳的无噪点的效果;缩略图确保正常加载;上方的大图可以采取懒加载的方式。最后更新文档 `Software_Infor_File/`。"

### Root cause (Phase 1)

| # | Surface | Current state | Gap vs AladinLite |
|---|---|---|---|
| 1 | **FITS Viewer** (`FireflyViewer.tsx`) | Color: 8 LUTs; Stretch: 4 (Linear/Log/Sqrt/Asinh); minCut/maxCut: dual slider, range `-1`–`100` step 0.5; defaults `Viridis`/`Log`/`-1` (Auto)/`99.5` | No `pow2` or `Histogram Equalization`; no `native` (passthrough) colormap; no gamma / brightness / contrast / saturation; cuts are percent-only; no histogram preview; no Auto button |
| 2 | **Multi-band Observation** (`MultiBandDataPanel.tsx`) | Per-tile CSS `contrast(1+v/100)` slider -100..+100 step 5; global Std/Hi-Q toggle; per-tile Hi-Q/Std badge; viewer picker (Aladin/Firefly). `HIPS_PROFILE` table hardcodes stretch + percent cuts for 6 surveys (allWISE, 2MASS, DSS2, SDSS, LEGACY, NVSS) | Stretch selector hidden from user; colormap selector hidden from user; no per-band cuts UI; no per-band gamma/brightness/contrast/saturation; no histogram preview; no Auto button; big image eager-loaded (R6.99-A iron rule) |
| 3 | **Default-on-mount** | 2MASS gets forced `Asinh + 0.5/99.5` (Firefly side); other surveys use whatever `HIPS_PROFILE` says or no cuts | Generic auto-stretch is NOT applied for unknown surveys — a new survey (e.g., Gaia DR3, Planck-LFI/HFI) opens with `asinh` (the fallback) but no percentile clip → noisy |
| 4 | **Big image loading** | R6.99-A iron rule: active big image is `loading=eager` + `fetchPriority=high` | User wants lazy-loading |
| 5 | **Cockpit docs** | `Software_Infor_File/INDEX.md` mega-block lists R6.89–R6.99; `STATE_SNAPSHOT.md` §11 covers R6.99-H; no entry for R6.104-K yet | Need to add R6.104-K row + changelog |

### Why this matters
- Astronomy research workflow requires DS9 / Aladin-style contrast adjustment as a basic feature — current product is "below industry baseline"
- "No-noise default" is the difference between "useful first-render" and "user has to fiddle before they can see anything"
- Feature parity closes a recurring user complaint and aligns our two viewers on the same mental model

## 2. Solution

Adopt AladinLite v3's **DisplayParams** schema as the single source of truth; render a shared **DisplayControls** panel; rewrite both viewers to consume it.

### AladinLite feature parity (decided 2026-09-25 brainstorming)
- Stretch functions: `linear`, `sqrt`, `log`, `asinh`, `pow2`, **`Histogram Equalization`** (added; not in AladinLite v3 but requested)
- Colormap: `viridis`, `plasma`, `inferno`, `magma`, `cividis`, `cubehelix`, `parula`, `grayscale`, `rainbow`, **`native`** (RGB passthrough)
- Min/max cuts: numeric inputs (dual-mode percent + absolute) + dual-handle range slider
- 4 post-stretch coefficients: `gamma` (0.3–3.0), `brightness` (-0.5–+0.5), `contrast` (0.5–2.0), `saturation` (0.0–2.0)
- **Auto-stretch** button (2.5%/99.5% percentile clip from current viewport canvas)
- **Histogram preview** canvas under the cut slider (256 bins + draggable min/max handles)
- **Color palette UI** (3×3 grid with mini preview swatches; replaces current `<Select>`)
- Pipeline order (must NOT change): cut → stretch → colormap → reverse → gamma → brightness → contrast → saturation

### Default-on-mount strategy (decided 2026-09-25 brainstorming)
- `HIPS_PROFILE` table is the source of truth per-survey defaults (already in `MultiBandDataPanel.tsx:244-262`)
- Expand from 6 → ~10 surveys (add `2MASS-color`, `Gaia-DR3`, `NVSS-color`, `Planck-LFI`, `Planck-HFI`)
- **Fallback for unknown survey**: `asinh + 3%/99.7%` percentile clip (AladinLite §6 "best no-noise" recipe)
- FireflyViewer honors the same per-survey profile when `fits[].surveyTag` matches

### Lazy big image (decided 2026-09-25 brainstorming)
- Active big image (`MultiBandDataPanel.tsx` Aladin viewer, line ~993–1011) renders a placeholder (30% opacity, "Click to load" affordance) until user clicks the tile
- On click: `setActiveLoaded(true)` → swap to eager `<img>` with the current params
- Reverts R6.99-A iron rule `R6.99-A-img-decode` only for the **active big**; non-active thumbs remain `loading=lazy` + `fetchPriority=auto`

## 3. DisplayParams Interface (single source of truth)

```typescript
// src/components/DisplayControls/types.ts
export type StretchType =
  | 'linear' | 'sqrt' | 'log' | 'asinh' | 'pow2' | 'equalization'

export type ColorTable =
  | 'viridis' | 'plasma' | 'inferno' | 'magma' | 'cividis'
  | 'cubehelix' | 'parula' | 'grayscale' | 'rainbow' | 'native'

export type CutMode = 'percent' | 'absolute'

export interface DisplayParams {
  stretch: StretchType           // default: 'asinh' (R6.104-K default)
  colormap: ColorTable           // default: 'viridis' (FITS) / 'native' (RGB HiPS)
  cutMode: CutMode               // default: 'percent'
  minCut: number                 // in cutMode units; sentinel -1 = Auto
  maxCut: number                 // in cutMode units
  gamma: number                  // default: 1.0
  brightness: number             // default: 0.0
  contrast: number               // default: 1.0
  saturation: number             // default: 1.0
}
```

**Iron rule**: every consumer (FireflyViewer + MultiBandDataPanel + future viewers) MUST read from this interface. No per-component local copies of these fields.

## 4. DisplayControls Component

`src/components/DisplayControls/index.tsx` (NEW)

### Props
```typescript
interface DisplayControlsProps {
  value: DisplayParams
  onChange: (next: DisplayParams) => void
  histogram?: ImageData | null        // from current viewport; null disables histogram UI
  onAutoStretch?: () => void         // parent computes 2.5/99.5 from canvas
  compact?: boolean                   // default false; true hides gamma/brightness/contrast/saturation under "Advanced" disclosure
}
```

### Subcomponents
- `StretchSelect` — 6-option `<Select>` (linear/sqrt/log/asinh/pow2/equalization); emits `value.stretch`
- `ColorPaletteGrid` — 3×3 grid of color-swatch buttons (10 colors). Each swatch is a 24×24 canvas painted with that LUT for the visible data range
- `CutInputs` — three elements in a row:
  - `<Segmented>` cut mode toggle (percent/absolute)
  - min `<InputNumber>` + dual `<Slider range>` + max `<InputNumber>`
  - When `cutMode === 'percent'`: range `-1`–`100` step 0.5; sentinel `-1` = Auto
  - When `cutMode === 'absolute'`: range `0`–`65535` step 1; no sentinel
  - `<Tooltip>` helper: "Auto" for `-1`, else `${value}%` or `${value}` based on cutMode
- `AutoButton` — calls `onAutoStretch()` if provided; disabled with tooltip when no histogram data
- `HistogramCanvas` — `<canvas width=320 height=80>` rendering 256-bin histogram + 2 vertical draggable handles for min/max; `pointer-events: none` on the bars, `pointer-events: auto` on the handles
- `AdvancedSection` (collapsible) — 4 sliders: gamma (0.3–3.0), brightness (-0.5–+0.5), contrast (0.5–2.0), saturation (0–2.0). Each slider has its own `<InputNumber>` companion + reset to default

### Layout (default expanded)
```
+-- DisplayControls ---------------------------------------------------+
| [Stretch: asinh v] [Color: . . . grid] [Auto] [Reset all]            |
| Cut: [percent|absolute] [min 0.5 ----.------.---- 99.5 max]           |
| +- Histogram (320x80) -------------------------------------------+   |
| | . .. . . . . . . . . . . . . . .  .   vmin    vmax             |   |
| +------------------------------------------------------------------+   |
| v Advanced                                                            |
|   Gamma [1.0 .--.-------]   Brightness [0.0 -.-------]                |
|   Contrast [1.0 .--.-------]  Saturation [1.0 .--.-------]             |
+--------------------------------------------------------------------+
```

## 5. Two Consumers

### 5.1 FireflyViewer (FITS Viewer)
- `FireflyViewer.tsx:78-83` — current `useState<number>` for colorTable / `useState<string>` for stretch etc. → replace with single `useState<DisplayParams>`
- `FireflyViewer.tsx:113-165` `initialIframeUrl` `useMemo` — extend URL params from current 5 (`color`/`stretch`/`grid`/`minCut`/`maxCut`) to 10 (`color`/`stretch`/`minCut`/`maxCut`/`cutMode`/`gamma`/`brightness`/`contrast`/`saturation`)
- `FireflyViewer.tsx:173-194` postMessage `updateDisplay` effect — payload becomes full `DisplayParams`
- New toolbar layout (3 rows):
  - Row 1: `<StretchSelect>` + `<ColorPaletteGrid>` + (2MASS badge if applicable) + Reload
  - Row 2: `<CutInputs>` + Auto + `<HistogramCanvas>` (reads from Firefly's WebGL canvas via `iframeRef.current.contentDocument.querySelector('canvas').getContext('webgl').readPixels(...)` — but cross-origin so falls back to histogram-less Auto)
  - Row 3 (Advanced, collapsed by default): 4 sliders
- `firefly-viewer.html:55-62` — extend URL parsing; new params `gamma` (default 1), `brightness` (0), `contrast` (1), `saturation` (1), `cutMode` ('percent')
- `firefly-viewer.html:125-149` `buildPlotOpts` — when `gamma !== 1.0 || brightness !== 0.0 || contrast !== 1.0 || saturation !== 1.0`, pass to `opts.PostStretchCoefficients = {gamma, brightness, contrast, saturation}` (Firefly >= v4.32 supports these as `RangeValues`-like 4-token strings)
- `firefly-viewer.html:115-122` `buildRangeValues` — extend to handle `cutMode='absolute'`: emit `"<stretch>;<loAbs>;<hiAbs>;Absolute"` instead of `Percent`
- 2MASS auto-preset (lines 98-104 / 124-149) PRESERVED — forces `Asinh + 0.5%/99.5%` only when survey tag matches `/2mass|_j.|_h.|_k./i`

### 5.2 MultiBandDataPanel (Multi-band Observation)
- `MultiBandDataPanel.tsx:622-631` `contrastAdjust` (CSS slider) — REPLACE with `useState<DisplayParams>` per active band
- New per-band `Record<bandKey, DisplayParams>` (replaces both `contrastAdjust` and `HIPS_PROFILE`'s hardcoded values)
- `HIPS_PROFILE` (lines 244-262) EXPANDED to ~10 surveys + explicit fallback to `asinh + 3%/99.7%`
- `MultiBandDataPanel.tsx:300-312` `contrastToCuts` — kept for backward compat with RGB backend merge-rgb params; math unchanged but reads from new `DisplayParams`
- `MultiBandDataPanel.tsx:497-537` `QualityToggle` (Std/Hi-Q) — kept as-is; orthogonal to contrast
- `MultiBandDataPanel.tsx:343-437` `buildImageUrl` — pass through new params:
  - For `quality='high'` (backend `/pipeline/hips-float`): add `gamma`, `brightness`, `contrast`, `saturation`, `cutMode` as query params
  - For `quality='standard'` (direct CDS): only `stretch`, `min_cut`, `max_cut` are accepted by CDS hips2fits; gamma/brightness/contrast/saturation must be applied via CSS filter on the `<img>` (extend `useContrastDOM`)
- Big image Aladin `<div>` (lines 993-1011) — wrapped in new `<LazyBigImage>`:
  - Default state: 30% opacity placeholder + "Click to load" affordance
  - On user click: `setLoaded(true)`; swap to `<img loading='eager' decoding='sync' fetchPriority='high'>` with current `DisplayParams`
  - `<DisplayControls>` panel pops up beside the big image
  - Histogram source: `<img>` decoded to canvas via `createImageBitmap()` + `getContext('2d').getImageData()`
- Thumb strip (lines 1029-1390) — per-tile controls:
  - Each tile shows a small `<ColorPaletteGrid>` swatch (1x1, current band color)
  - Each tile shows a small cut-% badge (e.g., "0.5-99.5%")
  - Click tile -> select + propagate to big image DisplayParams
- **`useContrastDOM` hook** (`useContrastDOM.ts`) — EXTEND from single-axis `contrast + brightness` formula to full 4-axis:
  ```typescript
  function filterFormula(p: DisplayParams): string {
    const parts = []
    if (p.contrast !== 1.0) parts.push(`contrast(${p.contrast})`)
    if (p.brightness !== 0.0) parts.push(`brightness(${1 + p.brightness})`)
    if (p.saturation !== 1.0) parts.push(`saturate(${p.saturation})`)
    // gamma: CSS does not natively support gamma filter; must apply via canvas pixel map
    if (p.gamma !== 1.0) parts.push(/* pre-baked gamma applied via canvas */ '')
    return parts.filter(Boolean).join(' ')
  }
  ```
  - When `gamma !== 1.0`, write a gamma-pre-baked CSS variable into `:root` and read it from a `<feColorMatrix>` filter in an SVG `<filter>` element applied to the image

## 6. Backend Pipeline Extensions

`gw-pipeline/src/pipeline/routes/hips.py` — extend `/pipeline/hips-float` and `/pipeline/merge-rgb`:

| Param | Type | Default | Validation |
|---|---|---|---|
| `stretch` | string | `'asinh'` | enum: `linear`, `sqrt`, `log`, `asinh`, `pow2`, `equalization` (NEW) |
| `gamma` | float | `1.0` | `[0.3, 3.0]` |
| `brightness` | float | `0.0` | `[-0.5, 0.5]` |
| `contrast` | float | `1.0` | `[0.5, 2.0]` |
| `saturation` | float | `1.0` | `[0.0, 2.0]` |
| `cut_mode` | string | `'percent'` | enum: `percent`, `absolute` |
| `min_cut_abs` | float | `0` | `[0, 65535]` (when `cut_mode='absolute'`) |
| `max_cut_abs` | float | `65535` | `[0, 65535]` (when `cut_mode='absolute'`) |

### New stretch implementations (in `hips.py`)

```python
def apply_pow2(pixels, min_cut, max_cut):
    """y = x^2  -- brightens faint features"""
    norm = (pixels - min_cut) / (max_cut - min_cut)
    return np.clip(norm, 0, 1) ** 2

def apply_equalization(pixels, min_cut, max_cut, n_bins=256):
    """Histogram equalization -- uniformizes distribution across [0, 1]"""
    norm = np.clip((pixels - min_cut) / (max_cut - min_cut), 0, 1)
    hist, edges = np.histogram(norm.flatten(), bins=n_bins, range=(0, 1))
    cdf = np.cumsum(hist) / hist.sum()
    bin_idx = np.clip((norm * (n_bins - 1)).astype(int), 0, n_bins - 1)
    return cdf[bin_idx].reshape(norm.shape)
```

### Pipeline order (mirrors AladinLite v3 §10)
1. subtract minCut
2. divide by (maxCut - minCut)
3. apply `stretch`
4. apply colormap LUT
5. reverse colormap if requested
6. apply `gamma = pow(rgb, 1/gamma)`
7. apply `brightness = rgb + brightness`
8. apply `contrast = (rgb - 0.5) * contrast + 0.5`
9. apply `saturation` via HSV rotate around gray
10. clamp to [0, 1]

## 7. Files (8-10 expected)

| File | Change | LOC |
|---|---|---|
| `gw-frontend/src/components/DisplayControls/types.ts` | NEW -- DisplayParams + sub-types | +50 |
| `gw-frontend/src/components/DisplayControls/index.tsx` | NEW -- panel + subcomponents | +400 |
| `gw-frontend/src/components/DisplayControls/Histogram.tsx` | NEW -- canvas histogram | +150 |
| `gw-frontend/src/components/DisplayControls/ColorPaletteGrid.tsx` | NEW -- 3x3 grid with LUT swatches | +120 |
| `gw-frontend/src/hooks/useContrastDOM.ts` | EXTEND -- 4-axis formula | +60 |
| `gw-frontend/src/pages/home/components/FireflyViewer.tsx` | ADOPT -- DisplayParams state + DisplayControls | +200 / -120 |
| `gw-frontend/public/firefly-viewer.html` | EXTEND -- new URL/postMessage params + new stretch types | +100 |
| `gw-frontend/src/pages/index/components/MultiBandDataPanel.tsx` | ADOPT -- DisplayParams + LazyBigImage + expanded HIPS_PROFILE | +300 / -150 |
| `gw-pipeline/src/pipeline/routes/hips.py` | EXTEND -- pow2 / equalization / gamma / 4 coefficients | +150 |
| `gw-pipeline/src/pipeline/routes/merge_rgb.py` (or similar) | EXTEND -- same params on merge-rgb | +80 |
| `gw-pipeline/tests/test_hips_stretch_ext.py` | NEW -- pow2 / equalization / gamma / cut_mode | +200 |
| `gw-frontend/src/components/DisplayControls/__tests__/DisplayControls.test.tsx` | NEW -- percent<->absolute conversion, Auto button trigger | +100 |
| `docs/changelog/r6_104k_v4.XX_R6.104-K.md` | NEW -- feature changelog | +300 |
| `Software_Infor_File/INDEX.md` | APPEND -- R6.104-K row + iron rules | +20 |
| `Software_Infor_File/STATE_SNAPSHOT.md` | APPEND -- §11 R6.104-K + §3 + §1 version bump | +30 |
| `Software_Infor_File/DECISION_MATRIX.md` | APPEND -- §5.10/5.11/5.12 (DisplayParams SSOT, histogram non-blocking, default profile) | +40 |

**Total**: ~16 files, ~2050 LOC (incl. tests + docs).

## 8. Iron Rules (3 new)

1. **R6.104-K-A** -- `DisplayParams` interface is the **single source of truth** for both viewers. Never duplicate state as component-local `useState`. Both FireflyViewer and MultiBandDataPanel import from `@/components/DisplayControls/types` and emit/receive `DisplayParams`. (Closes the "two mental models" gap between the two viewers.)

2. **R6.104-K-B** -- Histogram preview `<canvas>` MUST render with `pointer-events: none` on the bars AND `pointer-events: auto` on the two draggable min/max handles. The preview NEVER blocks the main image render (no synchronous histogram computation on the main thread -- must be debounced + Web Worker if pixel count > 256x256).

3. **R6.104-K-C** -- Default-on-mount for an UNKNOWN survey MUST use `asinh + 3%/99.7%` percentile clip (AladinLite §6 "best no-noise" recipe). Document this fallback in a comment block above `HIPS_PROFILE` in `MultiBandDataPanel.tsx`. New survey additions go in the table, not the fallback.

## 9. Test Plan

### Unit tests (`test_hips_stretch_ext.py` -- backend, ~8 cases)
1. `test_pow2_stretch` -- input `[0, 0.5, 1]` -> output `[0, 0.25, 1]`
2. `test_equalization_uniformizes` -- input skewed histogram -> output has approximately uniform distribution
3. `test_gamma_correction` -- input mid-gray -> output `(1/gamma)` power
4. `test_cut_mode_absolute` -- `min_cut_abs=100, max_cut_abs=1000` correctly clips without `Percent` token
5. `test_pipeline_order` -- operation sequence matches AladinLite §10
6. `test_invalid_stretch_400` -- `stretch=foobar` -> 400
7. `test_invalid_gamma_400` -- `gamma=10.0` (out of range) -> 400
8. `test_equalization_idempotent` -- re-running on already-equalized data -> unchanged

### Frontend tests (`DisplayControls.test.tsx` -- ~10 cases)
1. `test_percent_to_absolute_conversion` -- `cutMode='absolute'` -> numbers clamped to `[0, 65535]`
2. `test_absolute_to_percent_conversion` -- `cutMode='percent'` -> numbers clamped to `[0, 100]` + `-1` sentinel preserved
3. `test_auto_button_triggers_callback` -- click `<AutoButton>` -> `onAutoStretch` invoked with viewport canvas
4. `test_histogram_disabled_when_no_data` -- `histogram=null` -> canvas shows "Histogram unavailable"
5. `test_advanced_section_collapses` -- `compact=true` -> sliders hidden behind disclosure
6. `test_stretch_select_emits_change` -- pick `pow2` -> `value.stretch === 'pow2'`
7. `test_color_palette_click` -- click swatch -> `value.colormap` updated
8. `test_reset_to_defaults` -- click `Reset all` -> all params back to defaults
9. `test_gamma_slider_clamp` -- input 5.0 -> clamped to 3.0
10. `test_saturation_slider_zero` -- input 0.0 -> `value.saturation === 0.0`

### E2E manual (per [[parallel-review-after-batch]] + [[manual-confirm-major-changes]])
- Open observation, verify default cuts match `HIPS_PROFILE` (or 3%/99.7% fallback for unknown)
- Switch stretch to `pow2`, verify visual change
- Switch stretch to `equalization`, verify uniform histogram
- Click Auto, verify cuts update to ~2.5/99.5
- Drag gamma to 2.0, verify image brightens
- Verify big image is NOT loaded until tile clicked (Network tab: only `<img>` after click)

## 10. Rollout

### Phase 1 -- Backend
- Add pow2/equalization/gamma to `/pipeline/hips-float` + `/pipeline/merge-rgb`
- 8 unit tests
- Deploy via `build-and-deploy-jar.py deploy` (USER auth required per [[r678-classifier-boundary]])
- Verify via curl `/pipeline/hips-float?stretch=pow2&gamma=2.0` -> valid PNG with different md5 than linear

### Phase 2 -- Frontend DisplayControls component
- Build + tests
- No user-facing changes yet -- just the new component exists

### Phase 3 -- FireflyViewer adopts DisplayControls
- Replace 5 control state vars with single `DisplayParams`
- Update `firefly-viewer.html` URL/postMessage parsing
- 3-perspective review (correctness + security + operational)
- Deploy `sync-to-zjlab.py frontend --rebuild`

### Phase 4 -- MultiBandDataPanel adopts DisplayControls
- Replace `contrastAdjust` + per-survey hardcoded cuts with `DisplayParams` per band
- Expand `HIPS_PROFILE` from 6 -> 10 surveys
- Add `<LazyBigImage>` wrapper
- 3-perspective review
- Deploy `sync-to-zjlab.py frontend --rebuild`

### Phase 5 -- Docs
- New `docs/changelog/r6_104k_v4.XX_R6.104-K.md`
- Append `Software_Infor_File/INDEX.md` (R6.104-K row + iron rules R6.104-K-A/B/C)
- Append `Software_Infor_File/STATE_SNAPSHOT.md` (bump version in §1; §3 R6.x list; §9 timeline; §11 new deep-dive)
- Append `Software_Infor_File/DECISION_MATRIX.md` (§5.10/5.11/5.12)
- git commit + push to r6.52 (per [[r682-push-ssh]])

### Phase 6 -- zsmoke regression
- `python D:\AliCPT\scripts\zsmoke.py quick --no-fail` -- 6/6 PASS, 0 FAIL

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Backend pow2/equalization needs separate jar deploy | High | Phase 3/4 frontend depends on Phase 1 backend | Sequential deploy: backend first, then frontend; verify curl in Phase 1 before Phase 3 |
| Histogram readback fails on cross-origin HiPS (CORS) | High | Auto button useless for HiPS images | Graceful fallback: disable Auto + show "Histogram unavailable for this survey"; user can manually enter cuts |
| 4 new sliders bloat the toolbar | Medium | UX cluttered | Group under collapsible "Advanced" disclosure (collapsed by default); `compact=true` mode for narrow screens |
| Lazy big image degrades perceived UX | Medium | User sees blank for 1-2s after first click | Placeholder is semi-transparent + has visible "Click to load" affordance + tooltip explains the behavior |
| Touching `useContrastDOM` breaks R6.27i ms-level slider perf | Low | Slider lag regression | Keep existing direct-DOM `style.filter` mutation path; only ADD new axes, don't change existing `contrast/brightness` formula |
| `firefly-viewer.html` postMessage schema change breaks old parent | Medium | Firefly tab shows wrong cuts on older builds | Add `displayParamsVersion` field; iframe rejects payloads with `version !== 'r6.104-K'` |
| Vendor chunk size increases (R6.27c iron rule) | Medium | Vendor hash changes -> CSP review needed | All new code is in displayControls.tsx -- should NOT pull in new deps; verify `vendor-DPL9nlzK.js` hash unchanged |
| `gamma` not natively supported by CSS `filter` | High | Must pre-bake via canvas or SVG `<feColorMatrix>` | Pre-bake via SVG `<filter>` element appended to DOM; cached per-DisplayParams; reset when params change |

## 12. Success Criteria

1. DisplayControls.test.tsx 10/10 PASS
2. test_hips_stretch_ext.py 8/8 PASS
3. tsc / eslint / vitest all pass (target 165+ tests, 0 regression)
4. Vendor chunk hash unchanged (R6.27c preserved)
5. 3-perspective review PASSED (correctness + security + operational)
6. Backend Phase 1: `curl /pipeline/hips-float?stretch=pow2&gamma=2.0` returns valid PNG with different md5 than linear
7. Frontend Phase 3/4: deployed to zjlab, all 7 containers healthy, R6.104-K signatures (`DisplayParams`, `stretch=pow2`, `gamma`, `HistogramCanvas`) present in served bundle
8. zsmoke 6/6 PASS, 0 FAIL
9. Default-on-mount: open 3 unknown surveys (e.g., Gaia DR3) -> cuts auto-set to 3%/99.7%
10. Big image NOT loaded until user clicks tile (verified in DevTools Network)
11. Software_Infor_File cockpit reflects R6.104-K (INDEX row + STATE_SNAPSHOT §11 + DECISION_MATRIX §5.10-5.12)

## 13. Cross-references

- [[r6103j-firefly-dedup-preload-concurrency]] -- R6.103-J sibling (just-shipped Firefly + preload fixes)
- [[r699a-summary]] -- R6.99-A img-decode iron rule (active big = eager); partially reverted in R6.104-K for active big
- [[r699h-summary]] -- R6.99-H backend HiPS proxy (R6.104-K extends same backend with new stretch types)
- [[r627i-use-contrast-dom]] -- R6.27i ms-level slider perf (preserved; only extended)
- [[r627c-vendor-chunk-split]] -- R6.27c vendor chunk unchanged (verify in Phase 6)
- [[r627j-no-fake-api-params]] -- R6.27j iron rule (use real CDS param names; R6.104-K adds `gamma` etc. only to backend, not CDS direct)
- [[r627f-hips-backend-proxy]] -- R6.27f `<img>` MUST proxy via `/pipeline/` (R6.104-K adds new params to the same endpoint)
- [[mbpanel-divs-thumbnails]] -- empirical Hi-Q 4-8s/tile (R6.104-K lazy-load defers this cost)
- [[gw-aladin-never-break]] -- Aladin iron rules (CSP unchanged)
- [[gw-r627f-hips-backend-proxy]] -- HiPS backend proxy pattern (R6.104-K follows same shape)
- [[r682-push-ssh]] -- SSH push pattern (Phase 5)
- [[parallel-review-after-batch]] -- 3-perspective review BEFORE push (Phase 3+4)
- [[manual-confirm-major-changes]] -- USER auth for backend Phase 1 + frontend Phase 3+4 deploys
- [[r678-classifier-boundary]] -- backend code OK, production deploy needs auth (already authorized for this R)
- [[r699e-post-deploy-frontend-hygiene]] -- post-deploy hygiene (Phase 6 verify)
- [[conversation-to-digital-life]] -- daily log append mandatory on completion
- [[safe-int-env-helper]] -- use `_safe_int_env` for backend env vars
- [[english-naming]] -- English filenames
- [[always-check-zjlab-after-local-fix]] -- 本地修完 GW 前端必查 zjlab 6001 (Phase 6)
- [[gw-software-infor-file]] -- cockpit structure / sync guide (Phase 5)
- [[vpn-startup-procedure]] -- 奇安信 VPN required for bastion (Phase 1+3+4 deploys)