/**
 * GWChirpWave — LIGO-style gravitational wave chirp signal visualization.
 *
 * Renders animated SVG waveform + spacetime grid distortion behind the hero title.
 * Black holes and gravity ripples are owned by the landing page (single source of truth).
 * Keyframes are defined in landing/index.tsx to avoid CSS cascade conflicts.
 */
import { memo } from 'react'

// Frequency bands — concentric expanding detection rings
const FREQ_BANDS = [
  { r: 180, opacity: 0.04, delay: 0 },
  { r: 200, opacity: 0.06, delay: 0.5 },
  { r: 230, opacity: 0.05, delay: 1.2 },
  { r: 260, opacity: 0.03, delay: 2.0 },
  { r: 300, opacity: 0.02, delay: 3.0 },
]

function GWChirpWave() {
  return (
    <div
      className='absolute inset-0 pointer-events-none overflow-hidden'
      aria-hidden='true'
    >
      {/* Detection frequency bands — expanding concentric circles */}
      <div
        className='absolute left-1/2 top-1/2'
        style={{ transform: 'translate(-50%, -50%)' }}
      >
        {FREQ_BANDS.map(({ r, opacity, delay }) => (
          <div
            key={'freq-' + r}
            className='gw-ripple absolute rounded-full'
            style={{
              width: r * 2,
              height: r * 2,
              left: '50%',
              top: '50%',
              transform: 'translate(-50%, -50%)',
              border:
                '1px solid rgba(0,240,255,' + (opacity * 3).toFixed(3) + ')',
              boxShadow:
                '0 0 ' +
                r * 0.15 +
                'px rgba(0,240,255,' +
                opacity.toFixed(3) +
                '), inset 0 0 ' +
                r * 0.15 +
                'px rgba(124,58,237,' +
                (opacity * 0.8).toFixed(3) +
                ')',
              animation: 'gwRipple 8s ease-out infinite',
              animationDelay: delay + 's',
              opacity: 0,
            }}
          />
        ))}
      </div>

      {/* Spacetime grid distortion — SVG with quadratically warped grid lines */}
      <div className='absolute inset-0' style={{ perspective: '800px' }}>
        <svg
          className='absolute w-full h-full'
          style={{ opacity: 0.06 }}
          viewBox='0 0 1200 800'
          preserveAspectRatio='xMidYMid slice'
        >
          {/* Horizontal grid lines — bend toward center (600, 400) */}
          {[-300, -200, -120, -60, 0, 60, 120, 200, 300].map((y, i) => (
            <path
              key={'h' + i}
              d={
                'M0,' +
                (400 + y) +
                ' Q400,' +
                (400 + y * 0.5) +
                ' 600,' +
                (400 + y * 0.2) +
                ' Q800,' +
                (400 + y * 0.5) +
                ' 1200,' +
                (400 + y)
              }
              stroke='rgba(0,240,255,0.5)'
              strokeWidth='0.5'
              fill='none'
            />
          ))}
          {/* Vertical grid lines — bend toward center */}
          {[-400, -300, -200, -100, 0, 100, 200, 300, 400].map((x, i) => (
            <path
              key={'v' + i}
              d={
                'M' +
                (600 + x) +
                ',0 Q' +
                (600 + x * 0.5) +
                ',300 ' +
                (600 + x * 0.2) +
                ',400 Q' +
                (600 + x * 0.5) +
                ',500 ' +
                (600 + x) +
                ',800'
              }
              stroke='rgba(124,58,237,0.4)'
              strokeWidth='0.5'
              fill='none'
            />
          ))}
        </svg>
      </div>

      {/* LIGO chirp waveform — animated SVG at bottom of hero */}
      <div
        className='gw-chirp absolute left-1/2'
        style={{
          bottom: '12%',
          transform: 'translateX(-50%)',
          width: 'min(700px, 80vw)',
          height: 100,
        }}
      >
        <svg
          viewBox='0 0 700 60'
          preserveAspectRatio='none'
          className='w-full h-full'
          style={{ overflow: 'visible' }}
        >
          <defs>
            <linearGradient id='chirpGrad' x1='0' y1='0' x2='1' y2='0'>
              <stop offset='0%' stopColor='rgba(0,240,255,0.1)' />
              <stop offset='30%' stopColor='rgba(124,58,237,0.3)' />
              <stop offset='50%' stopColor='rgba(0,240,255,0.6)' />
              <stop offset='55%' stopColor='rgba(255,255,255,0.9)' />
              <stop offset='60%' stopColor='rgba(0,240,255,0.6)' />
              <stop offset='70%' stopColor='rgba(124,58,237,0.2)' />
              <stop offset='100%' stopColor='rgba(0,240,255,0.05)' />
            </linearGradient>
            <filter id='chirpGlow'>
              <feGaussianBlur stdDeviation='2' result='blur' />
              <feMerge>
                <feMergeNode in='blur' />
                <feMergeNode in='SourceGraphic' />
              </feMerge>
            </filter>
          </defs>

          {/* Primary waveform — inspiral → merger → ringdown */}
          <path
            d='M0,40 Q10,38 20,39 T40,35 T60,30 T80,28 T100,20 T120,22 T140,10 T160,15 T180,-2 T200,5 T210,-8 T220,8 T230,-15 T240,12 T250,-5 T255,10 T260,-3 T265,5 T270,0 Q300,25 350,35 T450,38 T550,40 Q650,42 700,40'
            stroke='url(#chirpGrad)'
            strokeWidth='2'
            fill='none'
            filter='url(#chirpGlow)'
            strokeLinecap='round'
            style={{ animation: 'chirpPulse 4s ease-in-out infinite' }}
          />

          {/* Secondary ghost waveform — offset for depth */}
          <path
            d='M0,40 Q10,39 20,39.5 T40,37 T60,33 T80,30 T100,24 T120,23 T140,14 T160,16 T180,5 T200,8 T210,2 T220,7 T230,-5 T240,8 T250,2 T255,7 T260,3 T265,5 T270,2 Q300,23 350,33 T450,37 T550,39 Q650,41 700,40'
            stroke='rgba(124,58,237,0.25)'
            strokeWidth='1'
            fill='none'
            strokeLinecap='round'
            style={{ animation: 'chirpPulse 4s ease-in-out infinite 0.7s' }}
          />
        </svg>
      </div>
    </div>
  )
}

// memo() justified: avoids re-render when landing page state changes (e.g. navigation)
export default memo(GWChirpWave)
