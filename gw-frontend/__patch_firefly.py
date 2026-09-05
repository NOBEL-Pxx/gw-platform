import re

with open('D:/AliCPT/gw-frontend/src/pages/home/components/FireflyViewer.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add useIframe state
content = content.replace(
    'const [showGrid, setShowGrid] = useState(true)\n  const loadedRef',
    'const [showGrid, setShowGrid] = useState(true)\n  const [useIframe, setUseIframe] = useState(false)\n  const loadedRef'
)

# 2. Change connect error handling to fall back to iframe
old_retry = '''          console.error('Firefly connection failed:', err)
          if (retryCountRef.current < MAX_RETRIES) { retryCountRef.current += 1; const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 12000); setRetryCount(retryCountRef.current); setTimeout(connect, delay) }
          else { setError(\x60Firefly local server unreachable after ${MAX_RETRIES} attempts. Run: docker compose up -d gw-firefly\x60); setLoading(false) }'''
new_retry = '''          console.warn('Firefly JS API failed, falling back to iframe mode:', err)
          setUseIframe(true)
          setLoading(false)'''
content = content.replace(old_retry, new_retry)

# 3. Add useIframe guard to loadImages useEffect
content = content.replace(
    'useEffect(() => { if (!loading && !error && ffRef.current) loadImages() }, [loading, error, loadImages])',
    'useEffect(() => { if (!loading && !error && ffRef.current && !useIframe) loadImages() }, [loading, error, loadImages, useIframe])'
)

# 4. Add iframe-related code before error check
iframe_block = '''
  // Build iframe URL for fallback mode
  const iframeUrl = (() => {
    if (!useIframe) return null
    const encodedFits = fits?.map(u => {
      const fullUrl = u.startsWith('http') ? u : 'http://gw-backend:8093' + (u.startsWith('/') ? u : '/' + u)
      return encodeURIComponent(fullUrl)
    }).join(',') || ''
    return '/firefly-viewer.html?fits=' + encodedFits + '&color=' + colorTable + '&stretch=' + stretch + '&grid=' + (showGrid ? '1' : '0')
  })()

  // Reset iframe when controls change
  const [iframeKey, setIframeKey] = useState(0)
  useEffect(() => {
    if (useIframe) setIframeKey(k => k + 1)
  }, [colorTable, stretch, showGrid, fits?.join(',')])
'''
content = content.replace('\n  if (error) return (', iframe_block + '\n  if (error) return (')

# 5. Guard loading spinner
content = content.replace(
    '  if (loading) return (',
    '  if (loading && !useIframe) return ('
)

# 6. Add iframe UI before hasData check
iframe_ui = '''  // Iframe fallback mode
  if (useIframe && iframeUrl) {
    return (
      <div className='w-full h-full flex flex-col' style={{ background: '#0A0F24' }}>
        <div className='flex items-center gap-3 px-3 py-1.5 border-b border-white/6 flex-shrink-0 flex-wrap' style={{ background: 'rgba(255,255,255,0.04)' }}>
          <span className='text-white/60 text-xs font-medium'>Color:</span>
          <Select size='small' value={colorTable} onChange={v => setColorTable(v)}
            style={{ width: 100 }}
            options={Object.entries(COLOR_TABLES).map(([l, v]) => ({ label: l, value: v }))} />
          <span className='text-white/60 text-xs font-medium'>Stretch:</span>
          <Select size='small' value={stretch} onChange={setStretch} style={{ width: 80 }}
            options={STRETCH_OPTIONS.map(s => ({ label: s, value: s }))} />
          <Tooltip title='Coordinate grid'>
            <Switch size='small' checked={showGrid} onChange={v => setShowGrid(v)} checkedChildren='G' unCheckedChildren='G' />
          </Tooltip>
          <span className='text-white/45 text-xs ml-auto'>iframe</span>
        </div>
        <div className='flex-1 relative'>
          <iframe key={iframeKey} src={iframeUrl} className='w-full h-full' style={{ border: 'none' }}
            sandbox='allow-scripts allow-same-origin'
            title='Firefly FITS Viewer' />
          {!hasData && (
            <div className='absolute inset-0 flex items-center justify-center pointer-events-none' style={{ background: 'rgba(10,15,36,0.80)', color: 'rgba(255,255,255,0.40)' }}>
              <div className='text-center'>
                <BgColorsOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.20)' }} />
                <p className='mt-3'>Select observations to load FITS</p>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

'''
content = content.replace('\n  const hasData = (fits && fits.length > 0) || !!hipsSurvey', iframe_ui + '\n  const hasData = (fits && fits.length > 0) || !!hipsSurvey')

# 7. Remove retryCount from dependency (no longer used with retry)
content = content.replace('}, [retryCount])', '}, [retryCount, useIframe])')

with open('D:/AliCPT/gw-frontend/src/pages/home/components/FireflyViewer.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('SUCCESS: FireflyViewer.tsx patched')
