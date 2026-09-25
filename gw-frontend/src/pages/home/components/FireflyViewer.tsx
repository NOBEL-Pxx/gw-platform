// R6.67.4: inlined a local ErrorBoundary instead of importing the shared
// `@/components/ErrorBoundary` default export. The bundle's cross-chunk
// import (`import{t as E} from './index-...js'` where entry aliases J->t)
// was resolving to an object (React error #130). Co-locating the boundary
// keeps it in the SAME chunk as the consumer and sidesteps the lookup.

import {
  useState,
  useMemo,
  useEffect,
  useCallback,
  useRef,
  Component,
  type ReactNode,
} from 'react'
import { Switch, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import {
  DEFAULT_DISPLAY_PARAMS,
  clampDisplayParams,
  type ColorTable,
  type StretchType,
} from '@/components/DisplayControls/types'
import { DisplayControls, useDisplayControlsState } from '@/components/DisplayControls'

// R6.67.4: minimal local ErrorBoundary, co-located to avoid the
// cross-chunk default-export bug (React error #130).
class LocalErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  componentDidCatch(error: Error) {
    console.error('[Firefly LocalErrorBoundary]', error)
  }
  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          className='flex items-center justify-center p-4 text-white/60 text-sm'
          style={{ minHeight: 200, background: '#0A0F1E' }}
        >
          Firefly render error: {this.state.error?.message || 'unknown'}
        </div>
      )
    }
    return this.props.children
  }
}

// R6.104-K: map DisplayParams ColorTable names → Firefly v4.32 integer IDs.
// cividis/parula/native have no exact v4.32 equivalent → viridis(16)/grayscale(0).
const FIREFLY_COLOR_TABLE_IDS: Record<ColorTable, number> = {
  grayscale: 0,
  rainbow: 8,
  viridis: 16,
  magma: 17,
  inferno: 18,
  plasma: 19,
  cubehelix: 20,
  cividis: 16,
  parula: 16,
  native: 0,
}
function colorTableFor(c: ColorTable): number {
  return FIREFLY_COLOR_TABLE_IDS[c] ?? 16
}
// R6.104-K: map DisplayParams StretchType (AladinLite lowercase) → Firefly
// v4.32 StretchType names (capitalized). pow2 → Power, equalization → HistogramEq.
const FIREFLY_STRETCH_NAMES: Record<StretchType, string> = {
  linear: 'Linear',
  sqrt: 'Sqrt',
  log: 'Log',
  asinh: 'Asinh',
  pow2: 'Power',
  equalization: 'HistogramEq',
}
function stretchFor(s: StretchType): string {
  return FIREFLY_STRETCH_NAMES[s] ?? 'Log'
}

interface FireflyViewerProps {
  fits?: string[]
  hipsSurvey?: string
  // R6.99-A: gates iframe mounting. Parent (MultiBandDataPanel /
  // ImageList) passes mount=true on first user click of Firefly tab.
  // Reverts R6.19 always-mount to eliminate WASM + WebGL init jank
  // on first paint of MultiBandDataPanel / ImageList.
  mount?: boolean
}

function has2MASS(fits?: string[]): boolean {
  return fits?.some((f) => /2mass|_j\.|_h\.|_k\./i.test(f)) ?? false
}

export default function FireflyViewer({
  fits,
  hipsSurvey,
  mount = false,
}: FireflyViewerProps): JSX.Element {
  // R6.104-K-A: DisplayParams is the SSOT. showGrid/iframeKey are Firefly-viewer
  // concerns, not part of DisplayParams, so they stay local.
  const { value: display, setValue: setDisplay } = useDisplayControlsState(DEFAULT_DISPLAY_PARAMS)
  const [showGrid, setShowGrid] = useState(true)
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
      setDisplay(clampDisplayParams({
        ...display,
        stretch: 'asinh',
        minCut: display.minCut === -1 ? 0.5 : display.minCut,
      }))
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
    // gw-firefly can resolve from its Docker network.
    //
    // R6.103-I (2026-09-15): updated http://gw-backend:8093 → http://divs-backend:8093.
    // Post R6.99-D the gw-backend Docker DNS alias was removed (per
    // [[r699e-post-deploy-frontend-hygiene]] iron rule). The actual backend
    // container_name in docker-compose.zjlab.yml is 'divs-backend'; compose
    // service names are NOT automatic DNS aliases when container_name is set.
    // Verified 2026-09-15: `getent hosts divs-backend` from gw-firefly returns
    // 192.168.240.4; `getent hosts gw-backend` returns empty (NXDOMAIN).
    //
    // History (R6.20c intent preserved):
    //   - relative URL: Firefly rejects ("Failed- url, s3, gcs ref are all null")
    //   - window.location.origin: gw-firefly can't resolve trycloudflare.com from
    //     inside the container ("Failed- Could not connect to service")
    //   - window.location.hostname + ':8093': only works on localhost; on tunnel
    //     port 8093 isn't publicly exposed.
    //
    // The ONLY URL that always works for Firefly's server-side fetcher is
    // http://divs-backend:8093/static-files/fits/... — Docker network hostname.
    const BACKEND_INTERNAL = 'http://divs-backend:8093' // R6.103-I: post R6.99-D, gw-backend alias GONE per [[r699e-post-deploy-frontend-hygiene]]. Must use divs-backend.
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
      colorTableFor(display.colormap) +
      '&stretch=' +
      stretchFor(display.stretch) +
      '&grid=' +
      (showGrid ? '1' : '0') +
      '&minCut=' +
      display.minCut +
      '&maxCut=' +
      display.maxCut +
      '&cutMode=' +
      display.cutMode +
      '&gamma=' +
      display.gamma +
      '&brightness=' +
      display.brightness +
      '&contrast=' +
      display.contrast +
      '&saturation=' +
      display.saturation
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
          // R6.104-K-A: send full DisplayParams SSOT
          colorTable: colorTableFor(display.colormap),
          stretch: stretchFor(display.stretch),
          showGrid,
          minCut: display.minCut,
          maxCut: display.maxCut,
          cutMode: display.cutMode,
          gamma: display.gamma,
          brightness: display.brightness,
          contrast: display.contrast,
          saturation: display.saturation,
        },
        '*',
      )
    }, 50)
    return () => {
      if (postMsgTimer.current) clearTimeout(postMsgTimer.current)
    }
  }, [display, showGrid])

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
    // R6.20c: see initialIframeUrl comment. Always use divs-backend Docker
    // hostname (R6.103-I: was gw-backend, removed in R6.99-D per
    // [[r699e-post-deploy-frontend-hygiene]] iron rule).
    const BACKEND_INTERNAL = 'http://divs-backend:8093' // R6.103-I: post R6.99-D, gw-backend alias GONE per [[r699e-post-deploy-frontend-hygiene]]. Must use divs-backend.
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

  return (
    <LocalErrorBoundary>
      <div
        className='w-full h-full flex flex-col'
        style={{ background: '#0A0F24' }}
      >
        {/* R6.104-K: unified display controls (stretch / colormap / cut / gamma / ...) */}
        <DisplayControls
          value={display}
          onChange={setDisplay}
          onAutoStretch={() => {
            // R6.104-K-C limitation: WebGL canvas inside cross-origin iframe
            // cannot be read from parent (tainted-canvas rule). Approximate
            // AladinLite 'Local cut' by clipping 2.5%/99.5% percentiles on the
            // user-facing params; re-render goes via postMessage updateDisplay.
            setDisplay(clampDisplayParams({ ...display, minCut: 2.5, maxCut: 99.5, cutMode: 'percent' }))
          }}
        />

        {/* Auxiliary row: Grid + 2MASS badge + Reload (Firefly-viewer concerns) */}
        <div
          className='flex items-center gap-2 px-3 py-1.5 border-b border-white/6 flex-shrink-0 flex-wrap'
          style={{ background: 'rgba(255,255,255,0.02)' }}
        >
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
              className='text-xs px-1.5 py-1 rounded shrink-0'
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

        {/* Viewer */}
        <div className='flex-1 relative'>
          {hasData && initialSrc && mount ? (
            <iframe
              key={iframeKey}
              src={initialSrc}
              ref={iframeRef}
              className='w-full h-full'
              style={{ border: 'none' }}
              title='Firefly FITS Viewer'
              allow='fullscreen'
            />
          ) : !mount ? (
            // R6.99-A: lazy-mount placeholder. Shown until parent sets
            // mount=true on first Firefly tab click. Avoids 4-5s WASM
            // init on first paint of MultiBandDataPanel / ImageList.
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
                <p>Firefly viewer (lazy mount)</p>
                <p
                  className='text-xs mt-1'
                  style={{ color: 'rgba(255,255,255,0.20)' }}
                >
                  Firefly v4.32 — first click triggers ~5s WASM init
                </p>
              </div>
            </div>
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
    </LocalErrorBoundary>
  )
}
