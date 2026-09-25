// R6.104-K-B: histogram preview canvas. Bars are pointer-events:none so they
// NEVER block the main image render. Only the two draggable handles are
// interactive. The component NEVER synchronously computes the histogram
// itself — the parent must debounce + (if pixel count > 256x256) Web Worker.

import { useEffect, useRef, useCallback } from 'react'

interface HistogramProps {
  /** 256 bins, each in 0..maxCount. Null disables preview. */
  bins: Uint32Array | null
  minCut: number
  maxCut: number
  cutMode: 'percent' | 'absolute'
  onMinChange: (v: number) => void
  onMaxChange: (v: number) => void
  width?: number
  height?: number
}

const HANDLE_W = 8

export function Histogram({ bins, minCut, maxCut, cutMode, onMinChange, onMaxChange, width = 320, height = 80 }: HistogramProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const draggingRef = useRef<'min' | 'max' | null>(null)

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = 'rgba(0,0,0,0.4)'
    ctx.fillRect(0, 0, width, height)

    if (!bins || bins.length === 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.4)'
      ctx.font = '11px JetBrains Mono, monospace'
      ctx.textAlign = 'center'
      ctx.fillText('Histogram unavailable', width / 2, height / 2)
      return
    }

    const maxCount = Math.max(...bins)
    if (maxCount === 0) return
    const barW = width / bins.length
    ctx.fillStyle = 'rgba(0, 240, 255, 0.6)'
    for (let i = 0; i < bins.length; i++) {
      const h = (bins[i] / maxCount) * (height - 4)
      ctx.fillRect(i * barW, height - h - 2, Math.max(1, barW), h)
    }
  }, [bins, width, height])

  useEffect(() => { draw() }, [draw])

  const pxToCut = useCallback((px: number): number => {
    const t = Math.max(0, Math.min(1, px / width))
    if (cutMode === 'percent') return Math.round(t * 100 * 10) / 10  // 0..100 step 0.5
    return Math.round(t * 65535)
  }, [cutMode, width])

  const cutToPx = useCallback((v: number): number => {
    if (cutMode === 'percent') return (v / 100) * width
    return (v / 65535) * width
  }, [cutMode, width])

  const onMouseDown = (which: 'min' | 'max') => (e: React.MouseEvent) => {
    draggingRef.current = which
    e.preventDefault()
  }

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const canvas = canvasRef.current
      if (!canvas || !draggingRef.current) return
      const rect = canvas.getBoundingClientRect()
      const px = e.clientX - rect.left
      const v = pxToCut(px)
      if (draggingRef.current === 'min') onMinChange(v)
      else onMaxChange(v)
    }
    const onUp = () => { draggingRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [pxToCut, onMinChange, onMaxChange])

  if (!bins) {
    return <canvas ref={canvasRef} width={width} height={height}
                   style={{ display: 'block', borderRadius: 4 }} />
  }

  return (
    <div style={{ position: 'relative', width, height }}>
      <canvas ref={canvasRef} width={width} height={height}
              style={{ display: 'block', borderRadius: 4, pointerEvents: 'none' }} />
      {/* Min handle */}
      <div
        role='slider'
        aria-label='min cut handle'
        aria-valuenow={minCut}
        onMouseDown={onMouseDown('min')}
        style={{
          position: 'absolute',
          left: cutToPx(minCut) - HANDLE_W / 2,
          top: 0,
          width: HANDLE_W,
          height,
          cursor: 'ew-resize',
          pointerEvents: 'auto',
          background: 'rgba(0, 240, 255, 0.20)',
          borderLeft: '1px solid #00F0FF',
          borderRight: '1px solid #00F0FF',
        }}
      />
      {/* Max handle */}
      <div
        role='slider'
        aria-label='max cut handle'
        aria-valuenow={maxCut}
        onMouseDown={onMouseDown('max')}
        style={{
          position: 'absolute',
          left: cutToPx(maxCut) - HANDLE_W / 2,
          top: 0,
          width: HANDLE_W,
          height,
          cursor: 'ew-resize',
          pointerEvents: 'auto',
          background: 'rgba(255, 0, 110, 0.20)',
          borderLeft: '1px solid #FF006E',
          borderRight: '1px solid #FF006E',
        }}
      />
    </div>
  )
}
