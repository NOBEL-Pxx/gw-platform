import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { buildHipsUrl, clearHipsCache, fetchHipsTile } from '../hips'
// preconnectHipsEndpoints is imported dynamically in R6.61.a preconnect tests
// (vi.resetModules + await import) to avoid module-level _preconnectFired pollution.

describe('hips utility', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    clearHipsCache()
    // R6.61.a: clear localStorage between tests (cross-tab cache)
    try {
      const keys: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('gw-hips-v1:')) keys.push(k)
      }
      keys.forEach((k) => localStorage.removeItem(k))
    } catch { /* ignore */ }
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  describe('buildHipsUrl', () => {
    it('returns alasky fallback when fetch fails', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('network down'))
      const url = await buildHipsUrl('DSS2Merged', 'Norder3/Dir0/index.png')
      expect(url).toMatch(
        /^https:\/\/alasky\.cds\.unistra\.fr\/DSS2Merged\/Norder3\/Dir0\/index\.png$/,
      )
    })

    it('returns backend-resolved endpoint + fullPath when fetch ok with endpoint', async () => {
      // Endpoint is a base URL (no surveyPath). Backend returns whichever
      // CDN was reachable (alasky / aladin / esac). fullPath = surveyPath + tilePath.
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr',
          ok: true,
        }),
      })
      const url = await buildHipsUrl('DSS2Merged', '/Norder3/Dir0/index.png')
      expect(url).toBe(
        'https://aladin.u-strasbg.fr/DSS2Merged/Norder3/Dir0/index.png',
      )
    })

    it('strips trailing slash from endpoint', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr/',
          ok: true,
        }),
      })
      const url = await buildHipsUrl('DSS2Merged', 'Norder3/index.png')
      expect(url).toBe(
        'https://aladin.u-strasbg.fr/DSS2Merged/Norder3/index.png',
      )
      // Verify single slash between endpoint and fullPath
      expect(url).not.toMatch(/u-strasbg\.fr\/\/+DSS2Merged/)
    })

    it('falls back when fetch returns ok but no endpoint in body', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ok: false }),
      })
      const url = await buildHipsUrl('P/DSS2/DSS2Merged', 'tile.png')
      expect(url).toMatch(/^https:\/\/alasky\.cds\.unistra\.fr\//)
    })

    it('falls back when fetch returns non-ok status', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 })
      const url = await buildHipsUrl('DSS2Merged', 'tile.png')
      expect(url).toMatch(/^https:\/\/alasky\.cds\.unistra\.fr\//)
    })

    it('adds leading slash to tilePath when missing', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('fail'))
      const url = await buildHipsUrl('survey', 'no-leading-slash.png')
      expect(url).toContain('/survey/no-leading-slash.png')
    })

    it('strips leading slashes from combined fullPath', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('fail'))
      const url = await buildHipsUrl('/survey', '/tile.png')
      expect(url).not.toMatch(/https:\/\/[^/]+\/\/+/)
      expect(url).toMatch(/survey\/tile\.png$/)
    })

    it('uses cache on second call within TTL', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr',
          ok: true,
        }),
      })
      globalThis.fetch = fetchMock
      const u1 = await buildHipsUrl('X', 'a.png')
      const u2 = await buildHipsUrl('X', 'a.png')
      expect(u1).toBe(u2)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('uses different cache keys for different fullPaths', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr',
          ok: true,
        }),
      })
      globalThis.fetch = fetchMock
      await buildHipsUrl('X', 'a.png')
      await buildHipsUrl('X', 'b.png')
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  describe('clearHipsCache', () => {
    it('clears cache so subsequent call hits fetch again', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr',
          ok: true,
        }),
      })
      globalThis.fetch = fetchMock
      await buildHipsUrl('X', 'a.png')
      expect(fetchMock).toHaveBeenCalledTimes(1)
      clearHipsCache()
      await buildHipsUrl('X', 'a.png')
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  // R6.61.a: localStorage persistence + preconnect
  describe('R6.61.a localStorage persistence', () => {
    it('writes entry to localStorage on backend resolve', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ endpoint: 'https://aladin.u-strasbg.fr', ok: true }),
      })
      await buildHipsUrl('surveyA', 'tile.png')
      const keys: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('gw-hips-v1:')) keys.push(k)
      }
      expect(keys.length).toBe(1)
      const v = JSON.parse(localStorage.getItem(keys[0]) || '{}')
      expect(v.endpoint).toBe('https://aladin.u-strasbg.fr')
      expect(v.ok).toBe(true)
      expect(typeof v.ts).toBe('number')
    })

    it('reads from localStorage on second call (no fetch)', async () => {
      globalThis.fetch = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ endpoint: 'https://aladin.u-strasbg.fr', ok: true }),
        })
      // First call - populate localStorage
      const u1 = await buildHipsUrl('surveyB', 'tile.png')
      // Second call - should hit localStorage, not fetch
      const fetchCallsBefore = (globalThis.fetch as any).mock.calls.length
      const u2 = await buildHipsUrl('surveyB', 'tile.png')
      const fetchCallsAfter = (globalThis.fetch as any).mock.calls.length
      expect(u1).toBe(u2)
      expect(fetchCallsAfter).toBe(fetchCallsBefore)
    })

    it('uses fallback as endpoint when fetch fails', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('fail'))
      await buildHipsUrl('surveyC', 'tile.png')
      // localStorage should have fallback entry
      const keys: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('gw-hips-v1:')) keys.push(k)
      }
      expect(keys.length).toBeGreaterThanOrEqual(1)
    })

    it('clearHipsCache also clears localStorage entries', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ endpoint: 'https://aladin.u-strasbg.fr', ok: true }),
      })
      await buildHipsUrl('surveyD', 'tile.png')
      let count = 0
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('gw-hips-v1:')) count++
      }
      expect(count).toBeGreaterThanOrEqual(1)
      clearHipsCache()
      count = 0
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k && k.startsWith('gw-hips-v1:')) count++
      }
      expect(count).toBe(0)
    })

    it('expired localStorage entries are skipped (24h TTL)', async () => {
      // Write an expired entry under a DIFFERENT key so we can verify it's deleted
      // without conflating with the fallback entry that buildHipsUrl will write.
      const expiredKey = 'gw-hips-v1:hips:expiredSurvey/oldTile.png'
      const expiredTs = Date.now() - 25 * 60 * 60 * 1000 // 25h ago
      localStorage.setItem(
        expiredKey,
        JSON.stringify({ endpoint: 'https://aladin.u-strasbg.fr', ts: expiredTs, ok: true }),
      )
      // Calling readLsCache directly via buildHipsUrl with same survey/tile
      // verifies the expired entry path. Use a fresh survey to avoid the
      // memCache from buildHipsUrl writing the same key.
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ endpoint: 'https://alasky.cds.unistra.fr', ok: true }),
      })
      // Trigger a cache write under a DIFFERENT cache key
      await buildHipsUrl('freshSurvey', 'tile.png')
      // The expired key should have been deleted by readLsCache during any
      // prior buildHipsUrl call that touched it - but since we never did, it's
      // still there. Let's directly verify the read helper ignores expired.
      // Simulate by calling buildHipsUrl with the expired survey (will expire
      // readLsCache, then fetch fresh, then write new entry under same key)
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ endpoint: 'https://alasky.cds.unistra.fr', ok: true }),
      })
      await buildHipsUrl('expiredSurvey', 'oldTile.png')
      // After call: same key exists, but ts is fresh (NOT 25h-old)
      const v = JSON.parse(localStorage.getItem(expiredKey) || '{}')
      const ageMs = Date.now() - v.ts
      expect(ageMs).toBeLessThan(60_000) // fresh, not 25h old
    })
  })

  // R6.61.a: preconnect (uses vi.resetModules to clear _preconnectFired state)
  describe('R6.61.a preconnect', () => {
    it('inserts 3 preconnect links on first call', async () => {
      vi.resetModules()
      const { preconnectHipsEndpoints: pc } = await import('../hips')
      document.querySelectorAll('link[rel="preconnect"]').forEach((l) => l.remove())
      pc()
      const links = document.querySelectorAll('link[rel="preconnect"]')
      expect(links.length).toBe(3)
      const hrefs = Array.from(links).map((l) => l.getAttribute('href'))
      expect(hrefs).toContain('https://alasky.cds.unistra.fr')
      expect(hrefs).toContain('https://aladin.u-strasbg.fr')
      expect(hrefs).toContain('https://archives.esac.esa.int')
    })

    it('is idempotent - second call adds no new links', async () => {
      vi.resetModules()
      const { preconnectHipsEndpoints: pc } = await import('../hips')
      document.querySelectorAll('link[rel="preconnect"]').forEach((l) => l.remove())
      pc()
      pc()
      pc()
      const links = document.querySelectorAll('link[rel="preconnect"]')
      expect(links.length).toBe(3)
    })
  })

  describe('fetchHipsTile', () => {
    it('returns Response when ok', async () => {
      const fakeResponse = { ok: true, status: 200 }
      globalThis.fetch = vi.fn().mockResolvedValue(fakeResponse)
      const r = await fetchHipsTile('DSS2Merged', 'tile.png')
      expect(r).toBe(fakeResponse)
    })

    it('returns null and clears cache when fetch ok is false', async () => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            endpoint: 'https://aladin.u-strasbg.fr',
            ok: true,
          }),
        })
        .mockResolvedValueOnce({ ok: false, status: 404 })
      globalThis.fetch = fetchMock
      const r = await fetchHipsTile('DSS2Merged', 'tile.png')
      expect(r).toBeNull()
      const callsBefore = fetchMock.mock.calls.length
      await fetchHipsTile('DSS2Merged', 'tile.png')
      const callsAfter = fetchMock.mock.calls.length
      expect(callsAfter).toBeGreaterThan(callsBefore)
    })

    it('returns null on fetch throw (network error)', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('network'))
      const r = await fetchHipsTile('DSS2Merged', 'tile.png')
      expect(r).toBeNull()
    })

    it('passes RequestInit to underlying fetch', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          endpoint: 'https://aladin.u-strasbg.fr',
          ok: true,
        }),
      })
      globalThis.fetch = fetchMock
      await fetchHipsTile('DSS2Merged', 'tile.png', { credentials: 'include' })
      const calls = fetchMock.mock.calls
      const passedInit = calls.some(
        (c) => c[1] && c[1].credentials === 'include',
      )
      expect(passedInit).toBe(true)
    })
  })
})
