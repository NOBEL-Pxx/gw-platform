// R6.41: A/B test for woff2 vs system font.
// Randomly assigns user to group A (woff2) or B (system font).
// Tracks font load time + CLS to compare perceptual quality.
//
// R6.44: POSTs samples to backend /pipeline/observability/ab-metrics
// R6.45: Pre-fetches /ab-dashboard and auto-assigns NEW users to the
//        winning group (existing users keep their stable assignment).

import { useEffect, useState } from 'react'

const AB_KEY = 'gw-font-ab-group'
const AB_METRICS_KEY = 'gw-font-ab-metrics'
const AB_REPORT_URL = '/pipeline/observability/ab-metrics'
const AB_DASHBOARD_URL = '/pipeline/observability/ab-dashboard'

export type FontGroup = 'woff2' | 'system'

interface FontMetrics {
  group: FontGroup
  loadTimeMs: number | null
  cls: number | null
  fcp: number | null
  page?: string
  userId?: string
}

// R6.57: Stored shape in localStorage (subset of FontMetrics with `t` ts).
interface FontMetricsEntry {
  group: string
  loadTimeMs?: number
  fcp?: number
  cls?: number
  page?: string
  userId?: string
  t?: number
}

function _getUserId(): string {
  if (typeof window === 'undefined') return 'ssr'
  let uid = localStorage.getItem('gw-user-id')
  if (!uid) {
    uid = `u_${Math.random().toString(36).slice(2, 10)}_${Date.now().toString(36)}`
    localStorage.setItem('gw-user-id', uid)
  }
  return uid
}

function _getPage(): string {
  if (typeof window === 'undefined') return 'unknown'
  return window.location.pathname.split('/').filter(Boolean)[0] || 'home'
}

function _reportMetric(m: FontMetrics): void {
  if (typeof window === 'undefined') return
  const payload = JSON.stringify({
    group: m.group,
    loadTimeMs: m.loadTimeMs,
    fcp: m.fcp,
    cls: m.cls,
    page: m.page,
    userId: m.userId,
    timestamp: Date.now(),
  })
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: 'application/json' })
      navigator.sendBeacon(AB_REPORT_URL, blob)
    } else {
      fetch(AB_REPORT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(() => {})
    }
  } catch {
    /* best effort */
  }
}

// R6.45: pre-fetch winner from dashboard. Falls back to null if dashboard unavailable
// or no winner determined yet (n<30 or no statistically significant delta).
async function _fetchWinner(): Promise<FontGroup | null> {
  try {
    const res = await fetch(AB_DASHBOARD_URL, { cache: 'no-store' })
    if (!res.ok) return null
    const data = await res.json()
    if (
      data?.analysis_ready &&
      (data.winner === 'woff2' || data.winner === 'system')
    ) {
      return data.winner
    }
  } catch {
    /* best effort */
  }
  return null
}

export function useFontABTest(): { group: FontGroup; metrics: FontMetrics } {
  const [group, setGroup] = useState<FontGroup>(() => {
    if (typeof window === 'undefined') return 'woff2'
    const existing = localStorage.getItem(AB_KEY)
    if (existing === 'woff2' || existing === 'system') return existing
    // No prior assignment: assign randomly for now; winner auto-switch
    // will overwrite this in the effect below if dashboard is reachable.
    const assigned: FontGroup = Math.random() < 0.5 ? 'woff2' : 'system'
    localStorage.setItem(AB_KEY, assigned)
    return assigned
  })

  const [metrics, setMetrics] = useState<FontMetrics>({
    group,
    loadTimeMs: null,
    cls: null,
    fcp: null,
    page: _getPage(),
    userId: _getUserId(),
  })

  useEffect(() => {
    if (typeof window === 'undefined') return

    // R6.45: auto-switch to winner (new users only)
    const existing = localStorage.getItem(AB_KEY)
    if (existing !== 'woff2' && existing !== 'system') {
      // No prior assignment — try dashboard winner
      _fetchWinner().then((winner) => {
        if (winner) {
          localStorage.setItem(AB_KEY, winner)
          setGroup(winner)

          console.info('[ABTest] Auto-assigned to winner group:', winner)
        }
      })
    }

    const start = performance.now()
    let clsValue: number | null = null
    let fcpValue: number | null = null

    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === 'first-contentful-paint') {
          fcpValue = entry.startTime
        }
      }
    }).observe({ type: 'paint', buffered: true })

    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // R6.57: PerformanceLayoutShift is the proper type for layout-shift
        // entries (has both 'value' and 'hadRecentInput'). Avoid `any`.
        const ls = entry as PerformanceEntry & {
          hadRecentInput?: boolean
          value?: number
        }
        if (!ls.hadRecentInput) {
          clsValue = (clsValue || 0) + (ls.value ?? 0)
        }
      }
    }).observe({ type: 'layout-shift', buffered: true })

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        const elapsed = performance.now() - start
        const currentGroup =
          (localStorage.getItem(AB_KEY) as FontGroup) || 'woff2'
        const m: FontMetrics = {
          group: currentGroup,
          loadTimeMs: elapsed,
          fcp: fcpValue,
          cls: clsValue,
          page: _getPage(),
          userId: _getUserId(),
        }
        setMetrics(m)
        const stored = JSON.parse(localStorage.getItem(AB_METRICS_KEY) || '[]')
        stored.push({ ...m, t: Date.now() })
        localStorage.setItem(AB_METRICS_KEY, JSON.stringify(stored.slice(-50)))
        _reportMetric(m)
      })
    }
  }, [])

  return { group, metrics }
}

// R6.42: Export A/B test metrics as JSON file
export function exportFontABMetrics(): void {
  if (typeof window === 'undefined') return
  const metrics = JSON.parse(localStorage.getItem('gw-font-ab-metrics') || '[]')
  if (metrics.length === 0) {
    alert('No A/B test data yet. Browse the app to collect metrics.')
    return
  }
  // R6.57: FontMetricsEntry is the runtime shape stored in localStorage
  // (subset of FontMetrics with extra `t` timestamp added at storage time).
  interface FontMetricsEntry {
    group: string
    loadTimeMs?: number
    fcp?: number
    cls?: number
    page?: string
    userId?: string
    t?: number
  }
  const groupA = metrics.filter((m: FontMetricsEntry) => m.group === 'woff2')
  const groupB = metrics.filter((m: FontMetricsEntry) => m.group === 'system')
  const avg = (arr: FontMetricsEntry[], k: keyof FontMetricsEntry) => {
    const vals = arr
      .map((m) => m[k])
      .filter((v): v is number => typeof v === 'number' && v !== null)
    return vals.length === 0
      ? null
      : vals.reduce((a, b) => a + b, 0) / vals.length
  }
  const summary = {
    generatedAt: new Date().toISOString(),
    totalSamples: metrics.length,
    groupA_woff2: {
      count: groupA.length,
      avgLoadTimeMs: avg(groupA, 'loadTimeMs'),
      avgFcp: avg(groupA, 'fcp'),
      avgCls: avg(groupA, 'cls'),
    },
    groupB_system: {
      count: groupB.length,
      avgLoadTimeMs: avg(groupB, 'loadTimeMs'),
      avgFcp: avg(groupB, 'fcp'),
      avgCls: avg(groupB, 'cls'),
    },
    rawData: metrics,
  }
  const blob = new Blob([JSON.stringify(summary, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `font-ab-metrics-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// R6.43: local-only statistical comparison
export interface FontABResult {
  groupA: {
    count: number
    avgLoadTimeMs: number
    avgFcp: number
    avgCls: number
    p95: number
  }
  groupB: {
    count: number
    avgLoadTimeMs: number
    avgFcp: number
    avgCls: number
    p95: number
  }
  conclusion: string
}
export function analyzeFontAB(): FontABResult | null {
  if (typeof window === 'undefined') return null
  const metrics: FontMetricsEntry[] = JSON.parse(
    localStorage.getItem('gw-font-ab-metrics') || '[]',
  )
  if (metrics.length < 100) return null
  const stats = (
    arr: FontMetricsEntry[],
    key: 'loadTimeMs' | 'fcp' | 'cls',
  ) => {
    const vals = arr
      .map((m) => m[key])
      .filter((v): v is number => v !== null && v !== undefined)
      .sort((a, b) => a - b)
    if (vals.length === 0) return { count: 0, avg: 0, p95: 0 }
    const sum = vals.reduce((a: number, b: number) => a + b, 0)
    return {
      count: vals.length,
      avg: sum / vals.length,
      p95: vals[Math.floor(vals.length * 0.95)],
    }
  }
  const groupA = metrics.filter((m: FontMetricsEntry) => m.group === 'woff2')
  const groupB = metrics.filter((m: FontMetricsEntry) => m.group === 'system')
  const sA = stats(groupA, 'loadTimeMs')
  const sB = stats(groupB, 'loadTimeMs')
  const fcpA = stats(groupA, 'fcp')
  const fcpB = stats(groupB, 'fcp')
  const avgA: number = sA.avg ?? 0
  const avgB: number = sB.avg ?? 0
  const winner: 'woff2' | 'system' = avgA < avgB ? 'woff2' : 'system'
  return {
    groupA: {
      count: sA.count,
      avgLoadTimeMs: avgA,
      avgFcp: fcpA.avg ?? 0,
      avgCls: stats(groupA, 'cls').avg ?? 0,
      p95: sA.p95 ?? 0,
    },
    groupB: {
      count: sB.count,
      avgLoadTimeMs: avgB,
      avgFcp: fcpB.avg ?? 0,
      avgCls: stats(groupB, 'cls').avg ?? 0,
      p95: sB.p95 ?? 0,
    },
    conclusion:
      winner === 'woff2'
        ? `woff2 group is ${(avgB - avgA).toFixed(0)}ms faster (n=${sA.count} vs ${sB.count})`
        : `system font is ${(avgA - avgB).toFixed(0)}ms faster (n=${sB.count} vs ${sA.count})`,
  }
}

// R6.44: fetch backend dashboard summary
export async function fetchABDashboard(): Promise<{
  total_samples: number
  analysis_ready: boolean
  // R6.57: groups is { groupName -> { sample stats } }. Backend returns
  // numbers + a count. Keep loose typing since the dashboard renders dynamically.
  groups: Record<string, Record<string, number>>
  winner: string | null
  winner_delta_ms: number
  queried_at: number
} | null> {
  if (typeof window === 'undefined') return null
  try {
    const res = await fetch(AB_DASHBOARD_URL)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}
