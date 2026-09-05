import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useRequest } from 'ahooks'
import { getGravitationalWave } from '@/service'
import Aladin from './Aladin1'
import FireflyViewer from './FireflyViewer'
import { Segmented } from 'antd'
import { getFitsUrl, getImageUrl } from '@/util/url'
import { preloadImages, preloadFits } from '@/util/preload'
import PreloadSplash from '@/components/PreloadSplash'
import { buildOrderedEntries, getHipsId, BAND_INFO } from '@/util/bandOrder'
import type { OrderedEntry } from '@/util/bandOrder'

type ViewerType = 'aladin' | 'firefly'

// R6.7e: Per-survey HiPS stretch map (mirror of MultiBandDataPanel.tsx HIPS_STRETCH).
// CDS hips2fits stretch param accepts: linear, log, sqrt, asinh.
// - allWISE: asinh — W4 (22µm) has high background (zodiacal + ISM), linear shows tile
//   boundary artifacts. Asinh compresses high values, hides tile boundaries.
// - 2MASS: asinh — same issue, near-IR J/H/Ks have moderate zodiacal background.
// - DSS2/LEGACY/NVSS: linear — low background, optical/near-IR/radio.
// AliCPT-1/Planck: no public HiPS → fall through to local /pipeline/thumbnail.
const HIPS_CUTOUT_BASE =
  'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'
const HIPS_STRETCH: Record<string, string> = {
  allWISE: 'asinh',
  DSS2: 'linear',
  LEGACY: 'linear',
  '2MASS': 'asinh', // R6.16: asinh measured 2x sharper than log (6774 vs 2183 at 400px)
  NVSS: 'linear',
}

function hipsCutoutUrl(
  hips: string,
  ra: number,
  dec: number,
  size = 120,
  stretch = 'linear',
): string {
  return `${HIPS_CUTOUT_BASE}?hips=${encodeURIComponent(hips)}&ra=${ra}&dec=${dec}&fov=3&width=${size}&height=${size}&stretch=${stretch}&format=jpg`
}

// R6.16: per-survey LARGE_SIZE (mirror). See MultiBandDataPanel.tsx for reasoning.
const LARGE_SIZE_BY_SURVEY: Record<string, number> = {
  '2MASS': 600,
  DSS2: 400,
  SDSS: 400,
  allWISE: 400,
  LEGACY: 400,
  NVSS: 400,
  'AliCPT-1': 150,
  Planck: 400,
}
const LARGE_SIZE_DEFAULT = 400
function largeImageUrl(e: OrderedEntry, ra?: number, dec?: number): string {
  if (e.kind === 'rgb') {
    // R6.16 mirror: HiPS-color RGB (e.g. 2MASS) uses HiPS cutout.
    if (e.hipsColor && ra !== undefined && dec !== undefined) {
      const stretch = HIPS_STRETCH[e.survey] || 'asinh'
      return hipsCutoutUrl(
        e.hipsColor,
        ra,
        dec,
        LARGE_SIZE_BY_SURVEY[e.survey] || LARGE_SIZE_DEFAULT,
        stretch,
      )
    }
    return getImageUrl(e.url).replace(
      /size=\d+/,
      `size=${LARGE_SIZE_BY_SURVEY[e.survey] || LARGE_SIZE_DEFAULT}`,
    )
  }
  if (ra !== undefined && dec !== undefined && e.kind === 'band') {
    const hips = getHipsId(e.survey, e.item.band || '')
    if (hips) {
      const stretch = HIPS_STRETCH[e.survey] || 'linear'
      return hipsCutoutUrl(
        hips,
        ra,
        dec,
        LARGE_SIZE_BY_SURVEY[e.survey] || LARGE_SIZE_DEFAULT,
        stretch,
      )
    }
  }
  const fp = e.item.fits_path || e.item.fits_db_path || ''
  const fn = fp.replace('/static-files/fits/', '')
  return `/pipeline/thumbnail?filename=${encodeURIComponent(fn)}&size=${LARGE_SIZE_BY_SURVEY[e.survey] || LARGE_SIZE_DEFAULT}`
}

// thumbUrl: thumbnail URL builder for preload (mirror MultiBandDataPanel's
// thumbUrl). Used to enumerate all URLs to preload when entries change.
const THUMB_SIZE = 120
function thumbUrl(e: OrderedEntry, ra?: number, dec?: number): string {
  if (e.kind === 'rgb') {
    if (e.hipsColor && ra !== undefined && dec !== undefined) {
      const stretch = HIPS_STRETCH[e.survey] || 'asinh'
      return hipsCutoutUrl(e.hipsColor, ra, dec, 400, stretch)
    }
    return getImageUrl(e.url)
  }
  if (ra !== undefined && dec !== undefined && e.kind === 'band') {
    const hips = getHipsId(e.survey, e.item.band || '')
    if (hips) {
      const stretch = HIPS_STRETCH[e.survey] || 'linear'
      return hipsCutoutUrl(hips, ra, dec, 400, stretch)
    }
  }
  const img = e.item.img_path
  if (img) return getImageUrl(img)
  const fp = e.item.fits_path || e.item.fits_db_path || ''
  const fn = fp.replace('/static-files/fits/', '')
  return fn
    ? `/pipeline/thumbnail?filename=${encodeURIComponent(fn)}&size=${THUMB_SIZE}`
    : ''
}

export default function ImageList({ ra, dec }: { ra: number; dec: number }) {
  const { data } = useRequest(() => getGravitationalWave({ ra, dec }), {
    refreshDeps: [ra, dec],
  })
  const entries = useMemo<OrderedEntry[]>(
    () => buildOrderedEntries(data?.data?.list || []),
    [data?.data?.list],
  )
  const [selectedIndexes, setSelectedIndexes] = useState<number[]>([0])
  const [selectedRgbIndex, setSelectedRgbIndex] = useState<number | null>(null)

  const [viewerType, setViewerType] = useState<ViewerType>('aladin')
  const [viewerFullscreen, setViewerFullscreen] = useState(false)
  const [fireflyPreloaded, setFireflyPreloaded] = useState(false)
  // R6.9b: track tiles whose thumbnail failed to load. Filtered from strip
  // so user sees only tiles with valid data.
  const [brokenTiles, setBrokenTiles] = useState<Set<number>>(() => new Set())
  const preloadTimerRef = useRef<ReturnType<typeof setTimeout>>()

  // R6.18 (mirrored from MultiBandDataPanel): preload thumbnails + big images
  // + FITS files into browser cache while the "Preparing observation…" splash
  // is showing. After preload completes, all tile/big-image/Firefly switches
  // hit cache → ms-level response.
  const [preloadDone, setPreloadDone] = useState(false)
  const [preloadProgress, setPreloadProgress] = useState({
    thumbnailsDone: 0,
    thumbnailsTotal: 0,
    bigImagesDone: 0,
    bigImagesTotal: 0,
    fitsDone: 0,
    fitsTotal: 0,
  })
  const preloadIdRef = useRef(0)

  useEffect(() => {
    setViewerType('aladin')
    setFireflyPreloaded(false)
    setSelectedIndexes([0])
    setSelectedRgbIndex(null)
    setBrokenTiles(new Set())
  }, [ra, dec])

  const handleViewerChange = useCallback(
    (val: ViewerType) => {
      setViewerType(val)
      if (val === 'firefly' && !fireflyPreloaded) {
        if (preloadTimerRef.current) clearTimeout(preloadTimerRef.current)
        setFireflyPreloaded(true)
      }
    },
    [fireflyPreloaded],
  )

  // v4.51: Single touch-zone fullscreen toggle — same zone enters/exits
  const toggleFullscreen = useCallback(() => {
    setViewerFullscreen((prev) => !prev)
  }, [])

  const fits = useMemo(
    () =>
      selectedIndexes
        .map((idx) => {
          const e = entries[idx]
          if (!e || e.kind !== 'band') return null
          const fitsPath = e.item.fits_db_path || e.item.fits_path
          if (!fitsPath) return null
          if (
            fitsPath.startsWith('/static-files/') ||
            fitsPath.startsWith('http')
          ) {
            return getFitsUrl(fitsPath)
          }
          return getFitsUrl(`/static-files/fits/${fitsPath}`)
        })
        .filter(Boolean) as string[],
    [selectedIndexes, entries],
  )

  useEffect(() => {
    if (fits.length > 0 && !fireflyPreloaded) {
      preloadTimerRef.current = setTimeout(() => {
        setFireflyPreloaded(true)
      }, 1500)
    }
    return () => {
      if (preloadTimerRef.current) clearTimeout(preloadTimerRef.current)
    }
  }, [fits, fireflyPreloaded])

  // R6.18 preload (mirrored from MultiBandDataPanel).
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (entries.length === 0) {
      setPreloadDone(true)
      return
    }
    setPreloadDone(false)
    const myId = ++preloadIdRef.current

    const thumbUrls = entries.map((e) => thumbUrl(e, ra, dec))
    const bigUrls = entries.map((e) => largeImageUrl(e, ra, dec))
    const fitsUrls = entries
      .filter((e) => e.kind === 'band')
      .map((e) => getFitsUrl(e.item.fits_path || e.item.fits_db_path))
      .filter(Boolean)

    setPreloadProgress({
      thumbnailsDone: 0,
      thumbnailsTotal: thumbUrls.length,
      bigImagesDone: 0,
      bigImagesTotal: bigUrls.length,
      fitsDone: 0,
      fitsTotal: fitsUrls.length,
    })

    const tick =
      (key: 'thumbnailsDone' | 'bigImagesDone' | 'fitsDone') => (d: number) => {
        if (preloadIdRef.current !== myId) return
        setPreloadProgress((p) => ({ ...p, [key]: d }))
      }

    Promise.all([
      preloadImages(thumbUrls, tick('thumbnailsDone')),
      preloadImages(bigUrls, tick('bigImagesDone')),
      preloadFits(fitsUrls, tick('fitsDone')),
    ]).then(() => {
      if (preloadIdRef.current === myId) setPreloadDone(true)
    })
  }, [ra, dec, entries])

  // R6.13: compute the big-viewer image URL the same way as the thumbnail.
  // Source priority (matches the panel helper):
  //   1. RGB composite click -> merge-rgb URL at LARGE_SIZE
  //   2. Single-band click with HiPS -> hipsCutoutUrl (no rotation, no stretch drift)
  //   3. Single-band click without HiPS (AliCPT, Planck) -> /pipeline/thumbnail at LARGE_SIZE
  //   4. Multi-select -> first selected band's largeImageUrl
  const imageUrl = useMemo(() => {
    if (selectedRgbIndex !== null) {
      const e = entries[selectedRgbIndex]
      if (e && e.kind === 'rgb') return largeImageUrl(e, ra, dec)
    }
    if (selectedIndexes.length >= 1) {
      const e = entries[selectedIndexes[0]]
      if (e) return largeImageUrl(e, ra, dec)
    }
    return ''
  }, [selectedRgbIndex, selectedIndexes, entries, ra, dec])

  // R6.13: alt text for accessibility / screen readers.
  const imageAlt = useMemo(() => {
    if (selectedRgbIndex !== null) {
      const e = entries[selectedRgbIndex]
      return e?.kind === 'rgb' ? `${e.label} composite` : 'FITS preview'
    }
    if (selectedIndexes.length === 1) {
      const e = entries[selectedIndexes[0]]
      if (e?.kind === 'band') {
        const info = BAND_INFO[e.item.band]
        return info ? `${info.name} (${info.lambda})` : e.item.band
      }
    }
    return 'FITS preview'
  }, [selectedRgbIndex, selectedIndexes, entries])

  const select = (idx: number, multi: boolean) => {
    const entry = entries[idx]
    if (entry?.kind === 'rgb') {
      setSelectedRgbIndex(selectedRgbIndex === idx ? null : idx)
      setSelectedIndexes([])
      return
    }
    setSelectedRgbIndex(null)
    if (multi) {
      setSelectedIndexes((prev) => {
        if (prev.includes(idx)) return prev.filter((i) => i !== idx)
        return [...prev, idx]
      })
    } else {
      setSelectedIndexes([idx])
    }
  }

  const handleSelect = (idx: number, e: React.MouseEvent) =>
    select(idx, e.shiftKey)

  // R6.18: preload progress totals for splash overlay
  const total =
    preloadProgress.thumbnailsTotal +
    preloadProgress.bigImagesTotal +
    preloadProgress.fitsTotal
  const done =
    preloadProgress.thumbnailsDone +
    preloadProgress.bigImagesDone +
    preloadProgress.fitsDone

  // R6.8b: RGB composite image branch removed (parity with Abnormal Data —
  // RGB click in strip no longer opens a big image panel; user views RGB by
  // selecting its constituent bands in the strip). rgbUrl state still
  // tracked so RGB-tile toggle behavior remains, but unused for display.
  // R6.19 (mirror MultiBandDataPanel): both viewers always mounted; toggle
  // via visibility so Firefly iframe + WebGL context persist across switches.
  // The PreloadSplash already caches all FITS bytes, so first Firefly click
  // is a CSS toggle (ms-level).
  const viewerBody = (
    <>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          height: '100%',
          visibility: viewerType === 'aladin' ? 'visible' : 'hidden',
          pointerEvents: viewerType === 'aladin' ? 'auto' : 'none',
        }}
      >
        <Aladin imageUrl={imageUrl} alt={imageAlt} />
      </div>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          height: '100%',
          visibility: viewerType === 'firefly' ? 'visible' : 'hidden',
          pointerEvents: viewerType === 'firefly' ? 'auto' : 'none',
        }}
      >
        <FireflyViewer fits={fits} />
      </div>
    </>
  )

  const hasViewerContent = !!imageUrl

  return (
    <div className='relative w-full h-full'>
      <PreloadSplash
        visible={!preloadDone}
        total={total}
        done={done}
        thumbnailsDone={preloadProgress.thumbnailsDone}
        thumbnailsTotal={preloadProgress.thumbnailsTotal}
        bigImagesDone={preloadProgress.bigImagesDone}
        bigImagesTotal={preloadProgress.bigImagesTotal}
        fitsDone={preloadProgress.fitsDone}
        fitsTotal={preloadProgress.fitsTotal}
        hint='Caching thumbnails, big images, and FITS files for instant switching'
      />
      <div className='flex items-center justify-between px-2 mb-1'>
        <span className='text-sm text-white/50 font-semibold'>FITS Viewer</span>
        <Segmented
          size='small'
          options={[
            { label: 'Aladin', value: 'aladin' },
            { label: 'Firefly', value: 'firefly' },
          ]}
          value={viewerType}
          onChange={(val) => handleViewerChange(val as ViewerType)}
        />
      </div>
      {/* v4.52: Portal fullscreen — escapes nav bar stacking context */}
      {viewerFullscreen && hasViewerContent ? (
        createPortal(
          <div className='fits-fullscreen-viewer'>
            <div
              className='fits-fullscreen-zone'
              onClick={toggleFullscreen}
              role='button'
              tabIndex={0}
              aria-label='Exit fullscreen'
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggleFullscreen()
                }
              }}
            >
              <span className='fits-fullscreen-icon'>✕</span>
            </div>
            <div className='fits-fullscreen-body'>{viewerBody}</div>
          </div>,
          document.body,
        )
      ) : (
        <div
          className='flex-1 min-h-0 overflow-hidden'
          style={{ position: 'relative', minHeight: 420, zIndex: 1 }}
        >
          {hasViewerContent && (
            <div
              className='fits-fullscreen-zone flex'
              onClick={toggleFullscreen}
              role='button'
              tabIndex={0}
              aria-label='Fullscreen viewer'
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggleFullscreen()
                }
              }}
            >
              <span className='fits-fullscreen-icon'>⛶</span>
            </div>
          )}
          {viewerBody}
        </div>
      )}

      {/* Thumbnail strip (ordered surveys + auto RGB) — R6.9b filter broken tiles */}
      <div className='flex gap-4 overflow-x-auto py-2'>
        {entries
          .filter((_, idx) => !brokenTiles.has(idx))
          .map((entry, idx) => {
            // R6.9b: map filtered index back to original index for brokenTiles tracking
            const originalIdx = entries.indexOf(entry)
            const isBand = entry.kind === 'band'
            const selected = isBand
              ? selectedIndexes.includes(idx)
              : selectedRgbIndex === idx
            return (
              <div
                key={idx}
                role='button'
                tabIndex={0}
                aria-pressed={selected}
                aria-label={
                  isBand
                    ? 'Select ' + (entry.item.band || 'band') + ' observation'
                    : 'Select ' + entry.label
                }
                className='rounded-lg min-w-[120px] text-center cursor-pointer transition-all flex-shrink-0'
                style={{
                  border: selected
                    ? '2px solid rgba(0,240,255,0.5)'
                    : '1px solid rgba(255,255,255,0.08)',
                  background: selected
                    ? 'rgba(0,240,255,0.10)'
                    : 'rgba(255,255,255,0.03)',
                  borderRadius: 12,
                  padding: 4,
                }}
                onClick={(e) => handleSelect(idx, e)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    select(idx, e.shiftKey)
                  }
                }}
              >
                <div
                  style={{
                    position: 'relative',
                    width: 100,
                    height: 100,
                    aspectRatio: '1 / 1',
                    borderRadius: 8,
                    overflow: 'hidden',
                    background: '#000',
                  }}
                >
                  <img
                    onError={() => {
                      // R6.9b: mark tile as broken; filtered from strip on next render
                      setBrokenTiles((prev) => {
                        if (prev.has(originalIdx)) return prev
                        const next = new Set(prev)
                        next.add(originalIdx)
                        return next
                      })
                    }}
                    onLoad={(e) => {
                      // R6.14 mirror: tiny-image (NVSS 15x15 placeholder) + all-black
                      // detection (e.g. Legacy RGB merge-rgb returns valid PNG that's
                      // 0% non-black). User explicit: '如果确实无数据就可以不保留'.
                      const w = e.currentTarget.naturalWidth
                      if (w > 0 && w < 32) {
                        setBrokenTiles((prev) => {
                          if (prev.has(originalIdx)) return prev
                          const next = new Set(prev)
                          next.add(originalIdx)
                          return next
                        })
                        return
                      }
                      try {
                        const img = e.currentTarget
                        const c = document.createElement('canvas')
                        c.width = img.naturalWidth
                        c.height = img.naturalHeight
                        const ctx = c.getContext('2d')
                        if (!ctx) return
                        ctx.drawImage(img, 0, 0)
                        const data = ctx.getImageData(
                          0,
                          0,
                          c.width,
                          c.height,
                        ).data
                        let nb = 0,
                          tot = 0
                        for (let i = 0; i < data.length; i += 4 * 50) {
                          const r = data[i],
                            g = data[i + 1],
                            b = data[i + 2]
                          if (r + g + b > 30) nb++
                          tot++
                        }
                        if (tot > 0 && nb / tot < 0.05) {
                          setBrokenTiles((prev) => {
                            if (prev.has(originalIdx)) return prev
                            const next = new Set(prev)
                            next.add(originalIdx)
                            return next
                          })
                        }
                      } catch (_err) {
                        // HiPS cross-origin taint — assume image is fine.
                      }
                    }}
                    src={
                      isBand
                        ? (() => {
                            // R6.7e: prefer HiPS cutout with per-survey stretch for
                            // HiPS-capable surveys (DSS2/LEGACY/2MASS/allWISE/NVSS).
                            // Local FITS thumbnails used only as fallback when no
                            // public HiPS exists (AliCPT-1, Planck).
                            const hips = getHipsId(
                              entry.survey,
                              entry.item.band || '',
                            )
                            if (hips) {
                              const stretch =
                                HIPS_STRETCH[entry.survey] || 'linear'
                              return hipsCutoutUrl(
                                hips,
                                ra!,
                                dec!,
                                120,
                                stretch,
                              )
                            }
                            const img = entry.item.img_path || ''
                            if (img) return img
                            const fp =
                              entry.item.fits_path ||
                              entry.item.fits_db_path ||
                              ''
                            const fn = fp.replace('/static-files/fits/', '')
                            return fn
                              ? `/pipeline/thumbnail?filename=${encodeURIComponent(fn)}&size=120`
                              : ''
                          })()
                        : entry.url
                    }
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                      filter: isBand ? 'brightness(1.1) contrast(1.1)' : 'none',
                    }}
                    alt={isBand ? entry.item.band || 'obs' : entry.label}
                    loading='lazy'
                  />
                  <span
                    style={{
                      position: 'absolute',
                      bottom: 0,
                      left: 0,
                      right: 0,
                      background:
                        'linear-gradient(transparent, rgba(0,0,0,0.8))',
                      color: isBand ? '#0f0' : '#00e5ff',
                      fontSize: 9,
                      padding: '8px 4px 2px',
                      textAlign: 'center',
                      fontFamily: 'monospace',
                    }}
                  >
                    {isBand ? entry.item.band : entry.label}
                  </span>
                </div>
                <div className='text-xs mt-1 font-semibold text-white/80'>
                  {isBand ? entry.item.band : entry.label}
                </div>
                <div className='text-xs text-white/45 font-medium'>
                  {isBand ? entry.item.telescope : 'RGB composite'}
                </div>
              </div>
            )
          })}
      </div>
    </div>
  )
}
