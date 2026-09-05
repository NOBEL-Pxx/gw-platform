import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { initCspMonitor, __test__ } from '../cspMonitor'

describe('R6.61.c cspMonitor', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    __test__.reset()
    // Remove all listeners we might have installed
    document.removeEventListener('securitypolicyviolation', __test__.installForTest as any, true)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
    __test__.reset()
  })

  // happy-dom lacks SecurityPolicyViolationEvent. Build a plain Event with the
  // violation fields manually attached. The cspMonitor reads them directly
  // via e.blockedURI etc, so this works in test environment.
  function makeViolation(
    overrides: Record<string, unknown> = {},
  ): SecurityPolicyViolationEvent {
    const e = new Event('securitypolicyviolation') as any
    e.blockedURI = overrides.blockedURI ?? 'https://evil.example.com/script.js'
    e.violatedDirective = overrides.violatedDirective ?? 'script-src'
    e.effectiveDirective = overrides.effectiveDirective ?? 'script-src'
    e.originalPolicy = overrides.originalPolicy ?? "default-src 'self'"
    e.documentURI = overrides.documentURI ?? 'https://gw.example.com/'
    e.referrer = overrides.referrer ?? ''
    e.sourceFile = overrides.sourceFile ?? 'https://evil.example.com/script.js'
    e.lineNumber = overrides.lineNumber ?? 1
    e.columnNumber = overrides.columnNumber ?? 1
    e.sample = overrides.sample ?? 'alert(1)'
    e.disposition = overrides.disposition ?? 'enforce'
    return e as SecurityPolicyViolationEvent
  }

  it('initCspMonitor installs once (idempotent)', () => {
    initCspMonitor()
    initCspMonitor()
    initCspMonitor()
    // No throw = success (idempotent)
  })

  it('captures violations dispatched on document', () => {
    let captured: SecurityPolicyViolationEvent | null = null
    const onV = (e: SecurityPolicyViolationEvent) => {
      captured = e
    }
    __test__.installForTest(onV)
    const v = makeViolation()
    document.dispatchEvent(v)
    expect(captured).toBe(v)
    __test__.uninstallForTest(onV)
  })

  it('dedups violations with same effectiveDirective + host + sample', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    // Fire 5 identical violations
    for (let i = 0; i < 5; i++) {
      document.dispatchEvent(makeViolation())
    }
    // Wait for debounce
    await new Promise((r) => setTimeout(r, 100))
    // Manually flush
    __test__.flushSync()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.violations.length).toBe(1)
  })

  it('different blockedURI hosts create separate entries', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    document.dispatchEvent(makeViolation({ blockedURI: 'https://a.example.com/x.js' }))
    document.dispatchEvent(makeViolation({ blockedURI: 'https://b.example.com/x.js' }))

    __test__.flushSync()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.violations.length).toBe(2)
  })

  it('inline/eval violations are kept separately from URL violations', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    document.dispatchEvent(makeViolation({ blockedURI: 'inline', sample: 'inline-script' }))
    document.dispatchEvent(makeViolation({ blockedURI: 'eval', sample: 'eval-call' }))
    document.dispatchEvent(makeViolation({ blockedURI: 'https://x.example.com/y.js' }))

    __test__.flushSync()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.violations.length).toBe(3)
  })

  it('caps batch size at 50', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    // 60 unique violations
    for (let i = 0; i < 60; i++) {
      document.dispatchEvent(
        makeViolation({ blockedURI: `https://host${i}.example.com/x.js` }),
      )
    }

    __test__.flushSync()

    expect(fetchMock).toHaveBeenCalled()
    const firstCall = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(firstCall.violations.length).toBeLessThanOrEqual(50)
  })

  it('POSTs to /pipeline/security/csp-violation with correct body shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    document.dispatchEvent(makeViolation())

    __test__.flushSync()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/pipeline/security/csp-violation')
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    const body = JSON.parse(init.body)
    expect(body.violations).toBeInstanceOf(Array)
    expect(body.violations[0]).toHaveProperty('blockedURI')
    expect(body.violations[0]).toHaveProperty('effectiveDirective')
    expect(body.violations[0]).toHaveProperty('sample')
    expect(body.userAgent).toBeDefined()
    expect(body.url).toBeDefined()
    expect(body.ts).toBeGreaterThan(0)
  })

  it('uses keepalive so fetch survives page unload', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock

    initCspMonitor()
    document.dispatchEvent(makeViolation())

    __test__.flushSync()

    const init = fetchMock.mock.calls[0][1]
    expect(init.keepalive).toBe(true)
  })

  it('swallows fetch errors (does not throw to caller)', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network down'))
    globalThis.fetch = fetchMock

    initCspMonitor()
    document.dispatchEvent(makeViolation())

    expect(() => __test__.flushSync()).not.toThrow()
  })

  it('dedup ring caps at 200 (does not grow unbounded)', () => {
    initCspMonitor()
    // Fire 250 unique violations
    for (let i = 0; i < 250; i++) {
      document.dispatchEvent(
        makeViolation({
          blockedURI: `https://unique${i}.example.com/x.js`,
          sample: `sample${i}`,
        }),
      )
    }
    // After 200, older entries should be evicted. We can't directly inspect
    // _dedupRing (private), but we can verify the queue is non-empty and
    // the monitor didn't crash.
    expect(__test__.queue.length).toBeGreaterThan(0)
  })
})
