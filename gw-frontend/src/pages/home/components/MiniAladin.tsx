// R6: MiniAladin — lightweight Aladin wrapper for 140x140 thumbnail tiles.
// v4.54-r6: replaces the raw <img> thumbnail with a real mini-Aladin sky view
// centered on the band's RA/Dec. Lazy-mounted via IntersectionObserver so
// the initial paint isn't blocked by 10+ WASM initializations.
//
// Usage: <MiniAladin ra={ra} dec={dec} size={140} loaded={selected} />
// - ra/dec: coordinates for the sky view
// - size: pixel size of the square tile
// - loaded: optional bool — if false, skip mounting (avoids loading all 10 at once)

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import ErrorBoundary from '@/components/ErrorBoundary'

interface MiniAladinProps {
  ra?: number
  dec?: number
  size?: number
  loaded?: boolean
  fov?: number
  // R6-data-critic: stable per-tile seed from parent (band index) prevents
  // iframe reload storm on every parent re-render. DO NOT use Math.random() here.
  seed?: string | number
}

const MAX_RETRIES = 2
const RETRY_DELAY_MS = 2000
const LOAD_TIMEOUT_MS = 8000

export default function MiniAladin({
  ra,
  dec,
  size = 140,
  loaded = true,
  fov = 0.25,
  seed = '0',
}: MiniAladinProps): JSX.Element {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [ready, setReady] = useState(false)
  const [retries, setRetries] = useState(0)
  const attemptRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const retryTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const cancelledRef = useRef(false)
  // R6: don't actually mount the iframe until `loaded` becomes true.
  // Avoids loading 10+ Aladin instances at once on initial panel render.
  const [shouldMount, setShouldMount] = useState(false)

  // Activate when parent says tile is loaded (selected OR scrolled into view)
  useEffect(() => {
    if (loaded) {
      // Tiny delay to avoid hammering the browser when many tiles flip at once
      const t = setTimeout(() => setShouldMount(true), 50)
      return () => clearTimeout(t)
    }
  }, [loaded])

  // R6-data-critic: memoize miniUrl so parent re-renders don't reload the iframe.
  // Seed is stable per-tile (parent passes band index); ra/dec/fov are the
  // actual coordinate inputs.
  const miniUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (ra !== undefined && Number.isFinite(ra)) params.set('ra', String(ra))
    if (dec !== undefined && Number.isFinite(dec))
      params.set('dec', String(dec))
    // R6-data-critic: allow fov=0 (degenerate but valid). Use Number.isFinite
    // instead of || so fov=0 doesn't get coerced to 0.25.
    if (Number.isFinite(fov)) params.set('fov', String(fov))
    params.set('seed', String(seed))
    return '/aladin-test-mini.html?' + params.toString()
  }, [ra, dec, fov, seed])

  const handleIframeLoad = useCallback(() => {
    setReady(true)
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
  }, [])

  // R6: iframe cleanup on unmount — same pattern as Aladin1
  useEffect(() => {
    // Copy refs to locals to satisfy react-hooks/ref-cleanup (avoid stale closure)
    const iframe = iframeRef.current
    const timeout = timeoutRef.current
    const retryTimer = retryTimerRef.current
    return () => {
      cancelledRef.current = true
      if (iframe) iframe.src = 'about:blank'
      if (timeout) clearTimeout(timeout)
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [])

  // R6: self-rescheduling retry loop (same pattern as Aladin1 — see R5d memory).
  // useRef instead of useState for the attempt counter so all retries actually fire.
  useEffect(() => {
    if (!shouldMount) return
    setReady(false)
    setRetries(0)
    attemptRef.current = 0
    cancelledRef.current = false
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)

    const armTimeout = () => {
      if (cancelledRef.current) return
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      timeoutRef.current = setTimeout(() => {
        if (cancelledRef.current) return
        if (attemptRef.current >= MAX_RETRIES) {
          setReady(true)
          return
        }
        attemptRef.current += 1
        setRetries(attemptRef.current)
        retryTimerRef.current = setTimeout(() => {
          if (cancelledRef.current) return
          if (iframeRef.current) {
            const bust =
              (miniUrl.indexOf('?') >= 0 ? '&' : '?') +
              '_r=' +
              attemptRef.current
            iframeRef.current.src = miniUrl + bust
            armTimeout()
          }
        }, RETRY_DELAY_MS)
      }, LOAD_TIMEOUT_MS)
    }

    armTimeout()
    return () => {
      cancelledRef.current = true
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [miniUrl, shouldMount])

  return (
    <ErrorBoundary>
      <div
        className='relative w-full h-full overflow-hidden'
        style={{
          width: size,
          height: size,
          background: '#000',
          borderRadius: 6,
        }}
      >
        {shouldMount ? (
          <iframe
            ref={iframeRef}
            src={miniUrl}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              border: 0,
              display: 'block',
              // R6: block interaction — the tile is a passive preview, the user
              // clicks to select the band which loads the full Aladin viewer above.
              pointerEvents: 'none',
            }}
            title='Aladin mini thumbnail'
            onLoad={handleIframeLoad}
            loading='lazy'
          />
        ) : null}
        {!ready && shouldMount && (
          <div className='absolute inset-0 flex items-center justify-center text-cyan-400/50 text-[10px] font-mono'>
            {retries > 0 ? `${retries}/${MAX_RETRIES}` : '…'}
          </div>
        )}
      </div>
    </ErrorBoundary>
  )
}
