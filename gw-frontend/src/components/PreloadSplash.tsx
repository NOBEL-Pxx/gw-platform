/**
 * R6.18: Splash overlay shown during initial prewarm of Multi-band Observation.
 *
 * Visual:
 *   - Full overlay over MultiBandDataPanel
 *   - AliCPT cyan-violet gradient + animated ring (matches landing page)
 *   - Progress: "Pre-loading 12 / 19 thumbnails..." (live count)
 *   - Auto-fades when `progress.pct >= 100` or `done === true`
 *
 * The trick: this splash absorbs the natural ~5-8s prewarm time during which
 * the user expects to wait anyway. By the time it fades, every URL is in
 * browser cache, so ALL subsequent tile/big-image/Firefly/Aladin switches
 * are instant.
 */

import { useEffect, useState } from 'react'

export interface PreloadSplashProps {
  visible: boolean
  total: number
  done: number
  thumbnailsDone: number
  thumbnailsTotal: number
  bigImagesDone: number
  bigImagesTotal: number
  fitsDone: number
  fitsTotal: number
  hint?: string
}

export default function PreloadSplash({
  visible,
  total,
  done,
  thumbnailsDone,
  thumbnailsTotal,
  bigImagesDone,
  bigImagesTotal,
  fitsDone,
  fitsTotal,
  hint,
}: PreloadSplashProps) {
  const [fading, setFading] = useState(false)

  useEffect(() => {
    if (!visible) {
      setFading(false)
      return
    }
    if (total > 0 && done >= total) {
      // Brief pause so user sees "100%" before fade
      const t = setTimeout(() => setFading(true), 300)
      return () => clearTimeout(t)
    }
  }, [visible, total, done])

  if (!visible) return null
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  // R6.27e: splash NEVER blocks clicks. Tile strip + Segmented stay usable
  // while preload runs. Old R6.27d splash had opacity-100 with full z-50
  // pointer events — combined with the force-settle bug, this hid the
  // latency from the user (they never clicked anything while splash was
  // up). Once splash faded, every click was a cold CDN load → felt broken.
  return (
    <div
      className={
        'absolute inset-0 z-50 flex items-center justify-center transition-opacity duration-500 ' +
        (fading ? 'opacity-0' : 'opacity-100')
      }
      style={{
        background: 'rgba(10,15,30,0.85)',
        backdropFilter: 'blur(6px)',
        pointerEvents: 'none',
      }}
    >
      <div
        className='text-center px-8 py-6 rounded-2xl max-w-md'
        style={{
          background: 'rgba(15,21,42,0.95)',
          border: '1px solid rgba(0,240,255,0.15)',
        }}
      >
        {/* R6.33: logo replaces animated ring. Consistent with Info page logo. */}
        <div
          className='relative mx-auto mb-5'
          style={{ width: 80, height: 80 }}
        >
          <div
            className='absolute inset-0 rounded-full animate-ping opacity-25'
            style={{ background: 'rgba(0,240,255,0.3)' }}
          />
          <picture>
            <source srcSet='/Logo_for_AliCPT-splash.webp' type='image/webp' />
            <img
              src='/Logo_for_AliCPT-splash.png'
              alt='AliCPT Logo'
              className='absolute inset-0 m-auto object-contain'
              width={80}
              height={80}
              loading='eager'
              fetchPriority='high'
              style={{ borderRadius: '50%' }}
            />
          </picture>
        </div>
        <p
          className='text-white font-semibold tracking-wide mb-1'
          style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 14 }}
        >
          {pct < 100 ? 'Preparing observation…' : 'Ready'}
        </p>
        <p
          className='text-xs text-white/40 mb-4'
          style={{ fontFamily: '"JetBrains Mono", monospace' }}
        >
          {pct}% — {done} / {total} assets cached
        </p>

        {/* Per-phase progress */}
        <div className='space-y-1.5 text-left'>
          <ProgressRow
            label='Thumbnails'
            done={thumbnailsDone}
            total={thumbnailsTotal}
            color='#00F0FF'
          />
          <ProgressRow
            label='Big images'
            done={bigImagesDone}
            total={bigImagesTotal}
            color='#7C3AED'
          />
          <ProgressRow
            label='FITS files'
            done={fitsDone}
            total={fitsTotal}
            color='#10B981'
          />
        </div>

        {/* Master bar */}
        <div
          className='mt-4 h-1 rounded-full overflow-hidden'
          style={{ background: 'rgba(255,255,255,0.06)' }}
        >
          <div
            className='h-full transition-all duration-300'
            style={{
              width: pct + '%',
              background: 'linear-gradient(90deg, #00F0FF, #7C3AED)',
            }}
          />
        </div>

        {hint && (
          <p
            className='text-[10px] text-white/30 mt-3'
            style={{ fontFamily: '"JetBrains Mono", monospace' }}
          >
            {hint}
          </p>
        )}
      </div>
    </div>
  )
}

function ProgressRow({
  label,
  done,
  total,
  color,
}: {
  label: string
  done: number
  total: number
  color: string
}) {
  const dPct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div
      className='flex items-center gap-2 text-[10px]'
      style={{ fontFamily: '"JetBrains Mono", monospace' }}
    >
      <span className='w-20 text-white/50'>{label}</span>
      <div
        className='flex-1 h-1 rounded-full overflow-hidden'
        style={{ background: 'rgba(255,255,255,0.06)' }}
      >
        <div
          className='h-full transition-all duration-200'
          style={{ width: dPct + '%', background: color }}
        />
      </div>
      <span className='w-16 text-right text-white/40'>
        {done}/{total}
      </span>
    </div>
  )
}
