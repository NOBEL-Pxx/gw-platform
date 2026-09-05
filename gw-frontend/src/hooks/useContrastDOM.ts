// R6.27i: direct-DOM contrast/brightness update for ms-level slider response.
//
// Why not React state? React reconciliation on a large <img> with a CSS
// `filter` style can take 50-200ms on a busy page (the parent re-renders,
// children re-evaluate, browser re-applies filter, re-paints). The user
// perceives this as "the slider lags".
//
// How DS9 does it: contrast/bias are just parameters to the pixel->display
// mapping. Changing them doesn't re-fetch or re-render React tree; it just
// changes the next frame's mapping. We emulate this by writing the filter
// directly to the <img> elements via refs / style mutation. The browser
// then handles the visual update at its native rate (< 16ms on modern GPUs).
//
// React state is still updated for localStorage persistence and for any
// other UI that depends on the value (e.g., slider position). The visual
// update is decoupled.

import { useRef, useCallback, useMemo } from 'react'

function filterFormula(v: number): string {
  // v in [-100, 100]. 0 = neutral (no filter).
  if (v === 0) return ''
  return `contrast(${1 + v / 100}) brightness(${1 + v / 200})`
}

export interface ContrastDOM {
  /** Attach to a thumbnail <img>: data-band attribute + register via callback. */
  registerThumb: (band: string, el: HTMLImageElement | null) => void
  /** Attach to the Aladin big image via ref. */
  bigImgRef: React.MutableRefObject<HTMLImageElement | null>
  /** Set the current band's big image band tag (so setContrast knows when to apply). */
  setActiveBand: (band: string | null) => void
  /** Directly update filter on the matching thumb + big image. Returns the filter string. */
  setContrast: (band: string, value: number) => string
  /** Compute the filter string from a value (pure, for the <img> initial style). */
  compute: (value: number) => string
}

export function useContrastDOM(): ContrastDOM {
  // Map<band, HTMLImageElement> for thumbnails. Persisted across renders
  // (useRef ensures stability).
  const thumbsRef = useRef<Map<string, HTMLImageElement>>(new Map())
  // Big image element + active band.
  const bigImgRef = useRef<HTMLImageElement | null>(null)
  const activeBandRef = useRef<string | null>(null)

  const registerThumb = useCallback(
    (band: string, el: HTMLImageElement | null) => {
      if (el) {
        thumbsRef.current.set(band, el)
        el.dataset.band = band
      } else {
        thumbsRef.current.delete(band)
      }
    },
    [],
  )

  const setActiveBand = useCallback((band: string | null) => {
    activeBandRef.current = band
  }, [])

  const setContrast = useCallback((band: string, value: number): string => {
    const filter = filterFormula(value)
    // Update matching thumbnail
    const thumb = thumbsRef.current.get(band)
    if (thumb) {
      if (filter) thumb.style.filter = filter
      else thumb.style.removeProperty('filter')
    }
    // Update big image if it matches the active band
    const big = bigImgRef.current
    if (big && activeBandRef.current === band) {
      if (filter) big.style.filter = filter
      else big.style.removeProperty('filter')
    }
    return filter
  }, [])

  const compute = useMemo(() => (value: number) => filterFormula(value), [])

  return { registerThumb, bigImgRef, setActiveBand, setContrast, compute }
}
