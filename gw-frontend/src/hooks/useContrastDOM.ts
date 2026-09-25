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
