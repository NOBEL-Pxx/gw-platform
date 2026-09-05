import { useEffect, useRef, useCallback } from 'react'

type QualityTier = 'low' | 'medium' | 'high'
const TIER_CONFIG: Record<
  QualityTier,
  { stars: number; fps: number; glow: boolean }
> = {
  low: { stars: 150, fps: 15, glow: false },
  medium: { stars: 400, fps: 30, glow: true },
  high: { stars: 800, fps: 60, glow: true },
}

// R6.27: GPU budget detection — picks initial tier based on device capabilities
// + prefers-reduced-motion. Used by Layout.tsx to seed `tier` state.
// eslint-disable-next-line react-refresh/only-export-components
export function detectGpuBudget(): QualityTier {
  if (typeof window === 'undefined') return 'medium'
  // Respect OS-level reduce-motion (a11y)
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
    return 'low'
  // Old/slow hardware: hardwareConcurrency < 4 (typical 2-core mobile / VM)
  const cores = navigator.hardwareConcurrency ?? 4
  // deviceMemory is only on Chromium; undefined elsewhere → assume 4 GB
  const mem = (navigator as { deviceMemory?: number }).deviceMemory ?? 4
  if (cores < 4 || mem < 2) return 'low'
  if (cores < 6 || mem < 4) return 'medium'
  return 'high'
}

interface Star {
  x: number
  y: number
  r: number
  baseAlpha: number
  alpha: number
  twinkleSpeed: number
  twinklePhase: number
}
interface StarfieldBackgroundProps {
  tier: QualityTier
  disabled: boolean
  meteors?: boolean
}

interface ShootingStar {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  maxLife: number
  length: number
}

const STAR_COLORS: string[] = []
function getStarColor(alpha: number): string {
  const key = Math.round(alpha * 100)
  if (!STAR_COLORS[key])
    STAR_COLORS[key] = 'rgba(200,220,255,' + (key / 100).toFixed(2) + ')'
  return STAR_COLORS[key]
}
const GLOW_COLORS: string[] = []
function getGlowColor(alpha: number): string {
  const key = Math.round(alpha * 100)
  if (!GLOW_COLORS[key])
    GLOW_COLORS[key] =
      'rgba(180,210,255,' + ((key / 100) * 0.08).toFixed(3) + ')'
  return GLOW_COLORS[key]
}

function createStars(count: number, w: number, h: number): Star[] {
  const stars: Star[] = []
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.random() * w,
      y: Math.random() * h,
      r: Math.random() * 1.8 + 0.2,
      baseAlpha: Math.random() * 0.5 + 0.3,
      alpha: 0,
      twinkleSpeed: Math.random() * 0.02 + 0.005,
      twinklePhase: Math.random() * Math.PI * 2,
    })
  }
  return stars
}

function spawnShootingStar(w: number, h: number): ShootingStar {
  const angle = (Math.random() * 60 - 30) * (Math.PI / 180)
  return {
    x: Math.random() * w * 0.8,
    y: Math.random() * h * 0.3,
    vx: Math.cos(angle) * (Math.random() * 6 + 4),
    vy: Math.sin(angle) * (Math.random() * 6 + 4) + 2,
    life: 0,
    maxLife: Math.random() * 80 + 60,
    length: Math.random() * 120 + 60,
  }
}

export default function StarfieldBackground({
  tier,
  disabled,
  meteors = false,
}: StarfieldBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const starsRef = useRef<Star[]>([])
  const shootingRef = useRef<ShootingStar[]>([])
  const frameRef = useRef(0)
  const dimsRef = useRef({ w: 0, h: 0 })
  const tierRef = useRef(tier)
  tierRef.current = tier
  const meteorsRef = useRef(meteors)
  meteorsRef.current = meteors
  const resize = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const { innerWidth: w, innerHeight: h } = window
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = w * dpr
    canvas.height = h * dpr
    canvas.style.width = w + 'px'
    canvas.style.height = h + 'px'
    dimsRef.current = { w, h }
    starsRef.current = createStars(TIER_CONFIG[tierRef.current].stars, w, h)
  }, [])

  const resizeTimeout = useRef<ReturnType<typeof setTimeout>>()
  const debouncedResize = useCallback(() => {
    if (resizeTimeout.current) clearTimeout(resizeTimeout.current)
    resizeTimeout.current = setTimeout(resize, 150)
  }, [resize])

  useEffect(() => {
    resize()
    window.addEventListener('resize', debouncedResize)
    return () => {
      window.removeEventListener('resize', debouncedResize)
      if (resizeTimeout.current) clearTimeout(resizeTimeout.current)
    }
  }, [resize, debouncedResize])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // v4.16: Complete disable — no canvas rendering at all
    if (disabled) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      return // No requestAnimationFrame, zero GPU usage
    }

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (motionQuery.matches) {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      for (const s of starsRef.current) {
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(200,220,255,' + s.baseAlpha.toFixed(2) + ')'
        ctx.fill()
      }
      return
    }

    let animId = 0,
      frameCount = 0
    const animate = () => {
      frameCount++
      const cfg = TIER_CONFIG[tierRef.current]
      if (frameCount % Math.round(60 / cfg.fps) !== 0) {
        animId = requestAnimationFrame(animate)
        return
      }
      const { w, h } = dimsRef.current
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      for (const s of starsRef.current) {
        s.alpha =
          s.baseAlpha +
          Math.sin(frameRef.current * s.twinkleSpeed + s.twinklePhase) * 0.25
        if (s.alpha < 0.05) s.alpha = 0.05
        else if (s.alpha > 1) s.alpha = 1
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = getStarColor(s.alpha)
        ctx.fill()
        if (cfg.glow && s.r > 1.5 && s.alpha > 0.55) {
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.r * 2.5, 0, Math.PI * 2)
          ctx.fillStyle = getGlowColor(s.alpha)
          ctx.fill()
        }
      }

      // v4.55: Meteors (shooting stars) — independent toggle, default OFF
      if (meteorsRef.current) {
        if (
          Math.random() < (cfg.fps >= 60 ? 0.005 : 0.003) &&
          shootingRef.current.length < 2
        ) {
          shootingRef.current.push(spawnShootingStar(w, h))
        }
        for (let i = shootingRef.current.length - 1; i >= 0; i--) {
          const ss = shootingRef.current[i]
          ss.x += ss.vx
          ss.y += ss.vy
          ss.life++
          const p = ss.life / ss.maxLife
          const alpha = p < 0.2 ? p / 0.2 : (1 - p) / 0.8
          ctx.beginPath()
          ctx.moveTo(ss.x, ss.y)
          ctx.lineTo(
            ss.x - ss.vx * ss.length * 0.05,
            ss.y - ss.vy * ss.length * 0.05,
          )
          ctx.strokeStyle = 'rgba(255,255,255,' + alpha.toFixed(2) + ')'
          ctx.lineWidth = 1.5
          ctx.stroke()
          if (ss.life >= ss.maxLife || ss.x < -100 || ss.y > h + 100)
            shootingRef.current.splice(i, 1)
        }
      } else {
        shootingRef.current.length = 0
      }

      frameRef.current++
      animId = requestAnimationFrame(animate)
    }
    animId = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animId)
  }, [disabled])

  return (
    <canvas
      ref={canvasRef}
      className='fixed inset-0 z-0 pointer-events-none'
      style={{ background: '#0A0F1E' }}
      aria-hidden='true'
    />
  )
}
