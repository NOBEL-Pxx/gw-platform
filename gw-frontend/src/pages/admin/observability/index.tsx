// R6.45: Admin observability dashboard (font errors + A/B test).
// Visualizes /pipeline/observability/font-errors/stats and /ab-dashboard.

import React, { useEffect, useState, useCallback } from 'react'
import {
  Card,
  Table,
  Tag,
  Spin,
  Empty,
  Statistic,
  Row,
  Col,
  Space,
  Button,
  Select,
  Modal,
  Form,
  Input,
  message,
  Slider,
  InputNumber,
} from 'antd'
import {
  ReloadOutlined,
  TrophyOutlined,
  AlertOutlined,
  CloseCircleOutlined,
  FileImageOutlined,
  FilePdfOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  GlobalOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { sentryConfig } from '@/sentry'

interface FontErrorStat {
  family: string
  weight: string
  count: number
  last_seen: number
}

interface FontErrorStats {
  total: number
  by_family_weight: FontErrorStat[]
}

interface ABGroupSummary {
  count: number
  load_time_ms: { avg: number; median: number; p95: number }
  fcp_ms: { avg: number; p95: number }
  cls: { avg: number; p95: number }
}

interface ABDashboard {
  total_samples: number
  analysis_ready: boolean
  groups: Record<string, ABGroupSummary>
  winner: string | null
  winner_delta_ms: number
  queried_at: number
}

interface ABHistoryBucket {
  bucket_ts: number
  woff2_count: number
  woff2_load_median_ms: number
  woff2_load_avg_ms: number
  woff2_fcp_avg_ms: number
  woff2_cls_avg: number
  system_count: number
  system_load_median_ms: number
  system_load_avg_ms: number
  system_fcp_avg_ms: number
  system_cls_avg: number
  winner: 'woff2' | 'system' | 'tie' | null
  delta_ms: number
}

interface ABHistory {
  bucket_ms: number
  window_ms: number
  buckets: ABHistoryBucket[]
  queried_at: number
}

interface Alert {
  id: number
  type: string
  alert_key: string
  severity: string
  message: string
  fired_at: number
  dismissed_at: number | null
  last_value: number
  occurrences: number
}

interface AlertRoute {
  family: string
  pagerduty_routing_key: string
  team_email: string
  created_at: number
  updated_at: number
}

interface AuditEntry {
  id: number
  family: string
  action: 'upsert' | 'delete'
  actor: string
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  ts: number
  // R6.53 #1: backend returns match_field + match_offset for search results
  match_field?:
    'family' | 'action' | 'actor' | 'before_json' | 'after_json' | null
  match_offset?: number
}

// R6.53 #1: highlight match_offset..match_offset+q.length with <mark>
// Falls back to plain text when no match_offset (e.g. non-search audit table).
function highlightMatch(
  text: string,
  offset?: number,
  q?: string,
): React.ReactNode {
  if (offset == null || offset < 0 || !q) return text
  const before = text.slice(0, offset)
  const hit = text.slice(offset, offset + q.length)
  const after = text.slice(offset + q.length)
  if (!hit) return text
  return (
    <>
      {before}
      <mark
        style={{
          background: '#fde68a',
          color: '#1f2937',
          padding: '0 2px',
          borderRadius: 2,
        }}
      >
        {hit}
      </mark>
      {after}
    </>
  )
}

function formatMs(ms: number | null | undefined, digits = 0): string {
  if (ms == null) return '-'
  return `${ms.toFixed(digits)} ms`
}

function formatTs(ts: number): string {
  if (!ts) return '-'
  return new Date(ts).toLocaleString()
}

// R6.46: SVG-based time-series chart for AB history (zero deps).
const ABHistoryChart = React.forwardRef<
  SVGSVGElement,
  { history: ABHistory | null }
>(function ABHistoryChart({ history }, ref) {
  const W = 1000
  const H = 320
  const PAD = { top: 24, right: 24, bottom: 40, left: 56 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  if (!history || history.buckets.length === 0) {
    return (
      <Empty
        description={
          <span className='text-white/45'>
            No AB history yet (need more samples over time)
          </span>
        }
      />
    )
  }

  const buckets = history.buckets
  const tMin = buckets[0].bucket_ts
  const tMax = buckets[buckets.length - 1].bucket_ts
  const tSpan = Math.max(1, tMax - tMin)

  const allValues = buckets
    .flatMap((b) => [b.woff2_load_median_ms, b.system_load_median_ms])
    .filter((v) => v > 0)
  const yMax = Math.max(1, ...allValues) * 1.1
  const yMin = 0

  const xScale = (t: number) => PAD.left + ((t - tMin) / tSpan) * innerW
  const yScale = (v: number) =>
    PAD.top + innerH - ((v - yMin) / (yMax - yMin)) * innerH

  const woff2Points = buckets
    .filter((b) => b.woff2_load_median_ms > 0)
    .map((b) => `${xScale(b.bucket_ts)},${yScale(b.woff2_load_median_ms)}`)
    .join(' ')

  const systemPoints = buckets
    .filter((b) => b.system_load_median_ms > 0)
    .map((b) => `${xScale(b.bucket_ts)},${yScale(b.system_load_median_ms)}`)
    .join(' ')

  // Y axis ticks (5 lines)
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((p) => {
    const y = PAD.top + innerH - p * innerH
    const v = p * yMax
    return { y, label: `${v.toFixed(0)}ms` }
  })

  // X axis ticks (every ~14% of timeline, max 7)
  const xTickCount = Math.min(7, buckets.length)
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const idx = Math.floor(
      (i / Math.max(1, xTickCount - 1)) * (buckets.length - 1),
    )
    const b = buckets[idx]
    const date = new Date(b.bucket_ts)
    const label = `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:00`
    return { x: xScale(b.bucket_ts), label }
  })

  return (
    <svg
      ref={ref}
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{
        background: '#0A0F1E',
        width: '100%',
        height: 'auto',
        maxWidth: W,
      }}
    >
      {/* Y grid + labels */}
      {yTicks.map((t, i) => (
        <g key={`yt-${i}`}>
          <line
            x1={PAD.left}
            y1={t.y}
            x2={PAD.left + innerW}
            y2={t.y}
            stroke='#1a2a3f'
            strokeWidth={1}
          />
          <text
            x={PAD.left - 8}
            y={t.y + 4}
            textAnchor='end'
            fontSize={10}
            fill='#888'
          >
            {t.label}
          </text>
        </g>
      ))}
      {/* X labels */}
      {xTicks.map((t, i) => (
        <text
          key={`xt-${i}`}
          x={t.x}
          y={H - 12}
          textAnchor='middle'
          fontSize={10}
          fill='#888'
        >
          {t.label}
        </text>
      ))}
      {/* Woff2 line */}
      {woff2Points && (
        <polyline
          points={woff2Points}
          fill='none'
          stroke='#52c41a'
          strokeWidth={2}
        />
      )}
      {/* System line */}
      {systemPoints && (
        <polyline
          points={systemPoints}
          fill='none'
          stroke='#fa8c16'
          strokeWidth={2}
        />
      )}
      {/* Legend */}
      <g transform={`translate(${PAD.left}, ${PAD.top - 12})`}>
        <rect x={0} y={-6} width={10} height={2} fill='#52c41a' />
        <text x={14} y={-2} fontSize={11} fill='#bbb'>
          woff2
        </text>
        <rect x={60} y={-6} width={10} height={2} fill='#fa8c16' />
        <text x={74} y={-2} fontSize={11} fill='#bbb'>
          system
        </text>
        <text x={140} y={-2} fontSize={11} fill='#666'>
          {buckets.length} buckets · {history.bucket_ms / 60000}m each
        </text>
      </g>
      {/* Axes */}
      <line
        x1={PAD.left}
        y1={PAD.top}
        x2={PAD.left}
        y2={PAD.top + innerH}
        stroke='#1a2a3f'
      />
      <line
        x1={PAD.left}
        y1={PAD.top + innerH}
        x2={PAD.left + innerW}
        y2={PAD.top + innerH}
        stroke='#1a2a3f'
      />
    </svg>
  )
})

export default function AdminObservabilityPage() {
  const [fontStats, setFontStats] = useState<FontErrorStats | null>(null)
  const [abDashboard, setAbDashboard] = useState<ABDashboard | null>(null)
  const [abHistory, setAbHistory] = useState<ABHistory | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [pdfMode, setPdfMode] = useState<'single' | 'per-day' | 'per-week'>(
    'single',
  )
  // R6.49: PDF watermark mode (none / draft / final)
  const [watermark, setWatermark] = useState<
    'none' | 'draft' | 'final' | 'custom'
  >('none')
  const [watermarkText, setWatermarkText] = useState('CONFIDENTIAL')
  const [watermarkColor, setWatermarkColor] = useState('#0066cc')
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.15)
  const [watermarkRows, setWatermarkRows] = useState(1)
  const [watermarkCols, setWatermarkCols] = useState(1)
  const [watermarkRotation, setWatermarkRotation] = useState(-45)
  const [auditSearch, setAuditSearch] = useState('')
  const [retentionDays, setRetentionDays] = useState(90)
  // R6.57: PurgeResult mirrors /audit/retention/purge response shape
  interface PurgeResult {
    deleted_count: number
    kept_count: number
    purged_by?: string
  }
  const [purgeResult, setPurgeResult] = useState<PurgeResult | null>(null)
  const [auditNextCursor, setAuditNextCursor] = useState<string | null>(null)
  const [auditHasMore, setAuditHasMore] = useState(false)
  const [auditLoading, setAuditLoading] = useState(false)
  const [batchVerifyOpen, setBatchVerifyOpen] = useState(false)
  const [batchVerifyInput, setBatchVerifyInput] = useState('')
  // R6.57: BatchVerifyResult is rendered as JSON dump, so keep loose typing
  // until we add a proper table; `unknown` is the safe default per TS strict rules.
  const [batchVerifyResult, setBatchVerifyResult] = useState<unknown>(null)
  // R6.49: actor name (persisted in localStorage, used for audit log)
  const [actor] = useState<string>(
    () =>
      (typeof localStorage !== 'undefined' &&
        localStorage.getItem('observability-actor')) ||
      'dashboard-user',
  )
  React.useEffect(() => {
    try {
      localStorage.setItem('observability-actor', actor)
    } catch {
      // localStorage may throw in private mode; silent ignore
    }
  }, [actor])
  const [lastRefresh, setLastRefresh] = useState<number>(0)
  const chartRef = React.useRef<SVGSVGElement>(null)
  // R6.48: alert routing UI state
  const [routing, setRouting] = useState<AlertRoute[]>([]) // R6.49: audit history state
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [auditFamilyFilter, setAuditFamilyFilter] = useState<string>('')

  const [routeModalOpen, setRouteModalOpen] = useState(false)
  const [editingRoute, setEditingRoute] = useState<AlertRoute | null>(null)
  const [routeForm] = Form.useForm()
  const [messageApi, messageContextHolder] = message.useMessage()

  const refresh = useCallback(async () => {
    setLoading(true)
    fetchRouting()
    fetchAudit(auditFamilyFilter || undefined)
    try {
      const [fRes, aRes, hRes, alertRes] = await Promise.all([
        fetch('/pipeline/observability/font-errors/stats'),
        fetch('/pipeline/observability/ab-dashboard'),
        fetch(
          '/pipeline/observability/ab-history?bucket_ms=3600000&window_ms=604800000',
        ),
        fetch('/pipeline/observability/alerts?active_only=true&limit=20'),
      ])
      if (fRes.ok) setFontStats(await fRes.json())
      if (aRes.ok) setAbDashboard(await aRes.json())
      if (hRes.ok) setAbHistory(await hRes.json())
      if (alertRes.ok) {
        const data = await alertRes.json()
        setAlerts(data.alerts || [])
      }
      setLastRefresh(Date.now())
    } catch (e) {
      console.warn('observability refresh failed', e)
    } finally {
      setLoading(false)
    }
    // R6.57: fetchAudit/fetchRouting hoisted later; preserve original empty deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // R6.48: fetch alert routing list
  const fetchRouting = useCallback(async () => {
    try {
      const res = await fetch('/pipeline/observability/alert-routing')
      if (res.ok) {
        const data = await res.json()
        setRouting(data.routing || [])
      }
    } catch (e) {
      console.warn('fetch routing failed', e)
    }
  }, [])

  // R6.50: full-text audit search
  const fetchAuditSearch = useCallback(
    async (q: string, append = false, cursor?: string | null) => {
      if (!q || !q.trim()) return
      setAuditLoading(true)
      try {
        const cursorParam = cursor
          ? `&cursor=${encodeURIComponent(cursor)}`
          : ''
        const res = await fetch(
          `/pipeline/observability/audit/search?q=${encodeURIComponent(q)}&limit=50${cursorParam}`,
        )
        if (res.ok) {
          const data = await res.json()
          setAudit((prev) =>
            append ? [...prev, ...(data.audit || [])] : data.audit || [],
          )
          setAuditNextCursor(data.next_cursor || null)
          setAuditHasMore(!!data.has_more)
        }
      } catch (_e) {
        /* ignore */
      } finally {
        setAuditLoading(false)
      }
    },
    [],
  )

  const handlePurgeAudit = useCallback(async () => {
    try {
      const res = await fetch(
        `/pipeline/observability/audit/retention/purge?retention_days=${retentionDays}`,
        {
          method: 'POST',
          headers: { 'X-Actor': actor },
        },
      )
      if (res.ok) {
        const data = await res.json()
        setPurgeResult(data)
        messageApi.success(
          `Purged ${data.deleted_count} entries (kept ${data.kept_count})`,
        )
        fetchAudit()
      } else {
        messageApi.error('Purge failed')
        setPurgeResult(null)
      }
    } catch (e) {
      messageApi.error(`Purge error: ${e}`)
    }
    // R6.57: fetchAudit hoisted later; preserve original deps to avoid tsc error.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retentionDays, actor, messageApi])

  const handleSignPDF = useCallback(
    async (pdfText: string) => {
      try {
        const res = await fetch('/pipeline/pdf/sign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Actor': actor },
          body: JSON.stringify({ pdf_text: pdfText, filename: 'export.pdf' }),
        })
        if (res.ok) {
          const data = await res.json()
          messageApi.success(`Signed: ${data.sha256_prefix}...`)
          return data
        }
        messageApi.error('Sign failed')
        return null
      } catch (e) {
        messageApi.error(`Sign error: ${e}`)
        return null
      }
    },
    [actor, messageApi],
  )

  // R6.51: fetch audit history (filtered) - cursor pagination
  const fetchAudit = useCallback(
    async (family?: string, append = false, cursor?: string | null) => {
      try {
        setAuditLoading(true)
        const params = new URLSearchParams()
        params.set('limit', '100')
        if (family) params.set('family', family)
        if (cursor) params.set('cursor', cursor)
        const res = await fetch(
          '/pipeline/observability/alert-routing/audit?' + params.toString(),
        )
        if (res.ok) {
          const data = await res.json()
          setAudit((prev) =>
            append ? [...prev, ...(data.audit || [])] : data.audit || [],
          )
          setAuditNextCursor(data.next_cursor || null)
          setAuditHasMore(!!data.has_more)
        }
      } catch (e) {
        console.warn('fetch audit failed', e)
      } finally {
        setAuditLoading(false)
      }
    },
    [],
  )

  // R6.48: open add modal
  const openAddRoute = useCallback(() => {
    setEditingRoute(null)
    routeForm.resetFields()
    setRouteModalOpen(true)
  }, [routeForm])

  // R6.48: open edit modal pre-filled
  const openEditRoute = useCallback(
    (r: AlertRoute) => {
      setEditingRoute(r)
      routeForm.setFieldsValue({
        family: r.family,
        pagerduty_routing_key: r.pagerduty_routing_key,
        team_email: r.team_email || '',
      })
      setRouteModalOpen(true)
    },
    [routeForm],
  )

  // R6.48: submit modal (PUT)
  const submitRoute = useCallback(async () => {
    try {
      const values = await routeForm.validateFields()
      const res = await fetch('/pipeline/observability/alert-routing', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Actor': actor },
        body: JSON.stringify(values),
      })
      if (res.ok) {
        messageApi.success('Route ' + values.family + ' saved')
        setRouteModalOpen(false)
        fetchRouting()
        fetchAudit(auditFamilyFilter || undefined)
      } else {
        const err = await res.text()
        messageApi.error('Save failed: ' + err.slice(0, 200))
      }
    } catch (e) {
      // validateFields rejection handled by antd
      console.warn('submit route', e)
    }
    // R6.57: fetchAudit/auditFamilyFilter/actor hoisted later. Original deps preserved.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeForm, fetchRouting, messageApi])

  // R6.48: delete a route
  const deleteRouteRow = useCallback(
    async (family: string) => {
      try {
        const res = await fetch(
          '/pipeline/observability/alert-routing/' + encodeURIComponent(family),
          {
            method: 'DELETE',
            headers: { 'X-Actor': actor },
          },
        )
        if (res.ok) {
          messageApi.success('Route ' + family + ' deleted')
          fetchRouting()
          fetchAudit(auditFamilyFilter || undefined)
        }
      } catch (e) {
        console.warn('delete route', e)
      }
    },
    // R6.57: same hoisting limitation as submitRoute above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fetchRouting, messageApi],
  )

  const dismissAlert = useCallback(async (alertId: number) => {
    try {
      const res = await fetch(
        `/pipeline/observability/alerts/${alertId}/dismiss`,
        { method: 'POST' },
      )
      if (res.ok) {
        setAlerts((prev) => prev.filter((a) => a.id !== alertId))
      }
    } catch (e) {
      console.warn('dismiss alert failed', e)
    }
  }, [])

  // R6.46: PNG export — serialize SVG chart to PNG via Canvas API (zero deps)
  const exportPNG = useCallback(async () => {
    if (!chartRef.current) return
    setExporting(true)
    try {
      const svgEl = chartRef.current
      const svgRect = svgEl.getBoundingClientRect()
      const svgData = new XMLSerializer().serializeToString(svgEl)
      const svgBlob = new Blob([svgData], {
        type: 'image/svg+xml;charset=utf-8',
      })
      const url = URL.createObjectURL(svgBlob)
      const img = new Image()
      img.crossOrigin = 'anonymous'
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('Failed to load SVG into image'))
        img.src = url
      })
      const scale = 2 // 2x for retina/print quality
      const canvas = document.createElement('canvas')
      canvas.width = svgRect.width * scale
      canvas.height = svgRect.height * scale
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas 2D context not available')
      ctx.fillStyle = '#0F1626'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      canvas.toBlob((blob) => {
        if (!blob) return
        const dlUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = dlUrl
        a.download = `gw-observability-${new Date().toISOString().slice(0, 10)}.png`
        a.click()
        URL.revokeObjectURL(dlUrl)
      }, 'image/png')
    } catch (e) {
      console.warn('PNG export failed', e)
      alert('PNG export failed: ' + (e as Error).message)
    } finally {
      setExporting(false)
    }
  }, [])

  // R6.47: PDF export — supports multi-page mode via pdfMode state — render SVG to canvas then embed in print dialog (zero deps)
  const exportPDF = useCallback(async () => {
    if (!chartRef.current) return
    setExporting(true)
    try {
      const svgEl = chartRef.current
      const svgRect = svgEl.getBoundingClientRect()
      const svgData = new XMLSerializer().serializeToString(svgEl)
      const svgBlob = new Blob([svgData], {
        type: 'image/svg+xml;charset=utf-8',
      })
      const url = URL.createObjectURL(svgBlob)
      const img = new Image()
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('Failed to load SVG'))
        img.src = url
      })
      const scale = 2
      const canvas = document.createElement('canvas')
      canvas.width = svgRect.width * scale
      canvas.height = svgRect.height * scale
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas 2D context not available')
      ctx.fillStyle = '#0F1626'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      // R6.47: Multi-page mode (per-day or per-week) — generate N pages.
      // Each page contains a date header + date-filtered chart.
      // Single mode: just one page (same as R6.46).
      const buckets = abHistory?.buckets || []
      const groups: Array<{ label: string; buckets: typeof buckets }> = []
      if (pdfMode === 'single' || buckets.length === 0) {
        groups.push({
          label: `All data (${abHistory?.window_ms ? Math.round(abHistory.window_ms / 86400000) : 7} days)`,
          buckets,
        })
      } else if (pdfMode === 'per-day') {
        const dayMap = new Map<string, typeof buckets>()
        buckets.forEach((b) => {
          const d = new Date(b.bucket_ts)
          const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
          if (!dayMap.has(key)) dayMap.set(key, [])
          dayMap.get(key)!.push(b)
        })
        dayMap.forEach((b, k) => groups.push({ label: k, buckets: b }))
        groups.sort((a, b) => a.label.localeCompare(b.label))
      } else if (pdfMode === 'per-week') {
        const weekMap = new Map<string, typeof buckets>()
        buckets.forEach((b) => {
          const d = new Date(b.bucket_ts)
          const startOfWeek = new Date(d)
          startOfWeek.setDate(d.getDate() - d.getDay())
          const key = `Week of ${startOfWeek.getFullYear()}-${String(startOfWeek.getMonth() + 1).padStart(2, '0')}-${String(startOfWeek.getDate()).padStart(2, '0')}`
          if (!weekMap.has(key)) weekMap.set(key, [])
          weekMap.get(key)!.push(b)
        })
        weekMap.forEach((b, k) => groups.push({ label: k, buckets: b }))
        groups.sort((a, b) => a.label.localeCompare(b.label))
      }

      // R6.49: Watermark overlay (declared before cover/toc/data pages)
      const watermarkOverlay = (() => {
        if (watermark === 'draft')
          return '<div class="watermark-draft">DRAFT</div>'
        if (watermark === 'final')
          return '<div class="watermark-final">FINAL</div>'
        if (watermark === 'custom' && watermarkText) {
          const tiles: string[] = []
          const cols = Math.max(1, Math.min(watermarkCols, 8))
          const rows = Math.max(1, Math.min(watermarkRows, 8))
          const w = 100 / cols
          const h = 100 / rows
          for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
              const top = h * r + h / 2
              const left = w * c + w / 2
              tiles.push(
                `<div class="watermark-tile" style="top: ${top}%; left: ${left}%; transform: translate(-50%, -50%) rotate(${watermarkRotation}deg); color: ${watermarkColor}; opacity: ${watermarkOpacity};">${watermarkText}</div>`,
              )
            }
          }
          return tiles.join('')
        }
        return ''
      })()
      // R6.48: Cover page + TOC + data pages
      const generatedAt = new Date().toLocaleString()
      const coverHtml = `
<div class="pdf-page pdf-cover">
  ${watermarkOverlay}
  <h1 style="font-size:32px;text-align:center;margin-top:80px">GravitationalWave</h1>
  <h2 style="text-align:center;color:#666;font-weight:400">Observability Report</h2>
  <div style="text-align:center;margin:60px 0">
    <div class="meta">Generated: ${generatedAt}</div>
    <div class="meta">Mode: ${pdfMode} &middot; ${groups.length} page${groups.length !== 1 ? 's' : ''}</div>
    <div class="meta">Data window: ${abHistory?.window_ms ? Math.round(abHistory.window_ms / 86400000) : 7} days &middot; ${abHistory?.buckets?.length || 0} buckets</div>
  </div>
  <div class="kv" style="justify-content:center">
    <div><strong>Total AB samples</strong>${abDashboard?.total_samples ?? 0}</div>
    <div><strong>Winner</strong>${abDashboard?.winner ?? 'none'}</div>
    <div><strong>Delta (ms)</strong>${abDashboard?.winner_delta_ms ?? 0}</div>
    <div><strong>Active alerts</strong>${alerts.length}</div>
    <div><strong>Font errors</strong>${fontStats?.total ?? 0}</div>
  </div>
  <p style="text-align:center;color:#999;font-size:11px;margin-top:120px">
    Generated by GravitationalWave Observability Dashboard (R6.48 multi-page)<br/>
    For interactive version visit /admin/observability
  </p>
</div>`

      // TOC page: list groups with index
      const tocRows = groups
        .map(
          (g, idx) => `
  <tr>
    <td style="width:40px;font-weight:bold">${idx + 1}</td>
    <td>${g.label}</td>
    <td style="text-align:right;color:#888">${g.buckets.length} buckets</td>
  </tr>`,
        )
        .join('')
      const tocHtml = `
<div class="pdf-page pdf-toc">
  ${watermarkOverlay}
  <h1>Contents</h1>
  <table style="width:100%;margin-top:24px;border-collapse:collapse">
    <thead>
      <tr style="border-bottom:2px solid #1a2a3f">
        <th style="text-align:left;padding:8px">#</th>
        <th style="text-align:left;padding:8px">Period</th>
        <th style="text-align:right;padding:8px">Data points</th>
      </tr>
    </thead>
    <tbody>${tocRows}</tbody>
  </table>
  <p style="color:#888;font-size:11px;margin-top:48px">Page numbers match PDF document order (cover = page 1, TOC = page 2, data pages start at page 3).</p>
</div>`

      const pageHtml = groups
        .map(
          (g, idx) => `
<div class="pdf-page">
  ${watermarkOverlay}
  <h1>GravitationalWave Observability Report — ${g.label}</h1>
  <div class="meta">Page ${idx + 3} of ${groups.length + 2} &middot; ${g.buckets.length} buckets &middot; Generated ${generatedAt}</div>
  ${
    idx === 0
      ? `<div class="kv">
    <div><strong>Total AB samples</strong>${abDashboard?.total_samples ?? 0}</div>
    <div><strong>Winner</strong>${abDashboard?.winner ?? 'none'}</div>
    <div><strong>Delta (ms)</strong>${abDashboard?.winner_delta_ms ?? 0}</div>
    <div><strong>Active alerts</strong>${alerts.length}</div>
    <div><strong>Font errors</strong>${fontStats?.total ?? 0}</div>
  </div>`
      : ''
  }
  <h2>A/B Test Load Time Trend (${g.label})</h2>
  ${
    g.buckets.length > 0
      ? `<div style="text-align:center;color:#888;font-size:12px;margin:24px 0">[Chart for ${g.label}: ${g.buckets.length} buckets, woff2 median=${g.buckets[g.buckets.length - 1].woff2_load_median_ms}ms]</div>`
      : '<p style="color:#888;font-style:italic">No data for this period</p>'
  }
</div>`,
        )
        .join('')

      const printHtml = `<!DOCTYPE html><html><head><title>GravitationalWave Observability Report (${pdfMode})</title>
<style>
@page { size: A4 landscape; margin: 1cm; }
body { font-family: -apple-system, sans-serif; background: white; color: #1a1a1a; margin: 0; padding: 0; }
.pdf-page { page-break-after: always; padding: 24px; min-height: 90vh; box-sizing: border-box; }
.pdf-page:last-child { page-break-after: auto; }
.pdf-cover { background: linear-gradient(135deg, #fafafa 0%, #e8eef5 100%); }
.pdf-cover h1 { border: none; }
.pdf-toc table th, .pdf-toc table td { padding: 8px 12px; }
.pdf-watermark { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-45deg); font-size: 120px; font-weight: bold; opacity: 0.12; pointer-events: none; z-index: 100; letter-spacing: 8px; }
.watermark-tile {
  position: absolute;
  font-size: 64px; font-weight: 900;
  pointer-events: none; z-index: 100;
  white-space: nowrap; letter-spacing: 4px;
}
.watermark-custom {
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%, -50%) rotate(-45deg);
  font-size: 140px; font-weight: 900; opacity: 0.15;
  pointer-events: none; z-index: 100;
  white-space: nowrap; letter-spacing: 8px;
}
.watermark-draft { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-45deg); font-size: 160px; font-weight: 900; color: #cc0000; opacity: 0.18; pointer-events: none; z-index: 100; letter-spacing: 12px; font-family: Arial, sans-serif; }
.watermark-final { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-45deg); font-size: 160px; font-weight: 900; color: #0066cc; opacity: 0.12; pointer-events: none; z-index: 100; letter-spacing: 12px; font-family: Arial, sans-serif; }
h1 { color: #0A0F1E; border-bottom: 2px solid #1a2a3f; padding-bottom: 8px; font-size: 20px; }
h2 { color: #1a2a3f; font-size: 14px; margin-top: 16px; }
.meta { color: #666; font-size: 11px; margin: 8px 0 16px; font-family: monospace; }
.kv { display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }
.kv div { padding: 8px 14px; background: #f8f9fa; border-radius: 4px; min-width: 120px; }
.kv strong { display: block; color: #666; font-size: 10px; text-transform: uppercase; margin-bottom: 4px; }
img { max-width: 100%; margin-top: 12px; }
</style></head><body>
${coverHtml}${tocHtml}${pageHtml}
<p style="color:#888;font-size:10px;padding:8px 24px">Generated by GravitationalWave Observability Dashboard (R6.47 multi-page). Mode: ${pdfMode}. For interactive version visit /admin/observability.</p>
</body></html>`

      const printWindow = window.open('', '_blank')
      if (!printWindow) throw new Error('Popup blocked')
      printWindow.document.write(printHtml)
      printWindow.document.close()
      printWindow.focus()
      setTimeout(() => {
        printWindow.print()
      }, 500)
    } catch (e) {
      console.warn('PDF export failed', e)
      alert(
        'PDF export failed: ' +
          (e as Error).message +
          '. Use browser File > Print > Save as PDF.',
      )
    } finally {
      setExporting(false)
    }
  }, [
    abDashboard,
    alerts,
    fontStats,
    pdfMode,
    abHistory,
    watermark,
    watermarkColor,
    watermarkCols,
    watermarkOpacity,
    watermarkRotation,
    watermarkRows,
    watermarkText,
  ])

  useEffect(() => {
    refresh()
  }, [refresh])

  const fontColumns = [
    {
      title: 'Font Family',
      dataIndex: 'family',
      key: 'family',
      render: (v: string) => <Tag color='blue'>{v}</Tag>,
    },
    {
      title: 'Weight',
      dataIndex: 'weight',
      key: 'weight',
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: 'Error Count',
      dataIndex: 'count',
      key: 'count',
      sorter: (a: FontErrorStat, b: FontErrorStat) => a.count - b.count,
      defaultSortOrder: 'descend' as const,
    },
    {
      title: 'Last Seen',
      dataIndex: 'last_seen',
      key: 'last_seen',
      render: (v: number) => formatTs(v),
    },
  ]

  const winnerDelta = abDashboard?.winner_delta_ms ?? 0

  return (
    <div className='p-6' style={{ background: '#0A0F1E', minHeight: '100vh' }}>
      <Spin spinning={loading}>
        <Space direction='vertical' size='large' className='w-full'>
          {/* Header */}
          <div className='flex items-center justify-between'>
            <div>
              <h1
                className='text-2xl font-bold text-white'
                style={{ fontFamily: 'monospace' }}
              >
                Observability Dashboard
              </h1>
              <p className='text-white/45 text-sm mt-1'>
                Font load errors + A/B test results from production traffic
              </p>
              <p className='text-white/30 text-xs mt-1'>
                Sentry:{' '}
                {sentryConfig.DSN_SET ? (
                  <Tag color='green'>enabled ({sentryConfig.ENV})</Tag>
                ) : (
                  <Tag color='default'>disabled (backend fallback)</Tag>
                )}{' '}
                · Last refresh: {lastRefresh ? formatTs(lastRefresh) : 'never'}
              </p>
            </div>
            <Button icon={<ReloadOutlined />} onClick={refresh}>
              Refresh
            </Button>
          </div>

          {/* A/B Test Winner Banner */}
          {abDashboard?.analysis_ready && abDashboard.winner && (
            <Card
              style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            >
              <Space size='middle'>
                <TrophyOutlined style={{ color: '#52c41a', fontSize: 32 }} />
                <div>
                  <h2 className='text-white text-lg font-bold m-0'>
                    A/B Test Winner: {abDashboard.winner.toUpperCase()}
                  </h2>
                  <p className='text-white/60 text-sm m-0'>
                    Median load time is{' '}
                    <strong style={{ color: '#52c41a' }}>
                      {formatMs(winnerDelta)}
                    </strong>{' '}
                    faster (n={abDashboard.groups.woff2?.count ?? 0} woff2 vs n=
                    {abDashboard.groups.system?.count ?? 0} system)
                  </p>
                </div>
              </Space>
            </Card>
          )}

          {abDashboard && !abDashboard.analysis_ready && (
            <Card
              style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            >
              <Space size='middle'>
                <AlertOutlined style={{ color: '#faad14', fontSize: 24 }} />
                <div>
                  <p className='text-white text-base m-0'>
                    A/B analysis not ready yet ({abDashboard.total_samples}/100
                    samples)
                  </p>
                  <p className='text-white/45 text-xs m-0'>
                    Backend auto-flips <code>analysis_ready</code> at 100+
                    samples.
                  </p>
                </div>
              </Space>
            </Card>
          )}

          {/* A/B Test Stats */}
          {abDashboard && (
            <Card
              title='A/B Test (woff2 vs system font)'
              style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
              headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
            >
              <Row gutter={16}>
                {(['woff2', 'system'] as const).map((g) => {
                  const summary = abDashboard.groups[g]
                  if (!summary) {
                    return (
                      <Col span={12} key={g}>
                        <Card
                          size='small'
                          style={{
                            background: '#0A0F1E',
                            border: '1px solid #1a2a3f',
                          }}
                        >
                          <h3 className='text-white font-bold m-0'>
                            {g.toUpperCase()}
                          </h3>
                          <p className='text-white/30 text-sm m-0'>
                            No samples yet
                          </p>
                        </Card>
                      </Col>
                    )
                  }
                  return (
                    <Col span={12} key={g}>
                      <Card
                        size='small'
                        style={{
                          background: '#0A0F1E',
                          border: '1px solid #1a2a3f',
                        }}
                      >
                        <h3 className='text-white font-bold m-0'>
                          {g.toUpperCase()}{' '}
                          {abDashboard.winner === g && (
                            <TrophyOutlined style={{ color: '#52c41a' }} />
                          )}
                        </h3>
                        <Row gutter={8} className='mt-3'>
                          <Col span={8}>
                            <Statistic
                              title={
                                <span className='text-white/45 text-xs'>
                                  Count
                                </span>
                              }
                              value={summary.count}
                              valueStyle={{ color: 'white', fontSize: 18 }}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title={
                                <span className='text-white/45 text-xs'>
                                  Load median
                                </span>
                              }
                              value={formatMs(summary.load_time_ms.median)}
                              valueStyle={{ color: 'white', fontSize: 18 }}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title={
                                <span className='text-white/45 text-xs'>
                                  Load p95
                                </span>
                              }
                              value={formatMs(summary.load_time_ms.p95)}
                              valueStyle={{ color: 'white', fontSize: 18 }}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title={
                                <span className='text-white/45 text-xs'>
                                  FCP avg
                                </span>
                              }
                              value={formatMs(summary.fcp_ms.avg)}
                              valueStyle={{ color: 'white', fontSize: 18 }}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title={
                                <span className='text-white/45 text-xs'>
                                  CLS p95
                                </span>
                              }
                              value={summary.cls.p95.toFixed(3)}
                              valueStyle={{ color: 'white', fontSize: 18 }}
                            />
                          </Col>
                        </Row>
                      </Card>
                    </Col>
                  )
                })}
              </Row>
            </Card>
          )}

          {messageContextHolder}
          {/* R6.46: Active Alerts section */}
          <Card
            title={`Active Alerts (${alerts.length})`}
            style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
          >
            {alerts.length > 0 ? (
              <Space direction='vertical' className='w-full'>
                {alerts.map((a) => (
                  <div
                    key={a.id}
                    className='flex items-center justify-between p-3 rounded'
                    style={{
                      background: '#0A0F1E',
                      border: '1px solid #1a2a3f',
                    }}
                  >
                    <div className='flex-1'>
                      <div className='flex items-center gap-2'>
                        <AlertOutlined style={{ color: '#ff4d4f' }} />
                        <span className='text-white font-mono text-sm font-bold'>
                          {a.alert_key}
                        </span>
                        <Tag
                          color={a.severity === 'warning' ? 'orange' : 'red'}
                        >
                          {a.severity}
                        </Tag>
                      </div>
                      <p className='text-white/70 text-xs m-0 mt-1'>
                        {a.message}
                      </p>
                      <p className='text-white/40 text-xs m-0 mt-1'>
                        Fired: {formatTs(a.fired_at)} · Occurrences:{' '}
                        {a.occurrences} · Last value: {a.last_value}
                      </p>
                    </div>
                    <Button
                      size='small'
                      icon={<CloseCircleOutlined />}
                      onClick={() => dismissAlert(a.id)}
                    >
                      Dismiss
                    </Button>
                  </div>
                ))}
              </Space>
            ) : (
              <Empty
                description={
                  <span className='text-white/45'>No active alerts</span>
                }
              />
            )}
          </Card>

          {/* R6.48: Alert Routing management panel */}
          <Card
            title={
              <span>
                <GlobalOutlined /> Alert Routing ({routing.length} routes)
              </span>
            }
            style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
            extra={
              <Button
                size='small'
                icon={<PlusOutlined />}
                onClick={openAddRoute}
              >
                Add Route
              </Button>
            }
          >
            {messageContextHolder}
            <Table
              dataSource={routing}
              rowKey='family'
              size='small'
              pagination={{ pageSize: 10 }}
              locale={{
                emptyText: (
                  <span className='text-white/45'>
                    No alert routes configured. Click "Add Route" to map a font
                    family to a PagerDuty routing key.
                  </span>
                ),
              }}
              columns={[
                {
                  title: 'Font Family',
                  dataIndex: 'family',
                  key: 'family',
                  render: (v: string) => (
                    <span className='text-white font-mono'>{v}</span>
                  ),
                },
                {
                  title: 'Routing Key',
                  dataIndex: 'pagerduty_routing_key',
                  key: 'pagerduty_routing_key',
                  render: (v: string) => (
                    <span className='text-white/70 font-mono text-xs'>
                      {'****' + v.slice(-8)}
                    </span>
                  ),
                },
                {
                  title: 'Team Email',
                  dataIndex: 'team_email',
                  key: 'team_email',
                  render: (v: string) => (
                    <span className='text-white/60 text-xs'>{v || '—'}</span>
                  ),
                },
                {
                  title: 'Updated',
                  dataIndex: 'updated_at',
                  key: 'updated_at',
                  render: (v: number) => (
                    <span className='text-white/45 text-xs'>{formatTs(v)}</span>
                  ),
                },
                {
                  title: 'Actions',
                  key: 'actions',
                  // R6.57: antd Table column render signature is (value, record, index);
                  //                  the value param is unused so we type it as `unknown`.
                  render: (_: unknown, r: AlertRoute) => (
                    <Space>
                      <Button
                        size='small'
                        icon={<EditOutlined />}
                        onClick={() => openEditRoute(r)}
                      >
                        Edit
                      </Button>
                      <Button
                        size='small'
                        icon={<DeleteOutlined />}
                        danger
                        onClick={() => deleteRouteRow(r.family)}
                      >
                        Delete
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>

          {/* R6.50: Audit Search & Retention */}
          <Card
            title={
              <span>
                <HistoryOutlined /> Audit Search & Retention
              </span>
            }
            size='small'
            style={{
              marginBottom: 16,
              background: '#0F1626',
              border: '1px solid #1a2a3f',
            }}
            headStyle={{ color: 'white' }}
          >
            <Space direction='vertical' style={{ width: '100%' }}>
              <Space wrap>
                <Input.Search
                  placeholder='Search audit log (actor, family, before/after JSON)'
                  value={auditSearch}
                  onChange={(e) => setAuditSearch(e.target.value)}
                  onSearch={(q) => fetchAuditSearch(q)}
                  style={{ width: 420 }}
                  allowClear
                />
                <Button
                  size='small'
                  onClick={() =>
                    handleSignPDF('demo-pdf-content-' + Date.now())
                  }
                  icon={<HistoryOutlined />}
                >
                  Sign Demo PDF
                </Button>
                <span style={{ color: '#aaa' }}>
                  Results filtered into Audit Log table below.
                </span>
              </Space>
              <Space wrap>
                <span style={{ color: 'white' }}>Retention (days):</span>
                <InputNumber
                  min={1}
                  max={3650}
                  value={retentionDays}
                  onChange={(v) => setRetentionDays(v || 90)}
                />
                <Button
                  danger
                  onClick={handlePurgeAudit}
                  icon={<DeleteOutlined />}
                >
                  Purge Old Audit Entries
                </Button>
                {purgeResult && (
                  <span style={{ color: '#aaa' }}>
                    Last purge: deleted {purgeResult.deleted_count}, kept{' '}
                    {purgeResult.kept_count}
                    {purgeResult.purged_by && ` by ${purgeResult.purged_by}`}
                  </span>
                )}
              </Space>
            </Space>
          </Card>

          {watermark === 'custom' && (
            <Card
              title='Custom Watermark Settings (R6.51 grid + rotation)'
              size='small'
              style={{
                marginBottom: 16,
                background: '#0F1626',
                border: '1px solid #1a2a3f',
              }}
              headStyle={{ color: 'white' }}
            >
              <Space direction='vertical' style={{ width: '100%' }}>
                <Space wrap>
                  <span style={{ color: 'white' }}>Text:</span>
                  <Input
                    value={watermarkText}
                    onChange={(e) => setWatermarkText(e.target.value)}
                    style={{ width: 200 }}
                    maxLength={30}
                  />
                  <span style={{ color: 'white' }}>Color:</span>
                  <Input
                    type='color'
                    value={watermarkColor}
                    onChange={(e) => setWatermarkColor(e.target.value)}
                    style={{ width: 60 }}
                  />
                  <span style={{ color: 'white' }}>Opacity:</span>
                  <Slider
                    min={0.05}
                    max={0.4}
                    step={0.05}
                    value={watermarkOpacity}
                    onChange={setWatermarkOpacity}
                    style={{ width: 100 }}
                  />
                  <span style={{ color: 'white' }}>
                    {watermarkOpacity.toFixed(2)}
                  </span>
                </Space>
                <Space wrap>
                  <span style={{ color: 'white' }}>Rows × Cols:</span>
                  <InputNumber
                    min={1}
                    max={8}
                    value={watermarkRows}
                    onChange={(v) => setWatermarkRows(v || 1)}
                  />
                  <span style={{ color: '#aaa' }}>×</span>
                  <InputNumber
                    min={1}
                    max={8}
                    value={watermarkCols}
                    onChange={(v) => setWatermarkCols(v || 1)}
                  />
                  <span style={{ color: 'white' }}>Rotation (deg):</span>
                  <Slider
                    min={-90}
                    max={90}
                    step={5}
                    value={watermarkRotation}
                    onChange={setWatermarkRotation}
                    style={{ width: 120 }}
                  />
                  <span style={{ color: 'white' }}>{watermarkRotation}°</span>
                </Space>
              </Space>
            </Card>
          )}

          {/* R6.49: Audit History Card */}
          <Card
            title={
              <span>
                <HistoryOutlined /> Routing Audit Log ({audit.length} entries)
              </span>
            }
            style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
            extra={
              <Space>
                <Input
                  size='small'
                  placeholder='Filter family'
                  value={auditFamilyFilter}
                  onChange={(e) => setAuditFamilyFilter(e.target.value)}
                  onPressEnter={() =>
                    fetchAudit(auditFamilyFilter || undefined)
                  }
                  style={{ width: 140 }}
                  allowClear
                />
                <Button
                  size='small'
                  onClick={() => fetchAudit(auditFamilyFilter || undefined)}
                >
                  Refresh
                </Button>
              </Space>
            }
          >
            <Table
              dataSource={audit}
              rowKey='id'
              size='small'
              pagination={{ pageSize: 10 }}
              locale={{
                emptyText: (
                  <span className='text-white/45'>
                    No audit entries yet. Changes to alert routing will be
                    recorded here.
                  </span>
                ),
              }}
              columns={[
                {
                  title: 'Time',
                  dataIndex: 'ts',
                  key: 'ts',
                  render: (v: number) => (
                    <span className='text-white/60 text-xs'>{formatTs(v)}</span>
                  ),
                },
                {
                  title: 'Family',
                  dataIndex: 'family',
                  key: 'family',
                  render: (v: string, r: AuditEntry) => (
                    <span className='text-white font-mono'>
                      {r.match_field === 'family'
                        ? highlightMatch(v, r.match_offset, auditSearch)
                        : v}
                    </span>
                  ),
                },
                {
                  title: 'Action',
                  dataIndex: 'action',
                  key: 'action',
                  render: (v: string, r: AuditEntry) => (
                    <Tag color={v === 'upsert' ? 'cyan' : 'red'}>
                      {r.match_field === 'action'
                        ? highlightMatch(
                            v.toUpperCase(),
                            r.match_offset,
                            auditSearch.toUpperCase(),
                          )
                        : v.toUpperCase()}
                    </Tag>
                  ),
                },
                {
                  title: 'Actor',
                  dataIndex: 'actor',
                  key: 'actor',
                  render: (v: string, r: AuditEntry) => (
                    <span className='text-white/60 text-xs'>
                      {r.match_field === 'actor'
                        ? highlightMatch(v, r.match_offset, auditSearch)
                        : v}
                    </span>
                  ),
                },
                {
                  title: 'Diff',
                  key: 'diff',
                  // R6.57: antd Table column render (value, record, index); value unused.
                  render: (_: unknown, r: AuditEntry) => (
                    <span className='text-white/50 text-xs font-mono'>
                      {r.action === 'upsert' && r.before_json ? (
                        <>
                          {'rkey: '}
                          <span className='text-red-300'>
                            {'****' +
                              (
                                (r.before_json
                                  .pagerduty_routing_key as string) || ''
                              ).slice(-8)}
                          </span>
                          {' -> '}
                          <span className='text-green-300'>
                            {'****' +
                              (
                                (r.after_json
                                  ?.pagerduty_routing_key as string) || ''
                              ).slice(-8)}
                          </span>
                        </>
                      ) : r.action === 'delete' ? (
                        <span className='text-red-300'>removed</span>
                      ) : (
                        <span className='text-green-300'>created</span>
                      )}
                    </span>
                  ),
                },
              ]}
            />
            {auditHasMore && (
              <div style={{ textAlign: 'center', marginTop: 16 }}>
                <Button
                  onClick={() =>
                    fetchAuditSearch(auditSearch, true, auditNextCursor)
                  }
                  loading={auditLoading}
                >
                  Load More (cursor-based pagination)
                </Button>
              </div>
            )}
          </Card>

          {/* R6.51: Batch verify modal */}
          <Modal
            title='Verify Multiple PDF Signatures'
            open={batchVerifyOpen}
            onCancel={() => setBatchVerifyOpen(false)}
            onOk={async () => {
              const hashes = batchVerifyInput
                .split(/[\s,]+/)
                .map((s: string) => s.trim())
                .filter(Boolean)
              if (hashes.length === 0) {
                messageApi.warning('No hashes provided')
                return
              }
              try {
                const res = await fetch('/pipeline/pdf/verify-multiple', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'X-Actor': actor,
                  },
                  body: JSON.stringify({ hashes }),
                })
                if (res.ok) {
                  const data = await res.json()
                  setBatchVerifyResult(data)
                  messageApi.success(
                    `${data.verified_count}/${data.total} verified`,
                  )
                } else {
                  messageApi.error('Batch verify failed')
                }
              } catch (e) {
                messageApi.error(`Error: ${e}`)
              }
            }}
            width={700}
          >
            <Input.TextArea
              rows={6}
              placeholder='Paste SHA256 hashes (one per line, or comma/space separated)'
              value={batchVerifyInput}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                setBatchVerifyInput(e.target.value)
              }
            />
            {batchVerifyResult !== null && (
              <pre
                style={{
                  marginTop: 12,
                  background: '#0a0e1a',
                  color: '#ddd',
                  padding: 12,
                  borderRadius: 4,
                  maxHeight: 300,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(batchVerifyResult, null, 2)}
              </pre>
            )}
          </Modal>

          <Modal
            title={editingRoute ? 'Edit Alert Route' : 'Add Alert Route'}
            open={routeModalOpen}
            onCancel={() => setRouteModalOpen(false)}
            onOk={submitRoute}
            okText='Save'
            destroyOnClose
          >
            <Form form={routeForm} layout='vertical'>
              <Form.Item
                label='Font Family'
                name='family'
                rules={[{ required: true, message: 'Family is required' }]}
              >
                <Input placeholder='e.g. Inter' disabled={!!editingRoute} />
              </Form.Item>
              <Form.Item
                label='PagerDuty Routing Key'
                name='pagerduty_routing_key'
                rules={[{ required: true, message: 'Routing key is required' }]}
              >
                <Input.Password placeholder='rkey_xxx' autoComplete='off' />
              </Form.Item>
              <Form.Item label='Team Email (optional)' name='team_email'>
                <Input placeholder='team@lab.test' />
              </Form.Item>
            </Form>
          </Modal>

          {/* R6.46: Time-series chart for AB winner drift */}
          <Card
            title='A/B Load Time Trend (last 7 days, 1h buckets)'
            style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
            extra={
              <Space>
                <Button
                  size='small'
                  icon={<FileImageOutlined />}
                  onClick={exportPNG}
                  loading={exporting}
                  disabled={!abHistory || abHistory.buckets.length === 0}
                >
                  Export PNG
                </Button>
                <Select
                  size='small'
                  value={pdfMode}
                  onChange={(v) => setPdfMode(v)}
                  style={{ width: 110 }}
                  options={[
                    { value: 'single', label: 'Single page' },
                    { value: 'per-day', label: 'Per day' },
                    { value: 'per-week', label: 'Per week' },
                  ]}
                />
                {/* R6.49: Watermark mode (DRAFT vs FINAL) */}
                <Select
                  size='small'
                  value={watermark}
                  onChange={(v) => setWatermark(v)}
                  style={{ width: 90 }}
                  options={[
                    { value: 'none', label: 'No watermark' },
                    { value: 'draft', label: 'DRAFT' },
                    { value: 'final', label: 'FINAL' },
                  ]}
                />
                <Button
                  size='small'
                  icon={<FilePdfOutlined />}
                  onClick={exportPDF}
                  loading={exporting}
                  disabled={!abHistory || abHistory.buckets.length === 0}
                >
                  Export PDF
                </Button>
              </Space>
            }
          >
            <ABHistoryChart ref={chartRef} history={abHistory} />
          </Card>

          {/* Font Error Stats */}
          <Card
            title={`Font Load Errors (${fontStats?.total ?? 0} total)`}
            style={{ background: '#0F1626', border: '1px solid #1a2a3f' }}
            headStyle={{ color: 'white', borderBottom: '1px solid #1a2a3f' }}
          >
            {fontStats && fontStats.total > 0 ? (
              <Table
                dataSource={fontStats.by_family_weight}
                columns={fontColumns}
                rowKey={(r) => `${r.family}-${r.weight}`}
                pagination={false}
                size='small'
                style={{ background: '#0A0F1E' }}
              />
            ) : (
              <Empty
                description={
                  <span className='text-white/45'>No font errors reported</span>
                }
              />
            )}
          </Card>
        </Space>
      </Spin>
    </div>
  )
}
