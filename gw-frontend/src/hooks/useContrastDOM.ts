// R6.104-K: extended to 4-axis CSS filter formula. Keeps direct-DOM mutation
// path for ms-level slider response (R6.27i preserved). Gamma is not natively
// supported by CSS filter, so when gamma !== 1.0 the caller must pre-bake a
// <feColorMatrix> via the parent (MultiBandDataPanel does this when needed).
//
// R6.104-K (T15-fix): the active big <img> is click-to-load (see Aladin1's
// `lazy` prop), so it does NOT exist in the DOM when the parent's
// currentBand effect first runs setDisplay(). Writing to a null ref silently
// dropped those settings. The hook now remembers the last params per band and
// re-applies them from `registerBig` -- a callback ref that fires the instant
// the big <img> actually mounts.

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
  // R6.104-K (T15-fix): callback ref for the active big <img>. Assign to
  // Aladin's `imgRef` prop. Replays the stored filter on mount.
  registerBig: (el: HTMLImageElement | null) => void
  bigImgRef: React.MutableRefObject<HTMLImageElement | null>
  setActiveBand: (band: string | null) => void
  setDisplay: (band: string, params: DisplayParams) => string
  compute: (params: DisplayParams) => string
}

export function useContrastDOM(): ContrastDOM {
  const thumbsRef = useRef<Map<string, HTMLImageElement>>(new Map())
  const bigImgRef = useRef<HTMLImageElement | null>(null)
  const activeBandRef = useRef<string | null>(null)
  // R6.104-K (T15-fix): last params written per band, so a big <img> that
  // mounts later (click-to-load reveal) can be brought up to date.
  const paramsRef = useRef<Map<string, DisplayParams>>(new Map())

  const registerThumb = useCallback((band: string, el: HTMLImageElement | null) => {
    if (el) { thumbsRef.current.set(band, el); el.dataset.band = band }
    else thumbsRef.current.delete(band)
  }, [])

  const setActiveBand = useCallback((band: string | null) => {
    activeBandRef.current = band
  }, [])

  // R6.104-K (T15-fix): single place that writes a filter string onto an
  // <img>, so the thumb / big / remount paths can never drift apart.
  const applyFilter = useCallback((el: HTMLImageElement | null, filter: string) => {
    if (!el) return
    if (filter) el.style.filter = filter
    else el.style.removeProperty('filter')
  }, [])

  const setDisplay = useCallback((band: string, params: DisplayParams): string => {
    paramsRef.current.set(band, params)
    const filter = filterFormula(params)
    applyFilter(thumbsRef.current.get(band) ?? null, filter)
    if (activeBandRef.current === band) {
      applyFilter(bigImgRef.current, filter)
    }
    return filter
  }, [applyFilter])

  // R6.104-K (T15-fix): callback ref for the active big <img>. React invokes
  // it with the element on mount and null on unmount. On mount we replay the
  // stored params for the active band -- that is what makes contrast settings
  // applied BEFORE the click-to-load reveal stick once the image appears.
  const registerBig = useCallback((el: HTMLImageElement | null) => {
    bigImgRef.current = el
    if (!el) return
    const band = activeBandRef.current
    if (!band) return
    const params = paramsRef.current.get(band)
    if (params) applyFilter(el, filterFormula(params))
  }, [applyFilter])

  const compute = useMemo(() => (p: DisplayParams) => filterFormula(p), [])

  return { registerThumb, registerBig, bigImgRef, setActiveBand, setDisplay, compute }
}
