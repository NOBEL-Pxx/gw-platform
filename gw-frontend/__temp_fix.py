import { useEffect, useRef, useState, useCallback } from 'react'
import { initFirefly } from 'firefly-api-access'
import { Spin, Alert, Button, Select, Switch, Tooltip } from 'antd'
import { ReloadOutlined, BgColorsOutlined } from '@ant-design/icons'
import type { FireflyAPI } from 'firefly-api-access'

const COLOR_TABLES: Record<string, number> = {
  Grayscale: 0, Heat: 4, Rainbow: 8,
  Viridis: 16, Magma: 17, Inferno: 18,
  Plasma: 19, Cubehelix: 20,
}
const STRETCH_OPTIONS = ['Linear', 'Log', 'Sqrt', 'Asinh'] as const

interface FireflyViewerProps { fits?: string[]; hipsSurvey?: string }
interface WCSReadout { ra: number; dec: number; pixelX: number; pixelY: number }

export default function FireflyViewer({ fits, hipsSurvey }: FireflyViewerProps): JSX.Element {
  const ffRef = useRef<FireflyAPI | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const MAX_RETRIES = 3
  const [retryCount, setRetryCount] = useState(0)
  const retryCountRef = useRef(0)
  const [colorTable, setColorTable] = useState<number>(16)
  const [stretch, setStretch] = useState<string>('Linear')
  const [showGrid, setShowGrid] = useState(true)
  const [wcsReadout, setWcsReadout] = useState<WCSReadout | null>(null)
  const loadedRef = useRef<Set<string>>(new Set())
  const containerId = 'firefly-main-view'

  // Connect to local Firefly Docker container (proxied by Nginx)
  useEffect(() => {
    let cancelled = false
    const connect = async () => {
      try {
        setLoading(true)
        setError(null)
        const getFF = initFirefly(window.location.origin + '/firefly')
        const ff = await getFF()
        if (!cancelled) {
          ffRef.current = ff
          setLoading(false)
          try {
            (ff as any).util?.addActionListener?.('READOUT_DATA', (_a: unknown, s: any) => {
              if (s?.wpt && !cancelled) {
                setWcsReadout({ ra: s.wpt.lon, dec: s.wpt.lat, pixelX: s.ipt?.x ?? 0, pixelY: s.ipt?.y ?? 0 })
              }
            })
          } catch { /* WCS optional */ }
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Firefly connection failed:', err)
          if (retryCountRef.current < MAX_RETRIES) { retryCountRef.current += 1; const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 12000); setRetryCount(retryCountRef.current); setTimeout(connect, delay) }
          else { setError(`Firefly local server unreachable after ${MAX_RETRIES} attempts. Run: docker compose up -d gw-firefly`); setLoading(false) }
        }
      }
    }
    connect()
    return () => { cancelled = true }
  }, [retryCount])

  const loadImages = useCallback(() => {
    const ff = ffRef.current
    if (!ff) return
    const prev = loadedRef.current
    const next = new Set<string>()
    if (hipsSurvey) next.add('hips:' + hipsSurvey)
    fits?.forEach(url => {
        // Firefly Java server needs Docker-internal absolute URLs
        const fullUrl = url.startsWith('http') ? url : 'http://gw-backend:8093' + (url.startsWith('/') ? url : '/' + url)
        next.add(fullUrl)
      })
    prev.forEach(key => { if (!next.has(key)) { try { (ff as any).removeLayer?.(key) } catch {}; prev.delete(key) } })
    next.forEach(key => {
      if (prev.has(key)) return
      try {
        if (key.startsWith('hips:')) {
          ff.showImage(containerId, { plotId: 'hips-0', hipsRootUrl: key.slice(5), Title: 'HiPS Survey', GridOn: showGrid, ColorTable: colorTable, StretchType: stretch })
        } else {
          ff.showImage(containerId, { URL: key, Title: key.split('/').pop() || 'FITS', ColorTable: colorTable, StretchType: stretch, ZoomType: 'TO_WIDTH', GridOn: showGrid })
        }
        prev.add(key)
      } catch (err) { console.error('Load failed:', key, err) }
    })
  }, [fits, hipsSurvey, colorTable, stretch, showGrid])

  useEffect(() => { if (!loading && !error && ffRef.current) loadImages() }, [loading, error, loadImages])

  const reload = () => { loadedRef.current.clear(); loadImages() }

  if (error) return (
    <div className='w-full h-full flex items-center justify-center' style={{ background: '#0A0F24' }}>
      <Alert message='Firefly Unavailable' description={error} type='warning' showIcon style={{ maxWidth: 520 }}
        action={<Button size='small' onClick={() => setRetryCount(0)} icon={<ReloadOutlined />}>Retry</Button>} />
    </div>
  )

  if (loading) return (
    <div className='w-full h-full flex items-center justify-center' style={{ background: '#0A0F24' }}>
      <Spin tip='Starting Firefly local server...' size='large'><div style={{ padding: 120 }} /></Spin>
    </div>
  )

  const hasData = (fits && fits.length > 0) || !!hipsSurvey

  return (
    <div className='w-full h-full flex flex-col' style={{ background: '#0A0F24' }}>
      <div className='flex items-center gap-3 px-3 py-1.5 border-b border-white/6 flex-shrink-0 flex-wrap' style={{ background: 'rgba(255,255,255,0.04)' }}>
        <span className='text-white/60 text-xs font-medium'>Color:</span>
        <Select size='small' value={colorTable} onChange={v => { setColorTable(v); reload() }}
          style={{ width: 100 }}
          options={Object.entries(COLOR_TABLES).map(([l, v]) => ({ label: l, value: v }))} />
        <span className='text-white/60 text-xs font-medium'>Stretch:</span>
        <Select size='small' value={stretch} onChange={setStretch} style={{ width: 80 }}
          options={STRETCH_OPTIONS.map(s => ({ label: s, value: s }))} />
        <Tooltip title='Coordinate grid'>
          <Switch size='small' checked={showGrid} onChange={v => { setShowGrid(v); reload() }} checkedChildren='G' unCheckedChildren='G' />
        </Tooltip>
        <Button size='small' icon={<ReloadOutlined />} onClick={reload}>Reload</Button>
        {wcsReadout && (
          <span className='text-green-400 text-xs ml-auto font-mono'>
            RA {wcsReadout.ra.toFixed(4)}&deg; Dec {wcsReadout.dec.toFixed(4)}&deg;
          </span>
        )}
      </div>
      <div className='flex-1 relative'>
        <div id={containerId} className='w-full h-full' />
        {!hasData && (
          <div className='absolute inset-0 flex items-center justify-center pointer-events-none' style={{ background: 'rgba(10,15,36,0.80)', color: 'rgba(255,255,255,0.40)' }}>
            <div className='text-center'>
              <BgColorsOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.20)' }} />
              <p className='mt-3'>Select observations to load FITS</p>
              <p className='text-xs mt-1' style={{ color: 'rgba(255,255,255,0.25)' }}>Firefly ready</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
