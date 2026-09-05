import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { buildHipsUrl, clearHipsCache, fetchHipsTile } from '../hips'

describe('hips utility', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    clearHipsCache()
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
