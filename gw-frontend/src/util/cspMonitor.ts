// R6.61.c: CSP violation monitor.
//
// Listens for `securitypolicyviolation` events on document. Browsers fire
// this whenever a Content-Security-Policy directive blocks a resource
// (script-src, img-src, connect-src, etc). We batch violations locally and
// POST them to /pipeline/security/csp-violation for backend logging.
//
// Why monitor CSP:
//   - 'wasm-unsafe-eval' is allowed in CSP for Aladin Lite WASM modules.
//     If we ever strip it, Aladin dies silently in production — monitoring
//     surfaces the breakage immediately.
//   - Defense-in-depth: detect XSS / supply-chain attempts that violate CSP.
//
// Rate limiting:
//   - Debounce 5s between sends (collapses bursts during initial page load).
//   - Max 50 violations per send (single bad script can fire thousands).
//   - Dedup by (directive + blockedURI + sample) — only first occurrence sent.
//
// Backend endpoint (R6.61.c):
//   POST /pipeline/security/csp-violation
//   Body: { violations: [...], userAgent, url, ts }

export interface CspViolation {
  // SecurityPolicyViolationEvent fields (per CSP Level 3 spec).
  blockedURI: string
  violatedDirective: string
  effectiveDirective: string
  originalPolicy: string
  documentURI: string
  referrer: string
  sourceFile: string
  lineNumber: number
  columnNumber: number
  sample: string
  disposition: string // 'enforce' | 'report'
}

interface CspReportBody {
  violations: CspViolation[]
  userAgent: string
  url: string
  ts: number
}

const DEBOUNCE_MS = 5000
const MAX_BATCH = 50
const DEDUP_LIMIT = 200 // ring-buffer size (avoid unbounded growth)

let _queue: CspViolation[] = []
let _dedupRing: string[] = []
let _timer: ReturnType<typeof setTimeout> | null = null
let _installed = false

function dedupKey(v: CspViolation): string {
  // (effectiveDirective + blockedURI host + sample[:40]) — same violation
  // collapses to one entry. blockedURI may be a URL or 'inline' / 'eval'.
  const host = (() => {
    try {
      return v.blockedURI === 'inline' || v.blockedURI === 'eval'
        ? v.blockedURI
        : new URL(v.blockedURI).host
    } catch {
      return v.blockedURI
    }
  })()
  return `${v.effectiveDirective}|${host}|${v.sample.slice(0, 40)}`
}

function rememberSeen(key: string): boolean {
  if (_dedupRing.includes(key)) return false
  _dedupRing.push(key)
  if (_dedupRing.length > DEDUP_LIMIT) _dedupRing.shift()
  return true
}

function flush(): void {
  if (_queue.length === 0) return
  const batch = _queue.slice(0, MAX_BATCH)
  _queue = _queue.slice(MAX_BATCH)
  const body: CspReportBody = {
    violations: batch,
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown',
    url: typeof location !== 'undefined' ? location.href : 'unknown',
    ts: Date.now(),
  }
  // Best-effort: fetch with keepalive so the request survives page unload.
  try {
    fetch('/pipeline/security/csp-violation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {
      // swallow — endpoint may be down, we don't want to spam the console.
      // Re-queue for next attempt? For simplicity, drop.
    })
  } catch {
    // ignore
  }
  // If more queued, schedule another flush
  if (_queue.length > 0) {
    _timer = setTimeout(flush, DEBOUNCE_MS)
  } else {
    _timer = null
  }
}

function onViolation(e: SecurityPolicyViolationEvent): void {
  const v: CspViolation = {
    blockedURI: e.blockedURI,
    violatedDirective: e.violatedDirective,
    effectiveDirective: e.effectiveDirective,
    originalPolicy: e.originalPolicy,
    documentURI: e.documentURI,
    referrer: e.referrer,
    sourceFile: e.sourceFile,
    lineNumber: e.lineNumber,
    columnNumber: e.columnNumber,
    sample: e.sample,
    disposition: e.disposition,
  }
  const key = dedupKey(v)
  if (!rememberSeen(key)) return
  _queue.push(v)
  if (_timer === null) {
    _timer = setTimeout(flush, DEBOUNCE_MS)
  }
}

export function initCspMonitor(): void {
  if (_installed) return
  if (typeof document === 'undefined') return
  // Use capture phase to catch violations before any in-page handler.
  document.addEventListener('securitypolicyviolation', onViolation, { capture: true })
  _installed = true
  // Also flush before unload (debounce might not have fired yet).
  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => {
      if (_queue.length > 0) flush()
    })
  }
}

// Test-only helpers (not exported in production index)
export const __test__ = {
  get queue() {
    return _queue
  },
  reset(): void {
    _queue = []
    _dedupRing = []
    if (_timer !== null) {
      clearTimeout(_timer)
      _timer = null
    }
  },
  installForTest(onV: (e: SecurityPolicyViolationEvent) => void): void {
    if (typeof document === 'undefined') return
    document.addEventListener('securitypolicyviolation', onV, { capture: true })
  },
  uninstallForTest(onV: (e: SecurityPolicyViolationEvent) => void): void {
    if (typeof document === 'undefined') return
    document.removeEventListener('securitypolicyviolation', onV, { capture: true } as any)
  },
  flushSync(): void {
    flush()
  },
}
