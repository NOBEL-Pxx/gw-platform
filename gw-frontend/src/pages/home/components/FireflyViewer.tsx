import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import ErrorBoundary from '@/components/ErrorBoundary'
import { Select, Switch, Tooltip, InputNumber, Button, Slider } from 'antd'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'

const COLOR_TABLES: Record<string, number> = {
  Grayscale: 0,
  Heat: 4,
  Rainbow: 8,
  Viridis: 16,
  Magma: 17,
  Inferno: 18,
  Plasma: 19,
  Cubehelix: 20,
}
const STRETCH_OPTIONS = ['Linear', 'Log', 'Sqrt', 'Asinh'] as const

interface FireflyViewerProps {
  fits?: string[]
  hipsSurvey?: string
}

function has2MASS(fits?: string[]): boolean {
  return fits?.some((f) => /2mass|_j\.|_h\.|_k\./i.test(f)) ?? false
}

export default function FireflyViewer({
  fits,
  hipsSurvey,
}: FireflyViewerProps): JSX.Element {
  const [colorTable, setColorTable] = useState<number>(16)
  const [stretch, setStretch] = useState<string>('Log')
  const [showGrid, setShowGrid] = useState(true)
  const [minCut, setMinCut] = useState<number>(-1)
  const [maxCut, setMaxCut] = useState<number>(99.5)
  const [iframeKey, setIframeKey] = useState(0)
  const postMsgTimer = useRef<ReturnType<typeof setTimeout>>()
  // R6.17: persistent ref to skip first swapFits (first load = iframe load).
  // Must live at component top-level so it survives effect re-runs.
  const isFirstFitsLoad = useRef(true)
  // R6.17b: stable iframe src. Setting iframe.src reloads firefly_loader.js
  // (~1.5MB) + re-inits Firefly (~5-10s) — fatal for swap latency. So we
  // capture the initial URL once and freeze it. After mount, all content
  // changes go via postMessage {type:'swapFits'}.
  const [initialSrc, setInitialSrc] = useState<string | null>(null)

  const is2MASS = has2MASS(fits)
  const hasData = (fits && fits.length > 0) || !!hipsSurvey

  // 2MASS auto-preset
  useEffect(() => {
    if (is2MASS) {
      setStretch('Asinh')
      if (minCut === -1) setMinCut(0.5)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [is2MASS])

  // R6.17c + R6.19: build iframe URL once we have data. Originally had empty
  // deps `[]` to build ONCE — but R6.19 always-mounts this component, so on
  // first render fits=[] and useMemo caches null forever (iframe never mounts).
  // Fix: depend on `hasData` so URL recomputes on empty→non-empty transition.
  // The useEffect guard `if (!initialSrc)` below ensures iframe.src is set
  // exactly once on the FIRST non-empty URL — subsequent fits changes still
  // go via postMessage (no firefly.js reload).
  const initialIframeUrl = useMemo(() => {
    if (!hasData) return null
    // R6.20c: Firefly's showImage() runs SERVER-SIDE inside the gw-firefly
    // Docker container. The URL passed in opts.URL must be a URL that
    // gw-firefly can resolve from its Docker network. We always use
    // http://gw-backend:8093 because the gw-firefly container can always
    // reach gw-backend via Docker DNS, regardless of where the user accesses
    // from (localhost or any public tunnel URL).
    //
    // Previous attempts (R6.20 / R6.20b) failed:
    //   - relative URL: Firefly rejects ("Failed- url, s3, gcs ref are all null")
    //   - window.location.origin: gw-firefly can't resolve trycloudflare.com from
    //     inside the container ("Failed- Could not connect to service")
    //   - window.location.hostname + ':8093': only works on localhost; on tunnel
    //     port 8093 isn't publicly exposed.
    //
    // The ONLY URL that always works for Firefly's server-side fetcher is
    // http://gw-backend:8093/static-files/fits/... — Docker network hostname.
    const BACKEND_INTERNAL = 'http://gw-backend:8093'
    const encoded =
      fits
        ?.map((u) => {
          const fullUrl = u.startsWith('http')
            ? u
            : BACKEND_INTERNAL + (u.startsWith('/') ? u : '/' + u)
          const m = u.match(/\/static-files\/fits\/([^/]+)\//)
          const survey = m ? m[1] : ''
          const band = u.split('_').pop()?.replace('.fits', '') || ''
          const tag = survey + '-' + band
          return encodeURIComponent(fullUrl) + ',' + encodeURIComponent(tag)
        })
        .join(';') || ''
    return (
      '/firefly-viewer.html?imgs=' +
      encoded +
      '&color=' +
      colorTable +
      '&stretch=' +
      stretch +
      '&grid=' +
      (showGrid ? '1' : '0') +
      '&minCut=' +
      minCut +
      '&maxCut=' +
      maxCut
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasData]) // R6.19: depend on hasData so URL is built when fits becomes non-empty

  // R6.17: iframe mounted ONCE for the session. fits[] swaps go via
  // postMessage (effect below). iframeKey only changes on explicit
  // 'Reload' click. This preserves Firefly JS init + WebGL context.
  const iframeRef = useRef<HTMLIFrameElement>(null)

  // v4.31: Live display updates via postMessage — avoids 10-30s iframe reload
  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe?.contentWindow) return
    // Debounce 50ms to avoid flooding Firefly during rapid slider drags
    if (postMsgTimer.current) clearTimeout(postMsgTimer.current)
    postMsgTimer.current = setTimeout(() => {
      iframe.contentWindow?.postMessage(
        {
          type: 'updateDisplay',
          colorTable,
          stretch,
          showGrid,
          minCut,
          maxCut,
        },
        '*',
      )
    }, 50)
    return () => {
      if (postMsgTimer.current) clearTimeout(postMsgTimer.current)
    }
  }, [colorTable, stretch, showGrid, minCut, maxCut])

  // R6.17b: capture initial src once. Subsequent fits changes do NOT
  // update iframe.src (which would reload firefly_loader.js -> 5-10s).
  // All swaps after mount go via postMessage (effect below).
  useEffect(() => {
    if (!initialIframeUrl) return
    if (!initialSrc) setInitialSrc(initialIframeUrl)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialIframeUrl])

  // R6.17: swap FITS files via postMessage instead of reloading iframe.
  // First load still needs iframe load (Firefly JS init ~4-5s, one-time).
  // Subsequent fits[] changes are sent as {type:'swapFits', imgs}, achieving
  // millisecond-level response (no JS re-init, no WebGL re-create, browser
  // cache serves the PNG bytes from server-side thumbnail cache).
  useEffect(() => {
    if (!fits || !iframeRef.current?.contentWindow) return
    if (isFirstFitsLoad.current) {
      isFirstFitsLoad.current = false
      return
    }
    // R6.20c: see initialIframeUrl comment. Always use gw-backend Docker
    // hostname because Firefly fetches FITS server-side from its container.
    const BACKEND_INTERNAL = 'http://gw-backend:8093'
    const imgs = fits.map((u) => {
      const fullUrl = u.startsWith('http')
        ? u
        : BACKEND_INTERNAL + (u.startsWith('/') ? u : '/' + u)
      const m = u.match(/\/static-files\/fits\/([^/]+)\//)
      const survey = m ? m[1] : ''
      const band = u.split('_').pop()?.replace('.fits', '') || ''
      const surveyTag = survey + '-' + band
      return { pngUrl: fullUrl, surveyTag }
    })
    iframeRef.current.contentWindow.postMessage({ type: 'swapFits', imgs }, '*')
  }, [fits])

  // Cleanup iframe src on unmount to stop network requests
  useEffect(() => {
    const iframe = iframeRef.current
    return () => {
      if (iframe) {
        iframe.src = 'about:blank'
      }
    }
  }, [])

  const reload = useCallback(() => setIframeKey((k) => k + 1), [])
  const resetCuts = useCallback(() => {
    setMinCut(-1)
    setMaxCut(99.5)
  }, [])

  return (
    <ErrorBoundary>
      <div
        className='w-full h-full flex flex-col'
        style={{ background: '#0A0F24' }}
      >
        {/* Toolbar row 1: Color, Stretch, Grid */}
        <div
          className='flex items-center gap-2 px-3 py-1.5 border-b border-white/6 flex-shrink-0 flex-wrap'
          style={{ background: 'rgba(255,255,255,0.04)' }}
        >
          <span className='text-white/60 text-xs font-medium shrink-0'>
            Color:
          </span>
          <Select
            size='small'
            value={colorTable}
            onChange={setColorTable}
            style={{ width: 100 }}
            options={Object.entries(COLOR_TABLES).map(([l, v]) => ({
              label: l,
              value: v,
            }))}
          />
          <span className='text-white/60 text-xs font-medium shrink-0'>
            Stretch:
          </span>
          <Select
            size='small'
            value={stretch}
            onChange={setStretch}
            style={{ width: 80 }}
            options={STRETCH_OPTIONS.map((s) => ({ label: s, value: s }))}
          />
          <Tooltip title='Grid'>
            <Switch
              size='small'
              checked={showGrid}
              onChange={setShowGrid}
              checkedChildren='G'
              unCheckedChildren='G'
            />
          </Tooltip>
          {is2MASS && (
            <span
              className='text-xs px-1.5 py-0.5 rounded shrink-0'
              style={{ background: 'rgba(168,85,247,0.15)', color: '#A855F7' }}
            >
              2MASS
            </span>
          )}
          <button
            onClick={reload}
            className='text-white/50 hover:text-white/80 text-xs px-2 py-1 rounded border border-white/10 hover:border-white/20 transition-colors ml-auto shrink-0'
            style={{ background: 'rgba(255,255,255,0.04)' }}
          >
            <ReloadOutlined className='mr-1' />
            Reload
          </button>
        </div>

        {/* Toolbar row 2: Contrast cuts — ALWAYS visible */}
        <div
          className='flex items-center gap-2 px-3 py-1.5 border-b border-white/6 flex-shrink-0 flex-wrap'
          style={{ background: 'rgba(255,255,255,0.02)' }}
        >
          <span className='text-white/50 text-xs shrink-0'>Clip:</span>
          <InputNumber
            size='small'
            min={-1}
            max={100}
            step={0.5}
            value={minCut}
            onChange={(v) => setMinCut(v ?? -1)}
            style={{ width: 64 }}
            placeholder='Auto'
            className='cut-input'
          />
          <div className='flex-1' style={{ minWidth: 100, maxWidth: 200 }}>
            <Slider
              range
              min={-1}
              max={100}
              step={0.5}
              value={[minCut, maxCut]}
              onChange={([lo, hi]) => {
                setMinCut(lo)
                setMaxCut(hi)
              }}
              tooltip={{
                formatter: (v?: number) => (v === -1 ? 'Auto' : v + '%'),
              }}
              className='cut-slider'
            />
          </div>
          <InputNumber
            size='small'
            min={-1}
            max={100}
            step={0.5}
            value={maxCut}
            onChange={(v) => setMaxCut(v ?? 99.5)}
            style={{ width: 64 }}
            placeholder='99.5'
            className='cut-input'
          />
          <Button
            size='small'
            onClick={resetCuts}
            style={{ color: 'rgba(255,255,255,0.4)', fontSize: 11 }}
          >
            Reset
          </Button>
          {is2MASS && <span className='text-white/30 text-xs'>%</span>}
        </div>

        {/* Viewer */}
        <div className='flex-1 relative'>
          {hasData && initialSrc ? (
            <iframe
              key={iframeKey}
              src={initialSrc}
              ref={iframeRef}
              className='w-full h-full'
              style={{ border: 'none' }}
              title='Firefly FITS Viewer'
              allow='fullscreen'
            />
          ) : (
            <div
              className='absolute inset-0 flex items-center justify-center'
              style={{
                background: 'rgba(10,15,36,0.80)',
                color: 'rgba(255,255,255,0.40)',
              }}
            >
              <div className='text-center'>
                <div
                  style={{
                    fontSize: 48,
                    color: 'rgba(255,255,255,0.10)',
                    marginBottom: 12,
                  }}
                >
                  <ReloadOutlined spin />
                </div>
                <p>Select observations to load FITS</p>
                <p
                  className='text-xs mt-1'
                  style={{ color: 'rgba(255,255,255,0.20)' }}
                >
                  Firefly v4.32
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </ErrorBoundary>
  )
}
