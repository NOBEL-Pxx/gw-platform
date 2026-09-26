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
function clampCutWindow(
  cutMode: DisplayParams['cutMode'],
  minRaw: number,
  maxRaw: number,
): { minCut: number; maxCut: number } {
  if (cutMode !== 'absolute') {
    // Percent mode is deliberately NOT reconciled: minCut = -1 is the legal
    // "Auto / no bottom clipping" sentinel, and the backend's 0-49 / 51-100
    // Query bounds (hips.py, server.py) already keep this pair from crossing.
    return {
      minCut: Math.max(-1, Math.min(100, minRaw)),
      maxCut: Math.max(0, Math.min(100, maxRaw)),
    }
  }
  const minCut = Math.max(0, Math.min(65535, minRaw))
  const maxCut = Math.max(0, Math.min(65535, maxRaw))
  // R6.104-K review (M3): the backend rejects min_cut_abs >= max_cut_abs with a
  // 400 and the tile then vanishes with no message. Both sliders clamp to
  // [0, 65535] independently, so the state was reachable.
  //
  // Crossed pair (min > max): swap. That preserves both requested values rather
  // than inventing one, and a crossed pair is the obvious reading of the input.
  //
  // Zero-width pair (min === max): widen max by one level. If min is already at
  // the ceiling there is no room above it, so pull the pair down to the top two
  // levels instead -- computing maxCut as minCut + 1 here would emit 65536,
  // which the backend's le=65535 rejects, reintroducing the very 400 this
  // function exists to prevent.
  //
  // Every arm returns a pair inside [0, 65535] with minCut < maxCut. The backend
  // 400 stays as defence-in-depth for programmatic callers.
  if (minCut > maxCut) return { minCut: maxCut, maxCut: minCut }
  if (minCut === maxCut) {
    return minCut < 65535
      ? { minCut, maxCut: minCut + 1 }
      : { minCut: 65534, maxCut: 65535 }
  }
  return { minCut, maxCut }
}

/** Clamp helpers for each field's legal range. */
export function clampDisplayParams(p: Partial<DisplayParams>): DisplayParams {
  const cutMode = p.cutMode ?? DEFAULT_DISPLAY_PARAMS.cutMode
  const cutWindow = clampCutWindow(
    cutMode,
    p.minCut ?? (cutMode === 'absolute' ? 0 : -1),
    p.maxCut ?? (cutMode === 'absolute' ? 65535 : 99.5),
  )
  return {
    stretch: p.stretch ?? DEFAULT_DISPLAY_PARAMS.stretch,
    colormap: p.colormap ?? DEFAULT_DISPLAY_PARAMS.colormap,
    cutMode,
    minCut: cutWindow.minCut,
    // R6.104-K review: percent maxCut floors at 0, NOT -1. The -1 sentinel
    // means "auto" for minCut only ("no bottom clipping"); for maxCut it is
    // meaningless and reached np.percentile as q=-1 -> ValueError -> HTTP
    // 500 on /pipeline/merge-rgb. Every write path funnels through here, so
    // this one clamp is what makes the state unreachable from the UI.
    maxCut: cutWindow.maxCut,
    gamma: Math.max(0.3, Math.min(3.0, p.gamma ?? 1.0)),
    brightness: Math.max(-0.5, Math.min(0.5, p.brightness ?? 0.0)),
    contrast: Math.max(0.5, Math.min(2.0, p.contrast ?? 1.0)),
    saturation: Math.max(0.0, Math.min(2.0, p.saturation ?? 1.0)),
  }
}
