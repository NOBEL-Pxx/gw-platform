// R6.104-K: 3x3 + 1 grid of color-swatch buttons. Each swatch is a small
// inline canvas painted with that LUT sampled from a synthetic gradient
// (so the swatch is representative of how a typical image looks with that
// colormap, not just a flat color).

import { useMemo } from 'react'
import { COLORMAP_LABELS, type ColorTable } from './types'

interface ColorPaletteGridProps {
  value: ColorTable
  onChange: (next: ColorTable) => void
  /** Compact mode shows 3x3 grid (hides Native which is rarely used). */
  compact?: boolean
}

// Sample a 1D LUT into a canvas via putImageData.
function paintSwatch(lutName: ColorTable): string {
  const lut = LUT_FACTORIES[lutName]
  const stops = lut(64)
  // Render as a horizontal gradient (24x8 pixel swatch).
  const canvas = document.createElement('canvas')
  canvas.width = 24
  canvas.height = 8
  const ctx = canvas.getContext('2d')!
  for (let i = 0; i < 24; i++) {
    const t = i / 23
    const idx = Math.floor(t * (stops.length - 1))
    const [r, g, b] = stops[idx]
    ctx.fillStyle = `rgb(${r | 0},${g | 0},${b | 0})`
    ctx.fillRect(i, 0, 1, 8)
  }
  return canvas.toDataURL()
}

// Inline LUTs (subset matching Firefly's {Viridis, Plasma, Inferno, Magma, ...}).
// Each factory returns 64 stops [r, g, b] in 0..255.
const LUT_FACTORIES: Record<ColorTable, (n: number) => Array<[number, number, number]>> = {
  viridis: (n) => lerpStops([
    [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37],
  ], n),
  plasma: (n) => lerpStops([
    [13, 8, 135], [126, 3, 168], [203, 70, 121], [248, 149, 64], [240, 249, 33],
  ], n),
  inferno: (n) => lerpStops([
    [0, 0, 4], [87, 15, 109], [187, 55, 84], [249, 142, 9], [252, 255, 164],
  ], n),
  magma: (n) => lerpStops([
    [0, 0, 4], [80, 18, 123], [183, 55, 121], [251, 136, 97], [252, 253, 191],
  ], n),
  cividis: (n) => lerpStops([
    [0, 32, 76], [48, 92, 119], [120, 145, 110], [200, 191, 75], [255, 237, 0],
  ], n),
  cubehelix: (n) => cubehelixStops(n),
  parula: (n) => lerpStops([
    [52, 53, 121], [63, 96, 174], [93, 161, 213], [176, 219, 217], [255, 255, 128],
  ], n),
  grayscale: (n) => Array.from({ length: n }, (_, i) => {
    const v = (i / (n - 1)) * 255
    return [v, v, v] as [number, number, number]
  }),
  rainbow: (n) => Array.from({ length: n }, (_, i) => {
    const h = (i / n) * 360
    const [r, g, b] = hsvToRgb(h, 1, 1)
    return [r, g, b] as [number, number, number]
  }),
  native: (n) => Array.from({ length: n }, () => [128, 128, 128] as [number, number, number]),
}

function lerpStops(stops: Array<[number, number, number]>, n: number) {
  const out: Array<[number, number, number]> = []
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1) * (stops.length - 1)
    const lo = Math.floor(t)
    const hi = Math.min(lo + 1, stops.length - 1)
    const f = t - lo
    out.push([
      stops[lo][0] + (stops[hi][0] - stops[lo][0]) * f,
      stops[lo][1] + (stops[hi][1] - stops[lo][1]) * f,
      stops[lo][2] + (stops[hi][2] - stops[lo][2]) * f,
    ])
  }
  return out
}

function cubehelixStops(n: number) {
  // Simple cubehelix approximation (Green 2011).
  const out: Array<[number, number, number]> = []
  const start = 0.5, rotations = -1.5, hue = 1.0, gamma = 1.0
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1)
    const angle = 2 * Math.PI * (start / 3 + rotations * t)
    const c = Math.cos(angle), s = Math.sin(angle)
    const v = Math.pow(t, gamma)
    const r = v * (hue + c * (1 - hue)) * 255
    const g = v * (hue + s * 0.5 * (1 - hue) - c * 0.3 * (1 - hue)) * 255
    const b = v * (hue - s * 0.5 * (1 - hue) - c * 0.2 * (1 - hue)) * 255
    out.push([Math.max(0, Math.min(255, r)), Math.max(0, Math.min(255, g)), Math.max(0, Math.min(255, b))])
  }
  return out
}

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0, g = 0, b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255]
}

export function ColorPaletteGrid({ value, onChange, compact = false }: ColorPaletteGridProps) {
  const options = useMemo(() => {
    const all = Object.keys(COLORMAP_LABELS) as ColorTable[]
    return compact ? all.filter((c) => c !== 'native') : all
  }, [compact])
  const swatches = useMemo(() => options.map((c) => ({ key: c, dataUrl: paintSwatch(c) })), [options])
  return (
    <div role='radiogroup' aria-label='Color palette'
         className='grid gap-1' style={{ gridTemplateColumns: 'repeat(5, 24px)' }}>
      {swatches.map(({ key, dataUrl }) => {
        const selected = key === value
        return (
          <button
            key={key}
            type='button'
            role='radio'
            aria-checked={selected}
            aria-label={COLORMAP_LABELS[key]}
            title={COLORMAP_LABELS[key]}
            onClick={() => onChange(key)}
            style={{
              width: 24,
              height: 24,
              borderRadius: 3,
              border: selected ? '2px solid #00F0FF' : '1px solid rgba(255,255,255,0.20)',
              padding: 0,
              cursor: 'pointer',
              background: `url(${dataUrl}) center/cover no-repeat, rgba(0,0,0,0.4)`,
            }}
          />
        )
      })}
    </div>
  )
}
