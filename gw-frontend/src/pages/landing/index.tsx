import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import GWChirpWave from '@/components/GWChirpWave'

const ORBIT_TEXTS = [
  'Multi-Messenger Astronomy',
  'FITS Data Explorer',
  'Real-time Pipeline',
  'AI-Powered Analysis',
  '7 Sky Surveys',
  'GW Counterpart Search',
  'Electromagnetic Follow-up',
  'Deep Space Exploration',
]

// Precompute orbit positions — enlarged radius v4.14
const orbitPositions = ORBIT_TEXTS.map((_, i) => {
  const angle = (i / ORBIT_TEXTS.length) * 360
  const radius = 430
  const rad = (angle * Math.PI) / 180
  return {
    x: (Math.cos(rad) * radius).toFixed(2),
    y: (Math.sin(rad) * radius).toFixed(2),
  }
})

// Precompute 24 radial beams — avoid Array.from() on every render
const RADIAL_BEAMS = Array.from({ length: 24 }, (_, i) => {
  const deg = (i / 24) * 360
  return { key: 'beam-' + i, deg }
})

// Gravity ripple rings — upscaled v4.14
const RIPPLE_RINGS = [
  { r: 300, opacity: 0.07, delay: 0, duration: 10 },
  { r: 360, opacity: 0.09, delay: 2.5, duration: 10 },
  { r: 420, opacity: 0.06, delay: 5, duration: 10 },
]

// Einstein rings — upscaled gravitational lensing v4.14
const EINSTEIN_RINGS = [
  { r: 430, opacity: 0.06, borderWidth: 1 },
  { r: 470, opacity: 0.08, borderWidth: 1.5 },
  { r: 510, opacity: 0.05, borderWidth: 0.5 },
  { r: 550, opacity: 0.1, borderWidth: 2 },
]

export default function LandingPage() {
  const navigate = useNavigate()

  // R6.8c: Slow fade splash — show landing briefly (fullscreen, no cards),
  // then gently fade out and navigate to Abnormal Data. Total visible time
  // ~4.5s with a 1.4s ease fade so the title lingers then drifts away.
  const [leaving, setLeaving] = useState(false)
  // R6.35: show 'Skip to app' button after 1.5s in case auto-redirect is slow.
  const [showSkip, setShowSkip] = useState(false)
  useEffect(() => {
    const t1 = setTimeout(() => setLeaving(true), 4500)
    const t2 = setTimeout(() => navigate('/index', { replace: true }), 5900)
    const t3 = setTimeout(() => setShowSkip(true), 1500)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
    }
  }, [navigate])

  // prefers-reduced-motion — skip all animations when active
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  return (
    <div
      className='relative min-h-screen flex flex-col items-center justify-center px-4 py-12 overflow-hidden'
      style={{
        opacity: leaving ? 0 : 1,
        transition: 'opacity 1.4s ease-in-out',
      }}
    >
      {/* Aurora overlay — static, no animation */}
      <div
        className='absolute inset-0 z-0 pointer-events-none'
        aria-hidden='true'
        style={{
          background:
            'radial-gradient(ellipse 80% 60% at 20% 10%, rgba(124,58,237,0.15) 0%, transparent 50%), radial-gradient(ellipse 70% 50% at 80% 85%, rgba(0,240,255,0.12) 0%, transparent 50%), radial-gradient(ellipse 50% 40% at 50% 50%, rgba(255,0,110,0.06) 0%, transparent 60%)',
        }}
      />

      {/* GW Chirp Wave — gravitational wave visualization layer */}
      <GWChirpWave />

      {/* Hero Section — R6.8c: fullscreen centered (no cards below) */}
      <div className='relative z-10 text-center' style={{ marginTop: 0 }}>
        <div
          className='relative mx-auto mb-6'
          style={{
            width: 900,
            height: 900,
            maxWidth: '94vw',
            maxHeight: '94vw',
          }}
        >
          {/* === EINSTEIN RINGS — gravitational lensing (upscaled) === */}
          {EINSTEIN_RINGS.map(({ r, opacity, borderWidth }) => (
            <div
              key={'einstein-' + r}
              className='absolute rounded-full pointer-events-none'
              aria-hidden='true'
              style={{
                left: '50%',
                top: '50%',
                width: r * 2,
                height: r * 2,
                transform: 'translate(-50%, -50%)',
                border:
                  borderWidth +
                  'px solid rgba(0,240,255,' +
                  opacity.toFixed(3) +
                  ')',
                boxShadow:
                  '0 0 ' +
                  r * 0.35 +
                  'px rgba(0,240,255,' +
                  (opacity * 0.7).toFixed(3) +
                  '), inset 0 0 ' +
                  r * 0.3 +
                  'px rgba(124,58,237,' +
                  (opacity * 0.55).toFixed(3) +
                  ')',
                animation: 'einsteinRotate 90s linear infinite',
                opacity: opacity * 8,
              }}
            />
          ))}

          {/* === GRAVITY RIPPLE — expanding from center (upscaled) === */}
          {RIPPLE_RINGS.map(({ r, opacity, delay, duration }) => (
            <div
              key={'ripple-' + r}
              className='absolute rounded-full pointer-events-none gw-ripple'
              aria-hidden='true'
              style={{
                left: '50%',
                top: '50%',
                width: r * 2,
                height: r * 2,
                transform: 'translate(-50%, -50%)',
                border: '1px solid rgba(0,240,255,' + opacity.toFixed(3) + ')',
                boxShadow:
                  '0 0 ' +
                  r * 0.25 +
                  'px rgba(0,240,255,' +
                  opacity.toFixed(3) +
                  '), inset 0 0 ' +
                  r * 0.25 +
                  'px rgba(124,58,237,' +
                  (opacity * 0.85).toFixed(3) +
                  ')',
                animation: 'gwRipple ' + duration + 's ease-out infinite',
                animationDelay: delay + 's',
                opacity: 0,
              }}
            />
          ))}

          {/* === DUAL BLACK HOLES — smooth orbital rotation (v4.14) === */}
          <div
            className='absolute left-1/2 top-1/2 gw-bh-orbit'
            aria-hidden='true'
            style={{
              transform: 'translate(-50%, -50%)',
              animation: reducedMotion
                ? 'none'
                : 'blackHoleRotate 20s linear infinite',
            }}
          >
            {/* Primary BH — larger */}
            <div
              className='gw-bh absolute rounded-full'
              style={{
                width: 72,
                height: 72,
                left: -210,
                top: -12,
                transform: 'translate(-50%, -50%)',
                background:
                  'radial-gradient(circle at 40% 35%, rgba(100,60,200,0.75) 0%, rgba(20,5,50,0.95) 50%, #020010 100%)',
                boxShadow:
                  '0 0 90px rgba(124,58,237,0.6), 0 0 160px rgba(0,0,0,0.65), 0 0 25px rgba(0,240,255,0.3)',
              }}
            />
            {/* Secondary BH — smaller */}
            <div
              className='gw-bh absolute rounded-full'
              style={{
                width: 56,
                height: 56,
                left: 210,
                top: 0,
                transform: 'translate(-50%, -50%)',
                background:
                  'radial-gradient(circle at 35% 30%, rgba(0,200,255,0.65) 0%, rgba(10,5,40,0.95) 50%, #010015 100%)',
                boxShadow:
                  '0 0 70px rgba(0,240,255,0.5), 0 0 130px rgba(0,0,0,0.65), 0 0 20px rgba(124,58,237,0.35)',
              }}
            />
            {/* Accretion glow */}
            <div
              className='absolute pointer-events-none'
              style={{
                left: 0,
                top: -5,
                width: 420,
                height: 5,
                transform: 'translate(-50%, -50%)',
                background:
                  'linear-gradient(90deg, transparent, rgba(0,240,255,0.12) 20%, rgba(124,58,237,0.18) 50%, rgba(0,240,255,0.12) 80%, transparent)',
                filter: 'blur(6px)',
              }}
            />
          </div>

          {/* === RADIAL BEAMS — star pivot lines (upscaled) === */}
          {RADIAL_BEAMS.map(({ key, deg }) => (
            <div
              key={key}
              className='absolute pointer-events-none'
              style={{
                left: '50%',
                top: '50%',
                width: 1,
                height: 400,
                transform: 'translate(-50%, -100%) rotate(' + deg + 'deg)',
                transformOrigin: 'center bottom',
                background:
                  'linear-gradient(to top, rgba(0,240,255,0.14), transparent)',
                opacity: 0.5,
              }}
            />
          ))}

          {/* === ORBIT TEXT RING (upscaled radius) === */}
          {ORBIT_TEXTS.map((text, i) => {
            const pos = orbitPositions[i]
            return (
              <div
                key={text}
                aria-hidden='true'
                className='absolute pointer-events-none'
                style={{
                  left: '50%',
                  top: '50%',
                  width: 0,
                  height: 0,
                  transform: 'translate(' + pos.x + 'px, ' + pos.y + 'px)',
                }}
              >
                <span
                  className='orbit-ring-text block whitespace-nowrap text-base font-semibold tracking-wider'
                  style={{
                    transform: 'translate(-50%, -50%)',
                    color: 'rgba(255,255,255,0.52)',
                    textShadow:
                      '0 0 16px rgba(0,240,255,0.35), 0 0 32px rgba(124,58,237,0.20)',
                    animation: 'orbitFadeSpin 40s linear infinite',
                    animationDelay: -i * (40 / ORBIT_TEXTS.length) + 's',
                  }}
                >
                  {text}
                </span>
              </div>
            )
          })}

          {/* === CENTER TITLE — slow color-shifting gradient (v4.14) === */}
          <div className='absolute inset-0 flex flex-col items-center justify-center'>
            {/* Top decorative line */}
            <div
              className='mb-4 w-24 h-px rounded'
              aria-hidden='true'
              style={{
                background:
                  'linear-gradient(90deg, transparent, rgba(0,240,255,0.7), rgba(124,58,237,0.7), transparent)',
              }}
            />

            {/* Title — smaller, with slow color drift */}
            <h1
              className='landing-title text-center'
              style={{
                fontFamily:
                  '"Cormorant Garamond", "Georgia", "Times New Roman", serif',
                fontWeight: 600,
                fontSize: 'clamp(50px, 7vw, 120px)',
                lineHeight: 0.9,
                letterSpacing: '0.10em',
                textTransform: 'uppercase' as const,
                background:
                  'linear-gradient(180deg, #ffffff 0%, #d0e8ff 18%, #a0d0ff 36%, #7d68ff 54%, #b050e0 72%, #e880ff 100%)',
                backgroundSize: '100% 400%',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                textShadow:
                  '0 0 8px rgba(255,255,255,0.18), 0 0 24px rgba(120,170,255,0.10), 0 0 48px rgba(124,58,237,0.06)',
                animation: reducedMotion
                  ? 'landingFadeUp 1.2s ease'
                  : 'landingFadeUp 1.2s ease, landingTitleFlow 8s ease-in-out infinite alternate',
              }}
            >
              AliCPT
              <br />
              DIVS
            </h1>

            {/* Separator line */}
            <div
              className='my-5 w-32 h-px'
              aria-hidden='true'
              style={{
                background: 'rgba(255,255,255,0.22)',
              }}
            />

            {/* Bottom decorative bars */}
            <div
              className='mt-1 mx-auto w-48 h-0.5 rounded'
              aria-hidden='true'
              style={{
                background:
                  'linear-gradient(90deg, #5CE4FF, #7D68FF, #C04DFF, #7D68FF, #5CE4FF)',
              }}
            />
            <div
              className='mt-2 mx-auto w-24 h-0.5 rounded'
              aria-hidden='true'
              style={{
                background:
                  'linear-gradient(90deg, transparent, rgba(0,240,255,0.5), transparent)',
              }}
            />
          </div>
        </div>
      </div>

      {/* R6.35: 'Skip to app' button. Shows after 1.5s in case auto-redirect is slow. */}
      {showSkip && !leaving && (
        <button
          type='button'
          onClick={() => navigate('/index', { replace: true })}
          className='absolute bottom-8 right-8 z-20 px-5 py-2 rounded-lg text-sm font-semibold'
          style={{
            background: 'rgba(0,240,255,0.12)',
            border: '1px solid rgba(0,240,255,0.40)',
            color: 'rgba(0,240,255,1.0)',
            backdropFilter: 'blur(8px)',
            transition: 'all 200ms ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(0,240,255,0.25)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(0,240,255,0.12)'
          }}
        >
          Skip to app →
          <div
            style={{
              fontSize: 10,
              color: 'rgba(0,240,255,0.5)',
              marginTop: 4,
              fontWeight: 400,
            }}
          >
            (or Ctrl+Shift+R to hard refresh)
          </div>
        </button>
      )}
    </div>
  )
}
