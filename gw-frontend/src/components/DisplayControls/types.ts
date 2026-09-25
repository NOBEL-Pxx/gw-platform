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
