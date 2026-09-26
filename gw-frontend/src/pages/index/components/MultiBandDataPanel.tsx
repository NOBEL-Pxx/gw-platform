import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Empty, Tooltip, Grid, Segmented, Popover } from 'antd'
import { LoadingOutlined, QuestionCircleOutlined } from '@ant-design/icons'

import { useRequest } from 'ahooks'
import { getGravitationalWave } from '@/service'
import Aladin from '@/pages/home/components/Aladin1'
import FireflyViewer from '@/pages/home/components/FireflyViewer'
import { getFitsUrl, getImageUrl } from '@/util/url'
// R6.27f: HiPS now proxied via /pipeline/hips-thumb (see HIPS_PROXY_URL constant)
import { buildOrderedEntries, BAND_INFO, getHipsId } from '@/util/bandOrder'
import type { OrderedEntry } from '@/util/bandOrder'
import { preloadImages, preloadFits } from '@/util/preload'
import PreloadSplash from '@/components/PreloadSplash'
// R6.27i: direct-DOM contrast updates for ms-level slider response.
// Bypasses React reconciliation entirely — slider drag paints at the
// browser's native rate (< 16ms instead of 50-200ms).
import { useContrastDOM } from '@/hooks/useContrastDOM'
import {
  DEFAULT_DISPLAY_PARAMS,
  FALLBACK_DISPLAY_PARAMS,
  clampDisplayParams,
  type DisplayParams,
  type StretchType,
} from '@/components/DisplayControls/types'
// R6.104-K (T16): the shared AladinLite-style control surface. Also used by
// FireflyViewer, so both consumers stay in lockstep (R6.104-K-A SSOT).
import { DisplayControls } from '@/components/DisplayControls'

type ViewerType = 'aladin' | 'firefly' // R6.8a: 'image' tab removed
// R6.8a: only Aladin (FITS overlay + WCS + HiPS) and Firefly (HiPS-native
// multi-color) remain. Default = 'aladin'. RGB click in the strip no longer
// opens an image panel; it only toggles rgbIndex state (kept for parity).
// User views RGB by selecting individual bands in the strip.

interface Props {
  ra?: number
  dec?: number
  uuid?: string
}

// R6.2 lean: single source size — 100px display matches request so backend
// /pipeline/merge-rgb runs at 100² (size² cost). 140 → 100 dropped merge-rgb
// from 5s to 1.3s with no visible quality loss on a ~470px panel.
// R6.99-A: THUMB now scales by viewport (see useBreakpoint in component).
// Module-level const remains as default for non-React contexts (tests).
const THUMB = 100
// R6.61.b: thumb uses 400px for HiPS cutout (preserves R6.13 strategy —
// HiPS JPEG at 400 looks crisp on ~470px panel; 100px FITS is just fallback).
// R6.99-A: THUMB_HIPS_SIZE now also scales by viewport.
const THUMB_HIPS_SIZE = 400

// R6.27g: revert to direct CDS URL — Docker Desktop on local Windows
// intercepts HTTPS outbound from containers (returns 500 with
// "writing response to alasky.cds.unistra.fr:80: connecting to
// 127.0.0.1:7890: connectex: refused"). Browser→CDS works because the
// host network can reach CDS in 1.5s. /pipeline/hips-thumb code path
// remains on zjlab where Docker Desktop interception isn't present.
//
// R6.27g.b: URL builder fix — CDS wants a single `hips` parameter, NOT
// `survey`+`band` separately. Example URL:
//   https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=DSS2/Blue&ra=10.5&dec=-1.2&width=400&height=400&fov=3&stretch=linear&format=jpg
const HIPS_PROXY_URL =
  'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'

// R6.27k: module-level quality flag read by top-level helpers (thumbUrl, largeImageUrl).
// Updated by the component via useEffect. Reading from React state inside these helpers
// would require threading the state through every call site.
let _currentQuality: 'standard' | 'high' = 'standard'
// eslint-disable-next-line react-refresh/only-export-components
export function setHipsQuality(q: 'standard' | 'high') {
  _currentQuality = q
}
// R6.29c: ALL Far-IR / Mid-IR / Near-IR bands auto Hi-Q.
// R6.32: extended to RGB composites. For RGB like allWISE W4W2W1, the
// hipsColor is 'P/allWISE/color' (pre-computed CDS color HiPS) which doesn't
// match the pattern. We check rgbChannels instead — if ALL channels are
// in AUTO_HI_Q, the RGB composite also gets Hi-Q mode (per-channel cut).
const AUTO_HI_Q_SURVEYS = new Set(['allWISE', '2MASS'])
const AUTO_HI_Q_BANDS = new Set(['W1', 'W2', 'W3', 'W4', 'J', 'H', 'K'])
function autoHiQ(hipsId: string): boolean {
  const parts = hipsId.split('/')
  return (
    AUTO_HI_Q_SURVEYS.has(parts[0] || '') && AUTO_HI_Q_BANDS.has(parts[1] || '')
  )
}
// R6.32: check if RGB composite should be Hi-Q based on its channels
function autoHiQRgb(e: {
  kind: string
  rgbChannels?: { r: string; g: string; b: string }
  survey?: string
}): boolean {
  if (e.kind !== 'rgb' || !e.rgbChannels) return false
  if (!e.survey || !AUTO_HI_Q_SURVEYS.has(e.survey)) return false
  // All 3 channels must be in AUTO_HI_Q_BANDS
  const chs = [e.rgbChannels.r, e.rgbChannels.g, e.rgbChannels.b]
  return chs.every((c) => {
    const band = c.split('/')[1] || ''
    return AUTO_HI_Q_BANDS.has(band)
  })
}

function getHipsQuality(hipsId?: string): 'standard' | 'high' {
  // R6.28: AUTO_HI_Q overrides user toggle for known-bad bands (W4, K).
  if (hipsId && autoHiQ(hipsId)) return 'high'
  return _currentQuality
}

function hipsCutoutUrlImpl(
  hips: string,
  ra: number,
  dec: number,
  size: number,
  display: DisplayParams,
  // R6.27k: 'standard' = direct CDS (fast jpg ~30KB).
  //          'high'     = backend /pipeline/hips-float (raw FITS + dither, ~175KB PNG).
  //                     Trades 5.8x volume for: float-precision cuts (no banding)
  //                     + Floyd-Steinberg dithering (no posterization) +
  //                     lossless PNG (no JPEG DCT blocks).
  quality: 'standard' | 'high' = 'standard',
): string {
  // CDS hips2fits wants a single combined 'hips' parameter, NOT survey+band.
  // R6.27g bug: I split 'DSS2/Blue' into survey=DSS2&band=Blue, which 400s
  // with 'Missing parameter: hips'. Fixed: pass the full string.
  // Examples: 'DSS2/Blue', 'allWISE/W4', 'NVSS', '2MASS/K'.
  const cuts = cutsForDisplay(display)

  if (quality === 'high') {
    // R6.27k: route to backend FITS+PNG pipeline.
    // Backend reads raw 32-bit FITS, applies our cut+stretch+dither, returns PNG.
    // R6.104-K: the backend now owns the whole AladinLite post-stretch chain
    // (gamma -> brightness -> contrast -> saturation) and the dual cut mode,
    // so every DisplayParams field travels as a query param on this path.
    const [survey, band] = hips.split('/')
    const params = new URLSearchParams({
      survey, // e.g. 'allWISE'
      band: band || '', // e.g. 'W4'
      ra: String(ra),
      dec: String(dec),
      size: String(size),
      stretch: display.stretch,
      dither: 'true', // always dither in high mode
      cut_mode: display.cutMode,
      gamma: String(display.gamma),
      brightness: String(display.brightness),
      contrast: String(display.contrast),
      saturation: String(display.saturation),
    })
    // R6.104-K: dual cut mode. percent -> *_cut_pct (server-side percentile of
    // the fetched FITS); absolute -> min_cut_abs / max_cut_abs in [0, 65535].
    if (cuts.percent) {
      // hips.py:184-185 declares min_cut_pct in [0, 49] and max_cut_pct in
      // [51, 100] -- the window must straddle the median -- and FastAPI 422s
      // otherwise. Clamp so a UI value outside that range degrades to the
      // nearest legal window instead of failing the request outright.
      if (!cuts.auto) {
        params.set(
          'min_cut_pct',
          String(Math.max(0, Math.min(49, cuts.minPct ?? 0))),
        )
        params.set(
          'max_cut_pct',
          String(Math.max(51, Math.min(100, cuts.maxPct ?? 100))),
        )
      }
    } else {
      params.set('min_cut_abs', String(cuts.minAbs))
      params.set('max_cut_abs', String(cuts.maxAbs))
    }
    return `/pipeline/hips-float?${params.toString()}`
  }

  // Standard path (R6.27j): direct CDS jpg, fetched by the browser.
  // R6.104-K: CDS hips2fits understands ONLY stretch + min_cut/max_cut.
  // gamma / brightness / contrast / saturation are applied client-side as a
  // CSS filter by useContrastDOM (spec 5.2). Colormap is not representable on
  // this path either -- CDS serves an 8-bit grayscale JPEG.
  const params = new URLSearchParams({
    hips, // e.g. 'DSS2/Blue'
    ra: String(ra),
    dec: String(dec),
    width: String(size),
    height: String(size),
    fov: String(Math.max(0.01, 3 * (size / 400))), // scale fov with size
    stretch: cdsStretchFor(display.stretch),
    format: 'jpg',
  })
  // Absolute cuts are not representable on this path (CDS takes percentiles
  // only), so an absolute cutMode falls back to CDS's own window -- which is
  // what `auto` already expresses.
  if (cuts.percent && !cuts.auto) {
    params.set('min_cut', `${cuts.minPct}%`)
    params.set('max_cut', `${cuts.maxPct}%`)
  }
  return `${HIPS_PROXY_URL}?${params.toString()}`
}

// R6.27i.d: DS9 pixel-level cut + stretch for HiPS cutouts.
//
// DS9's pixel renderer (NOT just CSS) does THREE things to a raw float pixel:
//
//   1. Cut levels (DS9's "bias" + "contrast"):
//        display = clamp((raw - bias) * contrast, 0, 255)
//      Maps a [bias-w/2, bias+w/2] window of raw pixel values to [0, 255].
//      Equivalent to CDS hips2fits pixel_cut_min / pixel_cut_max:
//        display = clamp((raw - pixel_cut_min) / (pixel_cut_max - pixel_cut_min) * 255, 0, 255)
//      Applied to PIXEL DATA on the server, BEFORE 8-bit JPEG quantization.
//      This is what fixes the W4 "blocky" issue — without it, the histogram
//      spans 0-10000+ (zodiacal background) but only 8-bit values exist, so
//      99.95% of pixels round to the same mid-tone value.
//
//   2. Stretch function (DS9's "scale" param):
//        linear: d = p
//        sqrt:   d = sqrt(p)               (gentle, preserves mid-tones)
//        log:    d = log(1 + p)            (aggressive compression)
//        asinh:  d = asinh(p/s) / asinh(s) (smooth low-to-high transition)
//      Applied to raw float pixels BEFORE the cut window. This is the
//      pre-conditioning that makes the histogram spread more evenly across
//      the dynamic range.
//
//   3. Auto-cut (DS9's "auto" button):
//      Default = full dynamic range. We override per-survey to clip the
//      extreme tails (zodiacal background, dead pixels) that consume the
//      8-bit precision without contributing useful sky information.
//
// Per-survey choices:
//
// - allWISE W4 (22µm):
//     stretch = sqrt (gentler than asinh, preserves mid-tones)
//     min_cut = 1.5% (clip bottom 1.5% — pure background noise)
//     max_cut = 99%  (clip top 1% — extreme bright sources)
//     Reason: W4 has zodiacal background ~10x source in faint regions.
//             Without tight top clip, mid-tone pixels round to identical
//             8-bit values → blocky in uniform regions. Empirical:
//             1.5%-99% cut: dark pixels 0.66%→2.25%, std 42→49 (sources
//             become visible against background). Note: JPEG DCT blocks
//             remain — that's a fundamental HiPS-tile limitation.
//
// - 2MASS Ks (2.2µm):
//     stretch = asinh (R6.16: measured 2x sharper than log at 400px)
//     min_cut = 0.5%, max_cut = 99.5% (CDS default — moderate bg handled)
//     Reason: Ks has moderate zodiacal; CDS default percentile is fine.
//
// - DSS2 / SDSS / LEGACY (optical):
//     stretch = linear (low background)
//     cut_min = 0     (optical surveys have well-calibrated zero)
//     cut_max = none  (let CDS auto — full range is informative)
//
// - NVSS (radio 1.4 GHz):
//     stretch = linear
//     cut_min = 0
//     cut_max = none  (radio has no zodiacal; auto is fine)
//
// - AliCPT-1 / Planck (no HiPS):
//     Render from FITS at native resolution; CDS params not applicable.

interface HipsBandProfile {
  stretch: string
  // R6.27j: percentile cuts (0-100). CDS hips2fits `min_cut` / `max_cut`
  // accept either absolute values or `1.5%`-style percentile strings.
  // Empirically validated 2026-09-03: percentile cuts DO change the
  // histogram (1.5%-99% on W4: mean 136→128, std 42→49, dark pixels
  // 0.66%→2.25%); absolute values were over-clipping (0-200 → 4 unique
  // grays — complete saturation).
  cutMinPct?: number
  cutMaxPct?: number
}

const HIPS_PROFILE: Record<string, HipsBandProfile> = {
  // R6.27j: empirical percentile cuts (validated 2026-09-03 via md5 + numpy
  // analysis on W4 at ra=187.5 dec=-12.5):
  //   allWISE W4 (22µm, zodiacal ~10x source in faint regions):
  //     stretch=sqrt + 1.5%-99% percentile (vs CDS default 0.5%-99.5%)
  //     → sources become visible (dark pixels 0.66%→2.25%, std 42→49)
  //   2MASS Ks (2.2µm, moderate zodiacal):
  //     stretch=asinh + 0.5%-99.5% (CDS default — already good for moderate bg)
  //   DSS2/SDSS/LEGACY (optical, well-calibrated, low background):
  //     stretch=linear + no cuts (CDS default handles them perfectly)
  //   NVSS (radio 1.4 GHz, no zodiacal):
  //     stretch=linear + no cuts (radio has uniform noise floor)
  allWISE: { stretch: 'sqrt', cutMinPct: 1.5, cutMaxPct: 99 }, // W4 — tighter top clip reveals faint sources
  '2MASS': { stretch: 'asinh', cutMinPct: 0.5, cutMaxPct: 99.5 }, // Ks — CDS default already good
  DSS2: { stretch: 'linear' }, // optical, low background
  SDSS: { stretch: 'linear' }, // optical
  LEGACY: { stretch: 'linear' }, // optical
  NVSS: { stretch: 'linear' }, // radio, no zodiacal
  // R6.104-K-C: NEW surveys (per user 2026-09-25 brainstorm).
  // Unknown surveys fall back to FALLBACK_DISPLAY_PARAMS (asinh + 3%/99.7%).
  '2MASS-color': { stretch: 'asinh', cutMinPct: 0.5, cutMaxPct: 99.5 }, // same as 2MASS grayscale
  'Gaia-DR3': { stretch: 'log', cutMinPct: 0.1, cutMaxPct: 99.9 }, // Gaia has wide dynamic range
  'NVSS-color': { stretch: 'linear' },
  'Planck-LFI': { stretch: 'asinh', cutMinPct: 1, cutMaxPct: 99 }, // CMB -> asinh
  'Planck-HFI': { stretch: 'asinh', cutMinPct: 1, cutMaxPct: 99 }, // CMB -> asinh
}

// R6.104-K (T16): CDS hips2fits VALIDATES `stretch` and rejects the
// backend-only stretches (pow2, equalization) with HTTP 400 -- even though it
// returns raw FITS regardless. Mirror the backend's resolve_cds_stretch() so
// the direct-CDS path degrades to linear instead of 400ing.
const CDS_STRETCH: Record<StretchType, string> = {
  linear: 'linear',
  sqrt: 'sqrt',
  log: 'log',
  asinh: 'asinh',
  pow2: 'linear',
  equalization: 'linear',
}
function cdsStretchFor(s: StretchType): string {
  return CDS_STRETCH[s] ?? 'linear'
}

// R6.104-K (T16): survey profile -> full DisplayParams. A profile with no
// explicit cuts yields the "no cut" sentinels -- minCut -1 (Auto) and
// maxCut 100 (identity) -- which cutsForDisplay() omits from the URL entirely,
// keeping DSS2 / SDSS / LEGACY / NVSS byte-identical to pre-R6.104-K output.
// A survey with no profile entry gets FALLBACK_DISPLAY_PARAMS
// (R6.104-K-C: asinh + 3% / 99.7%).
function profileDisplayParams(survey: string): DisplayParams {
  const prof = HIPS_PROFILE[survey]
  if (!prof) return FALLBACK_DISPLAY_PARAMS
  return {
    ...DEFAULT_DISPLAY_PARAMS,
    stretch: (prof.stretch as StretchType) || DEFAULT_DISPLAY_PARAMS.stretch,
    minCut: prof.cutMinPct ?? -1,
    maxCut: prof.cutMaxPct ?? 100,
  }
}

// R6.104-K-A (SSOT): resolve the DisplayParams for one band / channel key.
// A user override stored in `displayByBand` wins; otherwise the survey profile.
function displayFor(
  displayByBand: Record<string, DisplayParams> | undefined,
  survey: string,
  key: string,
): DisplayParams {
  return displayByBand?.[key] ?? profileDisplayParams(survey)
}

// R6.104-K (T16): "no explicit window" is the sentinel PAIR
// (minCut === -1 AND maxCut >= 100). It has to be detected as a pair: maxCut
// 100 on its own is a legitimate request for "no top clipping" (and
// min_cut_pct/max_cut_pct both accept the extremes server-side), while
// minCut -1 on its own just means "no bottom clipping".
function isAutoWindow(d: DisplayParams): boolean {
  return d.cutMode === 'percent' && d.minCut === -1 && d.maxCut >= 100
}

// R6.104-K (T16): the tile badge text. Deliberately routed through
// isAutoWindow() rather than a local `maxCut >= 100` test so the badge reports
// exactly what the URL builders will send.
function displayCutLabel(d: DisplayParams | null): string {
  if (!d) return ''
  if (d.cutMode === 'absolute') return `${d.minCut}-${d.maxCut}`
  if (isAutoWindow(d)) return 'Auto'
  const lo = d.minCut === -1 ? 'Auto' : d.minCut
  const hi = d.maxCut >= 100 ? 'Auto' : `${d.maxCut}%`
  return `${lo}-${hi}`
}

// R6.104-K (T16): DisplayParams -> concrete cut values for one render request.
//   percent, auto     -- let the renderer pick its own percentile window.
//   percent, explicit -- percentile bounds; minCut -1 (no bottom clipping) is
//                        expressed as percentile 0, its explicit equivalent.
//   absolute          -- raw pixel bounds in [0, 65535], forwarded as-is.
interface DisplayCuts {
  percent: boolean
  auto?: boolean
  minPct?: number
  maxPct?: number
  minAbs?: number
  maxAbs?: number
}
function cutsForDisplay(d: DisplayParams): DisplayCuts {
  if (d.cutMode === 'absolute') {
    return { percent: false, minAbs: d.minCut, maxAbs: d.maxCut }
  }
  if (isAutoWindow(d)) return { percent: true, auto: true }
  return {
    percent: true,
    minPct: d.minCut === -1 ? 0 : d.minCut,
    maxPct: d.maxCut,
  }
}

// R6.27j: REAL DS9 fix. Use correct CDS parameter names `min_cut`/`max_cut`
// with percentile values. See hipsCutoutUrlImpl for empirical md5 proof that
// the previous `pixel_cut_min`/`pixel_cut_max` was silently ignored by CDS.
function hipsCutoutUrl(
  hips: string,
  ra: number,
  dec: number,
  size: number,
  display: DisplayParams,
  quality: 'standard' | 'high' = 'standard',
): string {
  return hipsCutoutUrlImpl(hips, ra, dec, size, display, quality)
}

// R6.104-K (T16): DisplayParams -> per-channel percentile cuts for the backend
// /pipeline/merge-rgb HiPS mode (r_q_low / r_q_high / ...). Replaces the R6.29c
// scalar-slider shift; the percentile values are now explicit.
//   percent  -- -1 (Auto) and >= 100 fall back to the survey defaults.
//   absolute -- merge-rgb takes ONE global min_cut_abs / max_cut_abs pair, not
//               one per channel, so per-channel absolute cuts are not
//               representable; fall back to the survey percentile defaults.
function contrastToCuts(
  display: DisplayParams,
  defaultLow: number,
  defaultHigh: number,
): { qLow: number; qHigh: number } {
  // absolute: merge-rgb takes ONE global min_cut_abs / max_cut_abs pair rather
  // than one per channel, so a per-channel absolute cut is not representable.
  // auto: no explicit window -> let the survey defaults stand.
  if (display.cutMode === 'absolute' || isAutoWindow(display)) {
    return { qLow: defaultLow, qHigh: defaultHigh }
  }
  // The per-channel r_q_low/g_q_low/... overrides carry no ge/le in
  // server.py:1401-1406 (only their fallback q_low is bounded), so these
  // values pass through unclamped.
  return {
    qLow: display.minCut === -1 ? defaultLow : display.minCut,
    qHigh: display.maxCut,
  }
}

// R6.29c: extract per-band HiPS channel name from a HiPS string like 'allWISE/W4' -> 'W4'
function hipsBandName(hipsId: string): string {
  return hipsId.split('/')[1] || ''
}

// R6.29f: extract HiPS id for an entry (for Hi-Q badge display)
function hipsIdForEntry(e: OrderedEntry): string {
  if (e.kind === 'rgb') return e.hipsColor || ''
  if (e.kind === 'band') return getHipsId(e.survey, e.item.band || '') || ''
  return ''
}

// R6.2 lean + R6.6 HiPS-preferred + R6.7a per-survey stretch:
// thumb URL is a pure function.
// R6.61.b: shared factory function. Pure function of (entry, size, coords,
// displayByBand, quality) → URL. thumbUrl and largeImageUrl are thin wrappers
// that pick the size. This guarantees thumb and big URLs differ ONLY in the
// size param when all other inputs match (testable invariant).
//
// Logic mirrors R6.6/R6.16/R6.28/R6.29c/R6.30:
//   - RGB + hipsColor + ra/dec: merge-rgb (if quality=='high' AND rgbChannels) else hipsCutoutUrl
//   - RGB without hipsColor: substitute size param in e.url (R6.16 stitching)
//   - Band + ra/dec + getHipsId: hipsCutoutUrl (HiPS path)
//   - Band without HiPS: /pipeline/thumbnail (FITS path), or img_path fallback
//
// Per-tile quality is the caller's responsibility: thumbUrl passes caller
// quality (forceStd per-tile), largeImageUrl passes getHipsQuality for RGB HiPS.
//
// R6.61.b: exported for vitest consistency testing.
export function buildImageUrl(
  e: OrderedEntry,
  size: number,
  ra?: number,
  dec?: number,
  displayByBand?: Record<string, DisplayParams>,
  quality: 'standard' | 'high' = 'standard',
): string {
  // R6.27i.d: per-survey DS9 pixel-level profile (stretch + cut).
  // R6.104-K (T16): the profile is now only the DEFAULT -- a user override
  // stored in displayByBand wins (see displayFor / profileDisplayParams).
  const profile = HIPS_PROFILE[e.survey] || { stretch: 'asinh' }

  if (e.kind === 'rgb') {
    // R6.16: HiPS-color RGB (e.g. 2MASS) uses HiPS cutout for thumbnail.
    if (e.hipsColor && ra !== undefined && dec !== undefined) {
      // R6.28: per-channel Hi-Q routing. When quality=='high' AND rgbChannels,
      // route to backend /pipeline/merge-rgb?mode=hips for FITS-based rendering.
      if (quality === 'high' && e.rgbChannels) {
        // R6.104-K: per-channel DisplayParams drive the cuts (replacing the
        // R6.29c scalar slider -> contrastToCuts shift).
        const rD = displayFor(
          displayByBand,
          e.survey,
          hipsBandName(e.rgbChannels.r),
        )
        const gD = displayFor(
          displayByBand,
          e.survey,
          hipsBandName(e.rgbChannels.g),
        )
        const bD = displayFor(
          displayByBand,
          e.survey,
          hipsBandName(e.rgbChannels.b),
        )
        const defaultLow = profile.cutMinPct ?? 0.5
        const defaultHigh = profile.cutMaxPct ?? 99.5
        const rCuts = contrastToCuts(rD, defaultLow, defaultHigh)
        const gCuts = contrastToCuts(gD, defaultLow, defaultHigh)
        const bCuts = contrastToCuts(bD, defaultLow, defaultHigh)
        const params = new URLSearchParams({
          mode: 'hips',
          r_hips: e.rgbChannels.r,
          g_hips: e.rgbChannels.g,
          b_hips: e.rgbChannels.b,
          ra: String(ra),
          dec: String(dec),
          size: String(size),
          r_stretch: rD.stretch,
          g_stretch: gD.stretch,
          b_stretch: bD.stretch,
          r_q_low: String(rCuts.qLow),
          g_q_low: String(gCuts.qLow),
          b_q_low: String(bCuts.qLow),
          r_q_high: String(rCuts.qHigh),
          g_q_high: String(gCuts.qHigh),
          b_q_high: String(bCuts.qHigh),
        })
        return '/pipeline/merge-rgb?' + params.toString()
      }
      return hipsCutoutUrl(
        e.hipsColor,
        ra,
        dec,
        size,
        displayFor(displayByBand, e.survey, e.hipsColor),
        quality,
      )
    }
    // RGB non-HiPS-color: /pipeline/merge-rgb?size=N -> substitute with our size.
    const base = getImageUrl(e.url)
    return base.replace(/size=\d+/, `size=${size}`)
  }
  if (ra !== undefined && dec !== undefined && e.kind === 'band') {
    const hips = getHipsId(e.survey, e.item.band || '')
    if (hips) {
      return hipsCutoutUrl(
        hips,
        ra,
        dec,
        size,
        displayFor(displayByBand, e.survey, e.item.band || ''),
        quality,
      )
    }
  }
  if (e.item.img_path) return getImageUrl(e.item.img_path)
  const fp = e.item.fits_path || e.item.fits_db_path || ''
  const fn = fp.replace('/static-files/fits/', '')
  return getImageUrl(
    `/pipeline/thumbnail?filename=${encodeURIComponent(fn)}&size=${size}`,
  )
}

// R6.61.b: thin wrapper — picks size (400 for HiPS, THUMB=100 for FITS fallback)
// then delegates to buildImageUrl. The factory guarantees thumb/big URLs differ
// ONLY in the size param (verified by vitest test).
function thumbUrl(
  e: OrderedEntry,
  ra?: number,
  dec?: number,
  displayByBand?: Record<string, DisplayParams>,
  quality: 'standard' | 'high' = 'standard',
): string {
  const hipsBased =
    (e.kind === 'rgb' && !!e.hipsColor) ||
    (e.kind === 'band' && !!getHipsId(e.survey, e.item.band || ''))
  const size = hipsBased ? THUMB_HIPS_SIZE : THUMB
  return buildImageUrl(e, size, ra, dec, displayByBand, quality)
}

// R6.16: per-survey LARGE_SIZE. Each survey has its own sweet spot:
//   - 2MASS HiPS: 600px (asinh) — measured sharpness 13394, 2x better than 400px
//   - DSS2/SDSS/allWISE/NVSS HiPS: 400px — diminishing returns past 400, more bytes
//   - AliCPT-1 FITS: 150px — native source is 15x15 pixels, 400px is 26.7x
//     upscale blur (sharpness 375 vs 150's native render)
//   - Planck FITS: 400px (default)
//
// R6.15 cache-hit prewarm strategy preserved: each survey's big URL is
// prewarmed in parallel via the useEffect, browser cache serves it in <10ms.
const LARGE_SIZE_BY_SURVEY: Record<string, number> = {
  '2MASS': 600, // HiPS asinh, measured best at 600
  DSS2: 400,
  SDSS: 400,
  allWISE: 400,
  LEGACY: 400,
  NVSS: 400,
  'AliCPT-1': 150, // native 15x15 FITS, no benefit rendering bigger
  Planck: 400,
}
const LARGE_SIZE_DEFAULT = 400
// R6.61.b: thin wrapper — uses per-survey LARGE_SIZE. RGB HiPS uses
// per-survey getHipsQuality (R6.28 design); band/HiPS uses caller quality.
// Delegates to buildImageUrl for the actual URL construction.
function largeImageUrl(
  e: OrderedEntry,
  ra?: number,
  dec?: number,
  displayByBand?: Record<string, DisplayParams>,
  quality: 'standard' | 'high' = 'standard',
): string {
  const size = LARGE_SIZE_BY_SURVEY[e.survey] || LARGE_SIZE_DEFAULT
  // R6.28: RGB HiPS uses per-survey Hi-Q (e.g. 2MASS=high); otherwise caller quality.
  const q =
    e.kind === 'rgb' && e.hipsColor ? getHipsQuality(e.hipsColor) : quality
  return buildImageUrl(e, size, ra, dec, displayByBand, q)
}

// R6.27k: Image quality toggle. Two-state pill button.
// 'standard' = fast jpg (default, ~30KB per tile, 8-bit pre-quantized)
// 'high'     = FITS+PNG with dithering (~175KB per tile, float precision)
// Trade-off: 5.8x volume for true DS9-like rendering (no banding, no JPEG DCT).
function QualityToggle({
  quality,
  onChange,
}: {
  quality: 'standard' | 'high'
  onChange: (q: 'standard' | 'high') => void
}) {
  // Compute classNames outside JSX to avoid template-literal-in-attribute parsing issues.
  const stdCls =
    quality === 'standard'
      ? 'bg-blue-500/40 text-white'
      : 'bg-transparent text-white/60 hover:bg-white/5'
  const hiCls =
    quality === 'high'
      ? 'bg-blue-500/40 text-white'
      : 'bg-transparent text-white/60 hover:bg-white/5'
  return (
    <div
      className='flex items-center gap-1 text-xs shrink-0'
      title='R6.27k: high-quality mode routes through /pipeline/hips-float (raw FITS + Floyd-Steinberg dither, ~175KB PNG vs ~30KB JPG)'
    >
      <span className='text-white/50 hidden sm:inline'>Quality:</span>
      <div className='flex rounded overflow-hidden border border-white/20'>
        <button
          type='button'
          onClick={() => onChange('standard')}
          className={'px-2 py-0.5 whitespace-nowrap ' + stdCls}
        >
          Std
        </button>
        <button
          type='button'
          onClick={() => onChange('high')}
          className={'px-2 py-0.5 whitespace-nowrap ' + hiCls}
        >
          Hi-Q
        </button>
      </div>
    </div>
  )
}

function MultiBandDataPanel({ ra, dec, uuid }: Props) {
  const { data } = useRequest(
    () => getGravitationalWave({ ra: ra!, dec: dec!, uuid: uuid }),
    {
      ready: ra !== undefined && dec !== undefined,
      refreshDeps: [ra, dec, uuid],
      cacheKey: `mbp-${ra}-${dec}-${uuid || ''}`,
      staleTime: 60_000,
    },
  )
  const entries = useMemo(
    () => buildOrderedEntries(data?.data?.list || []),
    [data?.data?.list],
  )
  const [selected, setSelected] = useState<number[]>([0])
  const [rgbIndex, setRgbIndex] = useState<number | null>(null)
  const [viewerType, setViewerType] = useState<ViewerType>('aladin')
  // R6.99-A: Firefly lazy mount — true on first user click of Firefly
  // tab. Reverts R6.19 always-mount pattern (eliminated WASM init
  // jank on every observation change).
  const [fireflyMounted, setFireflyMounted] = useState(false)
  // R6.99-A: responsive breakpoints drive THUMB + viewer heights.
  const bp = Grid.useBreakpoint()
  const thumbSize = bp.xs ? 70 : bp.sm ? 90 : 100
  const viewerMinHeight = bp.xs ? 280 : bp.sm ? 340 : 420
  const thumbStripMaxHeight = bp.xs ? 130 : bp.md ? 170 : 200
  // R6.3: track tiles whose <img> failed to load (broken PNG like NVSS 15x15 placeholder)
  const [loadError, setLoadError] = useState<Set<number>>(new Set())
  // R6.29f: track tiles currently loading (img in flight, not yet loaded)
  const [imgLoading, setImgLoading] = useState<Set<number>>(new Set())
  // R6.30: per-tile Std override. User clicks Hi-Q badge to force Std mode
  // for a specific tile (e.g. when Hi-Q returns noise for faint data).
  // Session-only (not persisted).
  const [forceStdTiles, setForceStdTiles] = useState<Set<number>>(new Set())
  // Toggle Std/Hi-Q for a specific tile. Called when user clicks Hi-Q badge.
  const toggleTileQuality = (idx: number) => {
    setForceStdTiles((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }
  // Compute quality for a specific entry (incorporates per-tile override).
  // R6.32: also auto-Hi-Q for RGB composites whose all channels are in AUTO_HI_Q.
  const qualityForEntry = (
    entry: OrderedEntry,
    idx: number,
  ): 'standard' | 'high' => {
    if (forceStdTiles.has(idx)) return 'standard'
    // RGB composite: check if all channels are in AUTO_HI_Q
    if (entry.kind === 'rgb' && autoHiQRgb(entry)) return 'high'
    // Single band: standard AUTO_HI_Q check
    const hipsId = hipsIdForEntry(entry)
    if (hipsId) return getHipsQuality(hipsId)
    return _currentQuality
  }
  // R6.34: RGB composite re-render state tracking.
  // - rgbIsAdjusting: any component band has non-zero slider (user is adjusting)
  // - rgbIsRerendering: actively loading new image (img in flight)
  // These are different states; show different visual feedback for each.
  const rgbIsAdjusting = (entry: OrderedEntry): boolean => {
    if (entry.kind !== 'rgb' || !entry.rgbChannels) return false
    const bands = [
      hipsBandName(entry.rgbChannels.r),
      hipsBandName(entry.rgbChannels.g),
      hipsBandName(entry.rgbChannels.b),
    ]
    return bands.some((b) => {
      if (!b) return false
      // R6.104-K: a channel counts as "being adjusted" once it has a stored
      // DisplayParams override at all. The R6.27g version compared the scalar
      // slider against 0; every non-default override is now meaningful, so
      // the mere presence of an entry is the signal.
      return bandDisplay[b] !== undefined
    })
  }
  // Active re-render = component band being adjusted AND img in flight
  const rgbIsRerendering = (entry: OrderedEntry, idx: number): boolean => {
    if (entry.kind !== 'rgb') return false
    return rgbIsAdjusting(entry) && imgLoading.has(idx)
  }

  // R6.104-K (T16): per-band DisplayParams replace the R6.27g scalar contrast.
  // Key = band name (e.g. 'W4'). An absent key means "use the survey profile
  // default" (profileDisplayParams), so nothing is stored until the user
  // actually tunes that band. Persisted in localStorage.
  const [bandDisplay, setBandDisplay] = useState<Record<string, DisplayParams>>(
    () => {
      try {
        const raw = localStorage.getItem('gw-band-display')
        if (raw) return JSON.parse(raw)
        // R6.104-K migration: seed from the R6.27g scalar slider (-100..100) so
        // a session that already tuned contrast keeps those values on upgrade.
        const legacy = localStorage.getItem('gw-thumb-contrast')
        if (!legacy) return {}
        const scalars: Record<string, number> = JSON.parse(legacy)
        const seeded: Record<string, DisplayParams> = {}
        for (const band of Object.keys(scalars)) {
          const v = scalars[band]
          seeded[band] = clampDisplayParams({
            contrast: 1 + v / 100,
            brightness: v / 200,
          })
        }
        return seeded
      } catch {
        return {}
      }
    },
  )

  // R6.27k: image-quality toggle. 'standard' = fast jpg (default).
  //          'high' = backend FITS+PNG with dithering (5.8x volume,
  //                   float-precision cuts, no JPEG DCT blocks).
  // Persisted in localStorage so user preference survives reload.
  const [quality, setQuality] = useState<'standard' | 'high'>(() => {
    try {
      const raw = localStorage.getItem('gw-hips-quality')
      return raw === 'high' ? 'high' : 'standard'
    } catch {
      return 'standard'
    }
  })
  const updateQuality = (q: 'standard' | 'high') => {
    setQuality(q)
    try {
      localStorage.setItem('gw-hips-quality', q)
    } catch {
      // localStorage may throw (private mode, quota); silent ignore
    }
  }

  // R6.27k: sync component state -> module variable so top-level helpers (thumbUrl, largeImageUrl)
  // can read it without React re-render cascade.
  useEffect(() => {
    setHipsQuality(quality)
  }, [quality])
  // R6.104-K (T16): write one band's DisplayParams and persist the whole map.
  // The CSS-only axes (contrast / brightness / saturation) are ALSO pushed to
  // the DOM synchronously by the caller via contrastDOM.setDisplay, preserving
  // R6.27i's ms-level response; this React update is what rebuilds the URL for
  // the server-rendered axes (stretch / cuts / Hi-Q gamma).
  const setDisplayForBand = (band: string, next: DisplayParams) => {
    setBandDisplay((prev) => {
      const merged = { ...prev, [band]: next }
      try {
        localStorage.setItem('gw-band-display', JSON.stringify(merged))
      } catch {
        // localStorage may throw (private mode, quota); silent ignore
      }
      return merged
    })
  }

  // R6.27i: direct-DOM contrast updates. Control drag goes here — it mutates
  // img.style.filter directly, bypassing React. The React state write
  // (setDisplayForBand) runs in parallel for localStorage persistence and for
  // the server-rendered axes (stretch / cuts / Hi-Q gamma), which live in the
  // URL and therefore DO need a re-render. Visual update of the CSS axes stays
  // decoupled from React reconciliation.
  const contrastDOM = useContrastDOM()

  // R6.9b: filter out tiles whose thumbnail failed to load (broken image).
  // R6.31: restored — user prefers silent filter over visible 'No data' tile.
  const visibleEntries = useMemo(() => {
    if (loadError.size === 0) return entries
    return entries.filter((_, idx) => !loadError.has(idx))
  }, [entries, loadError])

  // R6.18: Splash-synchronized preload. Replaces R6.4 fire-and-forget.
  // User feedback: "在splash期间就把所有内容都准备好, 等用户切换时直接命中缓存".
  // Strategy: on entries change, parallel preloads for thumbnails + big
  // images + FITS files. Show overlay splash with live progress. After all
  // loaded (or 8s timeout), fade splash + render content instantly from cache.
  // Children (Firefly/Aladin) all read cached URLs — zero latency switches.
  const [preloadDone, setPreloadDone] = useState(false)
  const [preloadProgress, setPreloadProgress] = useState({
    thumbnailsDone: 0,
    thumbnailsTotal: 0,
    bigImagesDone: 0,
    bigImagesTotal: 0,
    fitsDone: 0,
    fitsTotal: 0,
  })
  const preloadIdRef = useRef(0)

  useEffect(() => {
    setSelected([0])
    setRgbIndex(null)
    setViewerType('aladin')
    setLoadError(new Set())
    setImgLoading(new Set(entries.map((_, i) => i))) // R6.29f: all tiles start loading
    if (typeof window === 'undefined') return
    if (entries.length === 0) {
      setPreloadDone(true)
      return
    }
    setPreloadDone(false)
    const myId = ++preloadIdRef.current

    const thumbUrls = entries.map((e) => thumbUrl(e, ra, dec))
    const bigUrls = entries.map((e) => largeImageUrl(e, ra, dec))
    const fitsUrls = entries
      .filter((e) => e.kind === 'band')
      .map((e) => getFitsUrl(e.item.fits_path || e.item.fits_db_path))
      .filter(Boolean)

    setPreloadProgress({
      thumbnailsDone: 0,
      thumbnailsTotal: thumbUrls.length,
      bigImagesDone: 0,
      bigImagesTotal: bigUrls.length,
      fitsDone: 0,
      fitsTotal: fitsUrls.length,
    })

    const tick =
      (key: 'thumbnailsDone' | 'bigImagesDone' | 'fitsDone') => (d: number) => {
        if (preloadIdRef.current !== myId) return
        setPreloadProgress((p) => ({ ...p, [key]: d }))
      }

    Promise.all([
      preloadImages(thumbUrls, tick('thumbnailsDone')),
      preloadImages(bigUrls, tick('bigImagesDone')),
      preloadFits(fitsUrls, tick('fitsDone')),
    ]).then(() => {
      if (preloadIdRef.current === myId) setPreloadDone(true)
    })
  }, [ra, dec, uuid, entries])

  const toggle = (idx: number, multi: boolean) => {
    const entry = entries[idx]
    if (entry.kind === 'rgb') {
      setRgbIndex((prev) => (prev === idx ? null : idx))
      setSelected([])
      return
    }
    setRgbIndex(null)
    if (multi) {
      setSelected((prev) =>
        prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx],
      )
    } else {
      setSelected([idx])
    }
  }

  // R6.13: compute the big-viewer image URL the same way as thumbUrl().
  // Source priority (matches thumbUrl):
  //   1. RGB composite click -> the merge-rgb URL at LARGE_SIZE
  //   2. Single-band click with HiPS -> hipsCutoutUrl (no rotation, no stretch drift)
  //   3. Single-band click without HiPS (AliCPT, Planck) -> /pipeline/thumbnail at LARGE_SIZE
  //   4. Multi-select (composite) -> use first selected band's largeImageUrl
  // This makes the big viewer consistent with the thumbnail for every band
  // type and gives bands without FITS (DSS2 RGB, allWISE RGB, LEGACY RGB) a
  // big image too.
  const imageUrl = useMemo(() => {
    if (rgbIndex !== null) {
      const e = entries[rgbIndex]
      // R6.104-K: pass bandDisplay so the big viewer re-renders when a band's
      // DisplayParams change (server-rendered axes land in the URL).
      // R6.30: pass per-tile quality (respects forceStdTiles for big viewer)
      if (e && e.kind === 'rgb')
        return largeImageUrl(
          e,
          ra,
          dec,
          bandDisplay,
          qualityForEntry(e, rgbIndex),
        )
    }
    if (selected.length >= 1) {
      const e = entries[selected[0]]
      if (e)
        return largeImageUrl(
          e,
          ra,
          dec,
          bandDisplay,
          qualityForEntry(e, selected[0]),
        )
    }
    return ''
    // R6.57: qualityForEntry closes over forceStdTiles + _currentQuality
    // which are already tracked via deps; adding qualityForEntry as a
    // dep would re-memo every render. Mark as intentionally omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rgbIndex, selected, entries, ra, dec, bandDisplay])

  // R6.27i: resolve the active band name (the band whose thumbnail is
  // currently shown in the big viewer). For RGB composites or no selection,
  // there is no per-band contrast.
  const currentBand = useMemo<string | null>(() => {
    if (rgbIndex !== null) return null // RGB composite — no per-band contrast
    if (selected.length === 1) {
      const e = entries[selected[0]]
      if (e && e.kind === 'band') return e.item.band
    }
    return null
  }, [rgbIndex, selected, entries])

  // R6.104-K (T16): the active band's DisplayParams -- user override, else the
  // survey profile default. currentBand is null for RGB composites and
  // empty selections, so those fall back to the identity defaults.
  const currentDisplay = useMemo<DisplayParams>(() => {
    if (!currentBand) return DEFAULT_DISPLAY_PARAMS
    const e = selected.length === 1 ? entries[selected[0]] : undefined
    return e
      ? displayFor(bandDisplay, e.survey, currentBand)
      : DEFAULT_DISPLAY_PARAMS
  }, [currentBand, bandDisplay, entries, selected])

  // R6.104-K review: does the big image come from the server-rendered Hi-Q
  // path? If so the four coefficients are already baked into that PNG and
  // the CSS filter must not re-apply them. Mirrors the quality choice in the
  // largeImageUrl memo above (only a single selected band has per-band
  // contrast -- currentBand is null for an RGB composite).
  const activeIsHiQ = useMemo<boolean>(() => {
    if (currentBand === null || selected.length < 1) return false
    const e = entries[selected[0]]
    return e ? qualityForEntry(e, selected[0]) === 'high' : false
    // R6.57: qualityForEntry closes over forceStdTiles + _currentQuality.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentBand, selected, entries])

  // R6.27i: sync the hook's activeBandRef whenever currentBand changes so
  // subsequent setDisplay calls only target the right image. We also
  // re-apply the band's DisplayParams here so the big image inherits the
  // latest state after a band switch (otherwise the new image would show
  // without the filter until the user touches a control again).
  //
  // Note: `contrastDOM` is intentionally NOT in the deps array -- it's a
  // new object every render (literal returned from useContrastDOM), so
  // including it would re-fire this effect on every render. The hook's
  // internal refs/callbacks are stable, so we can use them via a ref.
  const contrastDOMRef = useRef(contrastDOM)
  contrastDOMRef.current = contrastDOM
  useEffect(() => {
    const dom = contrastDOMRef.current
    dom.setActiveBand(currentBand)
    // R6.104-K review: tell the hook which mechanism owns the four
    // coefficients for this image BEFORE writing its filter.
    dom.setActiveServerApplied(activeIsHiQ)
    if (currentBand) {
      dom.setDisplay(currentBand, currentDisplay)
    } else {
      // No band (RGB composite) -- clear any leftover filter on the big image.
      const big = dom.bigImgRef.current
      if (big) big.style.removeProperty('filter')
    }
  }, [currentBand, currentDisplay, activeIsHiQ])

  // R6.13: alt text for the big image — descriptive per entry.
  const imageAlt = useMemo(() => {
    if (rgbIndex !== null) {
      const e = entries[rgbIndex]
      return e?.kind === 'rgb' ? `${e.label} composite` : 'Multi-band preview'
    }
    if (selected.length === 1) {
      const e = entries[selected[0]]
      if (e?.kind === 'band') {
        const info = BAND_INFO[e.item.band]
        return info ? `${info.name} (${info.lambda})` : e.item.band
      }
    }
    return 'Multi-band preview'
  }, [rgbIndex, selected, entries])

  // R6.13: still expose fits array for FireflyViewer (multi-FITS overlay).
  const fits = useMemo(
    () =>
      selected
        .map((i) => entries[i])
        .filter(
          (e): e is OrderedEntry & { kind: 'band' } => !!e && e.kind === 'band',
        )
        .map((e) => getFitsUrl(e.item.fits_path || e.item.fits_db_path))
        .filter(Boolean) as string[],
    [selected, entries],
  )

  const noObs = ra === undefined || dec === undefined
  // R6.5: noData removed — image mode now handles 'no FITS' case by showing
  // the thumbnail (img_path) or the HiPS cutout, so no separate Empty branch
  // is needed for HiPS-only entries (DSS2/2MASS/NVSS/allWISE/LEGACY).

  const total =
    preloadProgress.thumbnailsTotal +
    preloadProgress.bigImagesTotal +
    preloadProgress.fitsTotal
  const done =
    preloadProgress.thumbnailsDone +
    preloadProgress.bigImagesDone +
    preloadProgress.fitsDone

  return (
    <div
      className='w-full h-full flex flex-col overflow-hidden relative'
      style={{ background: 'rgba(255,255,255,0.02)' }}
    >
      {/* R6.29e: contrast help banner — always visible, top of panel, can't be missed.
          Without this hint users think contrast slider is just CSS brightness
          and don't know it re-renders RGB composites via per-channel cut. */}
      {!noObs && (
        <div
          className='flex items-center gap-2 px-4 pt-2 pb-1 text-[10px] text-white/55 shrink-0'
          style={{
            background: 'rgba(0,240,255,0.04)',
            borderBottom: '1px solid rgba(0,240,255,0.10)',
          }}
        >
          <QuestionCircleOutlined style={{ color: '#00F0FF' }} />
          <span>
            <b style={{ color: '#00F0FF' }}>cut % slider</b>: hover an IR band
            tile (W1/W2/W3/W4 + J/H/K). 0 = identity. Positive tightens
            percentile (more contrast). Negative loosens (less). Affects band
            thumb + any RGB composite containing it.
          </span>
        </div>
      )}
      <PreloadSplash
        visible={!preloadDone}
        total={total}
        done={done}
        thumbnailsDone={preloadProgress.thumbnailsDone}
        thumbnailsTotal={preloadProgress.thumbnailsTotal}
        bigImagesDone={preloadProgress.bigImagesDone}
        bigImagesTotal={preloadProgress.bigImagesTotal}
        fitsDone={preloadProgress.fitsDone}
        fitsTotal={preloadProgress.fitsTotal}
        hint='Caching thumbnails, big images, and FITS files for instant switching'
      />
      <div
        className='flex items-center justify-between px-4 pt-4 gap-2 min-w-0'
        style={{ position: 'relative', zIndex: 10 }}
      >
        <h2
          className='text-base font-bold text-white/85 whitespace-nowrap min-w-0 truncate flex-1'
          title={`Multi-band Observation Data FITS Viewer (${entries.length})`}
        >
          Multi-band Observation ({entries.length})
        </h2>
        <Segmented
          size='small'
          options={[
            { label: 'Aladin', value: 'aladin' },
            { label: 'Firefly', value: 'firefly' },
          ]}
          value={viewerType}
          onChange={(v) => {
            setViewerType(v as ViewerType)
            if (v === 'firefly') setFireflyMounted(true)
          }}
        />
        <QualityToggle quality={quality} onChange={updateQuality} />
      </div>
      <div
        className='px-4 pt-1 text-[10px] text-white/40 flex items-center gap-3 flex-wrap'
        style={{ position: 'relative', zIndex: 10 }}
      >
        <span>
          {quality === 'high'
            ? 'Hi-Q mode: backend reads raw FITS + Floyd-Steinberg dither (~175KB/tile, no banding, no JPEG blocks)'
            : 'Std mode: direct CDS jpg (~30KB/tile, fast)'}
        </span>
        {/* R6.30: progress count - shows N total, X loaded, Y still loading, Z failed */}
        {entries.length > 0 &&
          (() => {
            const total = entries.length
            const stillLoading = imgLoading.size
            const failed = loadError.size
            const loaded = total - stillLoading - failed
            return (
              <span
                style={{
                  color:
                    failed > 0
                      ? '#FF3B30'
                      : stillLoading > 0
                        ? '#FFB800'
                        : '#00E676',
                  fontWeight: 600,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {loaded}/{total} loaded{failed > 0 ? ` · ${failed} failed` : ''}
                {stillLoading > 0 ? ` · ${stillLoading} loading` : ''}
              </span>
            )
          })()}
      </div>
      {/* R6.99-A: viewport-aware minHeight. */}
      <div
        className='flex-1 min-h-0 overflow-hidden'
        style={{ position: 'relative', minHeight: viewerMinHeight, zIndex: 1 }}
      >
        {noObs ? (
          <div className='h-full flex items-center justify-center'>
            <Empty description='Select an error report to view observation data' />
          </div>
        ) : (
          <>
            {/* R6.19: Aladin always mounted (cheap — just <img>) */}
            <div
              style={{
                position: 'absolute',
                inset: 0,
                height: '100%',
                visibility: viewerType === 'aladin' ? 'visible' : 'hidden',
                pointerEvents: viewerType === 'aladin' ? 'auto' : 'none',
              }}
            >
              {/* R6.104-K (T15): active big image is now click-to-load
                  (lazy) — partial revert of R6.99-A eager-load. Once
                  revealed, eager decode still applies for snappy paint. */}
              <Aladin
                imageUrl={imageUrl}
                alt={imageAlt}
                imgRef={contrastDOM.registerBig}
                eager
                lazy
              />
              {/* R6.104-K (T16): DisplayControls for the active big image.
                  Only meaningful for a single-band selection (currentBand);
                  RGB composites and empty selections have no per-band params. */}
              {currentBand && (
                <div
                  style={{ position: 'absolute', top: 8, right: 8, zIndex: 4 }}
                >
                  <Popover
                    trigger='click'
                    placement='bottomRight'
                    title={`Display — ${currentBand}`}
                    content={
                      <div style={{ width: 460 }}>
                        <DisplayControls
                          compact
                          showColor={false}
                          value={currentDisplay}
                          onChange={(next) => {
                            // Instant (CSS axes) + persisted / URL-rebuilding.
                            contrastDOM.setDisplay(currentBand, next)
                            setDisplayForBand(currentBand, next)
                          }}
                        />
                      </div>
                    }
                  >
                    <button
                      type='button'
                      title='Stretch / cuts / gamma for the active band'
                      style={{
                        background: 'rgba(0,0,0,0.72)',
                        border: '1px solid rgba(0,240,255,0.35)',
                        borderRadius: 4,
                        color: 'rgba(255,255,255,0.85)',
                        fontSize: 11,
                        lineHeight: 1.6,
                        padding: '2px 8px',
                        cursor: 'pointer',
                      }}
                    >
                      Display
                    </button>
                  </Popover>
                </div>
              )}
            </div>
            {/* R6.19: Firefly always mounted (pre-mounts iframe during splash so
                firefly.js + first FITS parsed by the time user clicks Firefly tab) */}
            <div
              style={{
                position: 'absolute',
                inset: 0,
                height: '100%',
                visibility: viewerType === 'firefly' ? 'visible' : 'hidden',
                pointerEvents: viewerType === 'firefly' ? 'auto' : 'none',
              }}
            >
              <FireflyViewer fits={fits} mount={fireflyMounted} />
            </div>
          </>
        )}
      </div>
      {/* R6.99-A: viewport-aware thumb strip height. */}
      {!noObs && (
        <div
          className='mbp-thumb-strip flex gap-2 overflow-x-auto overflow-y-hidden flex-shrink-0 py-2'
          style={{ maxHeight: thumbStripMaxHeight }}
        >
          {visibleEntries.map((entry, _visibleIdx) => {
            // R6.9b: map visible index back to original entries index for loadError
            const idx = entries.indexOf(entry)

            const isBand = entry.kind === 'band'
            const isSel = isBand ? selected.includes(idx) : rgbIndex === idx
            const info = isBand ? BAND_INFO[entry.item.band] : null
            const label = isBand ? info?.name || entry.item.band : entry.label
            // R6.27g: strip 'Far-IR' / 'Mid-IR' / 'Near-IR' spectral-region prefix.
            // User requested: only show the wavelength, e.g. '22 µm'.
            const sub = isBand ? info?.lambda || '' : 'RGB composite'
            // R6.104-K (T16): per-band DisplayParams replace the R6.27g scalar
            // slider, and apply to EVERY band (the old slider was limited to
            // Far/Mid/Near-IR). The CSS-only axes are mirrored onto the <img>
            // inline style so React and useContrastDOM's direct-DOM writer
            // agree; the server-rendered axes (stretch / cuts / Hi-Q gamma)
            // reach the renderer through thumbUrl below.
            const tileDisplay: DisplayParams | null = isBand
              ? (bandDisplay[entry.item.band] ??
                profileDisplayParams(entry.survey))
              : null
            const entryQuality = qualityForEntry(entry, idx)
            // R6.104-K review (BLOCKER): the Hi-Q path sends the four
            // coefficients to the server, which bakes them into the PNG, so
            // the CSS filter must stay out of it -- otherwise they apply
            // twice and contrast/saturation square (contrast 2.0 -> ~4.0).
            const tileFilter =
              tileDisplay && entryQuality !== 'high'
                ? contrastDOM.compute(tileDisplay) || 'none'
                : 'none'
            const cutLabel = displayCutLabel(tileDisplay)
            const tip = isBand
              ? `${label} (${info?.lambda || '—'})\nCtrl/Cmd-click for multi-select`
              : `${label} — click to view RGB composite`
            return (
              <Tooltip key={idx} title={tip} placement='top'>
                <div
                  role='button'
                  tabIndex={0}
                  aria-pressed={isSel}
                  aria-label={label}
                  className='rounded-lg cursor-pointer flex-shrink-0 overflow-hidden'
                  style={{
                    border: isSel
                      ? '2px solid rgba(0,240,255,0.6)'
                      : '1px solid rgba(255,255,255,0.08)',
                    background: isSel
                      ? 'rgba(0,240,255,0.10)'
                      : 'rgba(255,255,255,0.03)',
                    borderRadius: 10,
                    padding: 4,
                    width: thumbSize + 8,
                  }}
                  onClick={(e) => toggle(idx, e.ctrlKey || e.metaKey)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggle(idx, e.ctrlKey || e.metaKey)
                    }
                  }}
                >
                  <div
                    className='mbp-thumb-shell'
                    data-band={isBand ? entry.item.band : ''}
                    style={{
                      position: 'relative',
                      width: thumbSize,
                      height: thumbSize,
                      borderRadius: 6,
                      overflow: 'hidden',
                      background: '#000',
                    }}
                  >
                    {/* R6.9b: loadError tiles filtered out via visibleEntries above */}
                    <>
                      <img
                        ref={(el) =>
                          isBand
                            ? contrastDOM.registerThumb(
                                entry.item.band,
                                // R6.104-K review: a Hi-Q tile is rendered
                                // server-side, so the hook must not own its
                                // filter. Passing null also DELETES a stale
                                // entry from when this tile was standard -- the
                                // inline ref re-fires every render, so the map
                                // tracks the quality exactly.
                                entryQuality === 'high' ? null : el,
                              )
                            : undefined
                        }
                        src={thumbUrl(
                          entry,
                          ra,
                          dec,
                          bandDisplay,
                          entryQuality,
                        )}
                        alt={label}
                        style={{
                          position: 'absolute',
                          inset: 0,
                          width: '100%',
                          height: '100%',
                          objectFit: 'contain',
                          filter: tileFilter,
                        }}
                        loading={idx === 0 ? 'eager' : 'lazy'}
                        decoding='async'
                        draggable={false}
                        onLoadStart={() =>
                          setImgLoading((prev) => new Set(prev).add(idx))
                        }
                        onLoad={(e) => {
                          // R6.29f: mark loading done first
                          setImgLoading((prev) => {
                            const n = new Set(prev)
                            n.delete(idx)
                            return n
                          })
                          // R6.3b: flag tiny decoded images (e.g. NVSS 15x15 placeholder)
                          const w = e.currentTarget.naturalWidth
                          if (w > 0 && w < 32) {
                            setLoadError((prev) => new Set(prev).add(idx))
                            return
                          }
                          // R6.14: detect 'loaded but mostly black' images.
                          try {
                            const img = e.currentTarget
                            const c = document.createElement('canvas')
                            c.width = img.naturalWidth
                            c.height = img.naturalHeight
                            const ctx = c.getContext('2d')
                            if (!ctx) return
                            ctx.drawImage(img, 0, 0)
                            const data = ctx.getImageData(
                              0,
                              0,
                              c.width,
                              c.height,
                            ).data
                            let nb = 0,
                              tot = 0
                            for (let i = 0; i < data.length; i += 4 * 50) {
                              const r = data[i],
                                g = data[i + 1],
                                b = data[i + 2]
                              if (r + g + b > 30) nb++
                              tot++
                            }
                            const frac = tot > 0 ? nb / tot : 1
                            if (frac < 0.05) {
                              setLoadError((prev) => new Set(prev).add(idx))
                            }
                          } catch (_err) {
                            // Cross-origin taint (HiPS from alasky.cds.unistra.fr)
                            // -> can't read pixels. Assume image is fine.
                          }
                        }}
                      />
                      {/* R6.29f: loading spinner overlay — shown while img in flight */}
                      {imgLoading.has(idx) && (
                        <div
                          style={{
                            position: 'absolute',
                            inset: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(0,0,0,0.55)',
                            zIndex: 3,
                            pointerEvents: 'none',
                          }}
                        >
                          <LoadingOutlined
                            style={{ fontSize: 20, color: '#00F0FF' }}
                            spin
                          />
                        </div>
                      )}
                      {/* R6.34: dual-state indicator for RGB composite:
                            - "re-rendering" (spinner) when actively loading
                            - "cut %" (badge) when component band is being adjusted but image is cached
                            - nothing when slider is 0 (default) */}
                      {entry.kind === 'rgb' && rgbIsRerendering(entry, idx) && (
                        <div
                          style={{
                            position: 'absolute',
                            inset: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(0,0,0,0.55)',
                            zIndex: 3,
                            pointerEvents: 'none',
                          }}
                        >
                          <LoadingOutlined
                            style={{ fontSize: 20, color: '#00F0FF' }}
                            spin
                          />
                        </div>
                      )}
                      {entry.kind === 'rgb' &&
                        rgbIsAdjusting(entry) &&
                        !imgLoading.has(idx) && (
                          <div
                            style={{
                              position: 'absolute',
                              bottom: 2,
                              left: 2,
                              background: 'rgba(0,240,255,0.85)',
                              color: '#0A0014',
                              fontSize: 8,
                              fontWeight: 700,
                              padding: '1px 4px',
                              borderRadius: 3,
                              zIndex: 3,
                              pointerEvents: 'none',
                              letterSpacing: 0.3,
                            }}
                          >
                            cut %
                          </div>
                        )}
                      {/* R6.30: clickable Hi-Q/Std badge. Click to toggle per-tile mode.
                            Hi-Q (cyan) = using /pipeline/hips-float FITS pipeline.
                            Std (gray) = direct CDS jpg (user override). */}
                      {!imgLoading.has(idx) && (
                        <div
                          role='button'
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleTileQuality(idx)
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              e.stopPropagation()
                              toggleTileQuality(idx)
                            }
                          }}
                          title={
                            qualityForEntry(entry, idx) === 'high'
                              ? 'Hi-Q mode (backend FITS+PNG, dithered). Click to switch this tile to Std (direct CDS jpg, faster).'
                              : 'Std mode (direct CDS jpg). Click to switch this tile to Hi-Q.'
                          }
                          style={{
                            position: 'absolute',
                            top: 2,
                            right: 2,
                            background:
                              qualityForEntry(entry, idx) === 'high'
                                ? 'rgba(0,240,255,0.85)'
                                : 'rgba(255,255,255,0.18)',
                            color:
                              qualityForEntry(entry, idx) === 'high'
                                ? '#0A0014'
                                : 'rgba(255,255,255,0.55)',
                            fontSize: 8,
                            fontWeight: 700,
                            padding: '1px 4px',
                            borderRadius: 3,
                            zIndex: 3,
                            cursor: 'pointer',
                            letterSpacing: 0.3,
                            userSelect: 'none',
                          }}
                        >
                          {qualityForEntry(entry, idx) === 'high'
                            ? 'Hi-Q'
                            : 'Std'}
                        </div>
                      )}
                      {isSel && (
                        <div
                          style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: 6,
                            pointerEvents: 'none',
                            boxShadow: 'inset 0 0 0 2px rgba(0,240,255,0.55)',
                            zIndex: 2,
                          }}
                        />
                      )}
                    </>
                    {/* R6.104-K (T16): per-tile DisplayControls popover,
                          replacing the R6.27g hover Slider. The badge shows the
                          band's current cut window; clicking it opens stretch /
                          cuts / advanced controls for THAT band only. */}
                    {isBand && (
                      <div
                        className='mbp-thumb-display'
                        onClick={(e) => e.stopPropagation()}
                        onPointerDown={(e) => e.stopPropagation()}
                        onMouseDown={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                        tabIndex={-1}
                        style={{
                          position: 'absolute',
                          left: 4,
                          right: 4,
                          bottom: 4,
                          background: 'rgba(0,0,0,0.78)',
                          borderRadius: 4,
                          padding: '2px 4px',
                          zIndex: 3,
                          pointerEvents: 'auto',
                          textAlign: 'center',
                        }}
                      >
                        <Popover
                          trigger='click'
                          placement='topLeft'
                          title={label}
                          content={
                            <div style={{ width: 420 }}>
                              <DisplayControls
                                compact
                                showColor={false}
                                value={tileDisplay ?? FALLBACK_DISPLAY_PARAMS}
                                onChange={(next) => {
                                  contrastDOM.setDisplay(entry.item.band, next)
                                  setDisplayForBand(entry.item.band, next)
                                }}
                              />
                            </div>
                          }
                        >
                          <button
                            type='button'
                            title='Stretch / cut window for this band'
                            style={{
                              width: '100%',
                              background: 'transparent',
                              border: 'none',
                              color: 'rgba(255,255,255,0.75)',
                              fontSize: 9,
                              lineHeight: 1.4,
                              cursor: 'pointer',
                              padding: 0,
                            }}
                          >
                            {cutLabel}
                          </button>
                        </Popover>
                      </div>
                    )}
                  </div>
                  <div
                    className='text-xs mt-1 font-semibold text-white/80 truncate'
                    title={label}
                  >
                    {label}
                  </div>
                  <div className='text-xs text-white/45 truncate'>{sub}</div>
                </div>
              </Tooltip>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default memo(MultiBandDataPanel)
