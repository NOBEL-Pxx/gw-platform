// R6.45: Real backend font-load monitoring + optional Sentry capture.
// Replaces R6.43's localStorage-only fallback with persistent backend storage
// at /api/observability/font-errors (SQLite + JSONL on the backend side).
// When Sentry SDK is initialized (VITE_SENTRY_DSN set), also calls
// Sentry.captureMessage() for centralized alerting.

import { useEffect } from 'react'
import { captureFontError, initSentry } from '../sentry'

const ERROR_KEY = 'gw-font-errors' // last 50 (R6.43 backward compat)
const REPORT_URL = '/pipeline/observability/font-errors'
const APP_VERSION = 'v4.62+R6.45'
interface WindowWithEnv extends Window {
  GW_APP_ENV?: string
}
const APP_ENV =
  (typeof window !== 'undefined' && (window as WindowWithEnv).GW_APP_ENV) ||
  'production'
interface FontError {
  family: string
  weight: string
  src: string
  timestamp: number
  url: string
  userAgent: string
  version?: string
  env?: string
}

interface DedupKey {
  family: string
  weight: string
  src: string
}
const _seenRecently = new Map<string, number>()
const DEDUP_TTL_MS = 60_000

function _dedupKey(e: DedupKey): string {
  return `${e.family}|${e.weight}|${e.src}`
}

function _shouldReport(e: DedupKey): boolean {
  const k = _dedupKey(e)
  const now = Date.now()
  const last = _seenRecently.get(k) || 0
  if (now - last < DEDUP_TTL_MS) return false
  _seenRecently.set(k, now)
  if (_seenRecently.size > 200) {
    const cutoff = now - DEDUP_TTL_MS
    for (const [k2, t] of _seenRecently) {
      if (t < cutoff) _seenRecently.delete(k2)
    }
  }
  return true
}

export function useFontMonitor(): void {
  useEffect(() => {
    if (typeof window === 'undefined') return
    // R6.45: try Sentry init (no-op if VITE_SENTRY_DSN unset)
    initSentry()

    const collectError = (family: string, weight: string, src: string) => {
      if (!_shouldReport({ family, weight, src })) return

      const error: FontError = {
        family,
        weight,
        src,
        timestamp: Date.now(),
        url: window.location.href,
        userAgent: navigator.userAgent,
        version: APP_VERSION,
        env: APP_ENV,
      }
      // Local fallback (R6.43 backward compat)
      const errors = JSON.parse(localStorage.getItem(ERROR_KEY) || '[]')
      errors.push(error)
      localStorage.setItem(ERROR_KEY, JSON.stringify(errors.slice(-50)))

      // R6.44: persistent backend storage (SQLite + JSONL on server)
      try {
        const payload = JSON.stringify(error)
        if (navigator.sendBeacon) {
          const blob = new Blob([payload], { type: 'application/json' })
          navigator.sendBeacon(REPORT_URL, blob)
        } else {
          fetch(REPORT_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload,
            keepalive: true,
          }).catch(() => {
            /* best effort */
          })
        }
      } catch {
        // best-effort, never block UI
      }
      // R6.45: Sentry capture (no-op if not initialized)
      captureFontError(family, weight, src)

      console.warn('[FontMonitor] Failed to load:', family, weight, src)
    }

    const probeInterval = setInterval(() => {
      if (document.fonts && document.fonts.status === 'loaded') {
        const probes: Array<[string, string]> = [
          ['Inter', '400'],
          ['Inter', '700'],
          ['JetBrains Mono', '400'],
        ]
        for (const [family, weight] of probes) {
          if (!document.fonts.check(`${weight} 16px "${family}"`)) {
            collectError(family, weight, 'check-failed')
          }
        }
        clearInterval(probeInterval)
      }
    }, 500)

    const handleError = (e: Event) => {
      const target = e.target as
        (CSSStyleSheet & { familyName?: string; src?: string }) | null
      if (target?.familyName) {
        collectError(
          target.familyName,
          'unknown',
          target.src || 'css-font-error',
        )
      }
    }
    window.addEventListener(
      'CSSFontFaceLoadError',
      handleError as EventListener,
    )
    return () => {
      clearInterval(probeInterval)
      window.removeEventListener(
        'CSSFontFaceLoadError',
        handleError as EventListener,
      )
    }
  }, [])
}

export function exportFontErrors(): FontError[] {
  if (typeof window === 'undefined') return []
  return JSON.parse(localStorage.getItem(ERROR_KEY) || '[]')
}
