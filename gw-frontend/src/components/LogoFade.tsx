/**
 * R6.83: Shared LogoFade component (extracted from PreloadSplash.tsx).
 *
 * Reusable across login, settings, splash, and any page that displays the
 * AliCPT logo. Three-state machine (loading / loaded / error) with skeleton
 * + fade-in + branded 'A' fallback.
 *
 * Usage:
 *   <LogoFade size={80} />             // default splash size
 *   <LogoFade size={120} />            // login hero
 *   <LogoFade size={64} />             // settings card
 *
 * Visual:
 *   - loading: conic-gradient ring (cyan->violet) + radial-gradient inner disc,
 *     1.4s rotation. Skeleton disappears on img.onLoad.
 *   - Loaded: opacity 0->1 + scale 0.92->1 over 320ms ease-out +
 *     drop-shadow(0 0 12px rgba(0,240,255,0.35)).
 *   - Error: branded 'A' letter with cyan glow, no broken-icon.
 *
 * Assets:
 *   - /Logo_for_AliCPT-splash.webp (preferred)
 *   - /Logo_for_AliCPT-splash.png (fallback)
 *   Both are in public/ (R6.80 sync verified).
 */

import { useState } from 'react'

export interface LogoFadeProps {
  /** Pixel size of the square logo area. Default 80. */
  size?: number
  /** Override the alt text. Default 'AliCPT Logo'. */
  alt?: string
  /** Optional className passthrough for positioning. */
  className?: string
}

export default function LogoFade({ size = 80, alt = 'AliCPT Logo', className }: LogoFadeProps) {
  const [state, setState] = useState<'loading' | 'loaded' | 'error'>('loading')

  // Skeleton ring masks scale with size (28-38px for size=80)
  const innerRadius = Math.round(size * 0.35)
  const ringWidth = Math.round(size * 0.075)
  const ringGap = Math.round(size * 0.025)

  return (
    <div
      className={'relative mx-auto ' + (className || 'mb-5')}
      style={{ width: size, height: size }}
    >
      {/* Outer ambient ping - only after logo loaded, otherwise ring-on-ring visual noise */}
      {state === 'loaded' && (
        <div
          className='absolute inset-0 rounded-full animate-ping opacity-25'
          style={{ background: 'rgba(0,240,255,0.3)' }}
        />
      )}

      {/* Skeleton: pulsing cyan-violet gradient ring (visible during load) */}
      {state === 'loading' && (
        <div
          className='absolute inset-0 rounded-full'
          style={{
            background:
              'conic-gradient(from 0deg, rgba(0,240,255,0.0) 0deg, rgba(0,240,255,0.6) 90deg, rgba(124,58,237,0.5) 180deg, rgba(0,240,255,0.0) 360deg)',
            animation: 'logoSkeleton 1.4s linear infinite',
            maskImage: 'radial-gradient(circle, transparent ' + innerRadius + 'px, black ' + (innerRadius + ringGap) + 'px, black ' + (innerRadius + ringGap + ringWidth) + 'px, transparent ' + (innerRadius + ringGap + ringWidth + ringGap) + 'px)',
            WebkitMaskImage: 'radial-gradient(circle, transparent ' + innerRadius + 'px, black ' + (innerRadius + ringGap) + 'px, black ' + (innerRadius + ringGap + ringWidth) + 'px, transparent ' + (innerRadius + ringGap + ringWidth + ringGap) + 'px)',
          }}
        />
      )}

      {/* Skeleton: pulsing inner disc (visible during load) */}
      {state === 'loading' && (
        <div
          className='absolute rounded-full animate-pulse'
          style={{
            inset: Math.round(size * 0.15),
            background:
              'radial-gradient(circle, rgba(0,240,255,0.15) 0%, rgba(124,58,237,0.08) 60%, transparent 100%)',
          }}
        />
      )}

      {/* Logo image with fade-in transition */}
      <picture>
        <source srcSet='/Logo_for_AliCPT-splash.webp' type='image/webp' />
        <img
          src='/Logo_for_AliCPT-splash.png'
          alt={alt}
          className='absolute inset-0 m-auto object-contain'
          width={size}
          height={size}
          loading='eager'
          fetchPriority='high'
          decoding='async'
          onLoad={() => setState('loaded')}
          onError={() => setState('error')}
          style={{
            borderRadius: '50%',
            opacity: state === 'loaded' ? 1 : 0,
            transform: state === 'loaded' ? 'scale(1)' : 'scale(0.92)',
            transition: 'opacity 320ms ease-out, transform 320ms ease-out',
            filter: 'drop-shadow(0 0 12px rgba(0,240,255,0.35))',
          }}
        />
      </picture>

      {/* Error fallback: branded 'A' letter with cyan glow (no broken icon) */}
      {state === 'error' && (
        <div
          className='absolute inset-0 m-auto rounded-full flex items-center justify-center'
          style={{
            width: size,
            height: size,
            background:
              'linear-gradient(135deg, rgba(0,240,255,0.15) 0%, rgba(124,58,237,0.15) 100%)',
            border: '1px solid rgba(0,240,255,0.4)',
            fontFamily: '"JetBrains Mono", monospace',
            fontWeight: 700,
            fontSize: Math.round(size * 0.4),
            color: '#00F0FF',
            textShadow: '0 0 12px rgba(0,240,255,0.6)',
            opacity: 1,
            transform: 'scale(1)',
            transition: 'opacity 320ms ease-out, transform 320ms ease-out',
          }}
        >
          A
        </div>
      )}

      <style>{`
        @keyframes logoSkeleton {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
