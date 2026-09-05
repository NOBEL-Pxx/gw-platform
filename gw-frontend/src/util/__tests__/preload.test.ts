import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { preloadImages, preloadFits, PreloadTracker, timeoutForUrl } from '../preload'

// Mock Image constructor so we can deterministically trigger onload/onerror.
// The preload utility stores handlers as img.onload / img.onerror so we
// capture them and fire them manually when the test sets img.src.
type MockImageInstance = {
  onload: (() => void) | null
  onerror: (() => void) | null
  decoding: string
  fetchPriority: string
  _src: string
  src: string
  triggerLoad: () => void
  triggerError: () => void
}

function installImageMock() {
  const imgs: MockImageInstance[] = []

  const OriginalImage = globalThis.Image
  class MockImageCtor {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    decoding = ''
    fetchPriority = ''
    _src = ''
    get src() {
      return this._src
    }
    set src(v: string) {
      this._src = v
      imgs.push(this)
    }
    triggerLoad() {
      if (this.onload) this.onload()
    }
    triggerError() {
      if (this.onerror) this.onerror()
    }
  }
  globalThis.Image = MockImageCtor as unknown as typeof Image
  return {
    imgs,
    restore: () => {
      globalThis.Image = OriginalImage
    },
  }
}

describe('preload utility', () => {
  let originalFetch = globalThis.fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  describe('preloadImages', () => {
    let mock: ReturnType<typeof installImageMock>

    beforeEach(() => {
      mock = installImageMock()
    })

    afterEach(() => {
      mock.restore()
    })

    it('returns empty set immediately for empty input', async () => {
      const result = await preloadImages([])
      expect(result.size).toBe(0)
    })

    it('marks URL as done after onload fires', async () => {
      const promise = preloadImages(['http://x/y.png'])
      await Promise.resolve()
      await Promise.resolve()
      const img = mock.imgs[mock.imgs.length - 1]
      img.triggerLoad()
      const result = await promise
      expect(result.has('http://x/y.png')).toBe(true)
    })

    it('does NOT mark URL as done after onerror fires', async () => {
      const promise = preloadImages(['http://x/bad.png'])
      await Promise.resolve()
      await Promise.resolve()
      const img = mock.imgs[mock.imgs.length - 1]
      img.triggerError()
      const result = await promise
      expect(result.has('http://x/bad.png')).toBe(false)
    })

    it('handles multiple urls in parallel', async () => {
      const promise = preloadImages([
        'http://x/a.png',
        'http://x/b.png',
        'http://x/c.png',
      ])
      await Promise.resolve()
      await Promise.resolve()
      mock.imgs[1].triggerLoad()
      mock.imgs[0].triggerError()
      mock.imgs[2].triggerLoad()
      const result = await promise
      expect(result.has('http://x/a.png')).toBe(false)
      expect(result.has('http://x/b.png')).toBe(true)
      expect(result.has('http://x/c.png')).toBe(true)
    })

    it('handles empty list with progress callback', async () => {
      const onProgress = vi.fn()
      const result = await preloadImages([], onProgress)
      expect(result.size).toBe(0)
      expect(onProgress).not.toHaveBeenCalled()
    })

    it('returns a Promise resolving to Set', async () => {
      const p = preloadImages([])
      expect(p).toBeInstanceOf(Promise)
      const r = await p
      expect(r).toBeInstanceOf(Set)
    })

    it('calls onProgress with done/total per tick', async () => {
      const onProgress = vi.fn()
      const promise = preloadImages(
        ['http://x/a.png', 'http://x/b.png'],
        onProgress,
      )
      await Promise.resolve()
      await Promise.resolve()
      mock.imgs[0].triggerLoad()
      mock.imgs[1].triggerLoad()
      await promise
      expect(onProgress).toHaveBeenCalled()
      const last = onProgress.mock.calls[onProgress.mock.calls.length - 1]
      expect(last[0]).toBe(2)
      expect(last[1]).toBe(2)
    })

    it('sets decoding=async and fetchPriority=low on image', async () => {
      const promise = preloadImages(['http://x/a.png'])
      await Promise.resolve()
      await Promise.resolve()
      const img = mock.imgs[0]
      expect(img.decoding).toBe('async')
      expect(img.fetchPriority).toBe('low')
      img.triggerLoad()
      await promise
    })
  })

  describe('PreloadTracker', () => {
    it('begin() returns true for already-cached url', () => {
      const t = new PreloadTracker()
      expect(t.begin('a')).toBe(false)
      t.complete('a')
      expect(t.begin('a')).toBe(true)
    })

    it('begin() returns false first time', () => {
      const t = new PreloadTracker()
      expect(t.begin('foo')).toBe(false)
    })

    it('complete() moves from pending to cached', () => {
      const t = new PreloadTracker()
      t.begin('url')
      expect(t.pendingCount).toBe(1)
      expect(t.cachedCount).toBe(0)
      t.complete('url')
      expect(t.pendingCount).toBe(0)
      expect(t.cachedCount).toBe(1)
    })

    it('isReady() reflects cache membership', () => {
      const t = new PreloadTracker()
      expect(t.isReady('x')).toBe(false)
      t.begin('x')
      t.complete('x')
      expect(t.isReady('x')).toBe(true)
    })

    it('subscribe() invokes listener on complete()', () => {
      const t = new PreloadTracker()
      const fn = vi.fn()
      t.subscribe(fn)
      t.begin('u')
      t.complete('u')
      expect(fn).toHaveBeenCalledTimes(1)
    })

    it('subscribe() returns unsubscribe function', () => {
      const t = new PreloadTracker()
      const fn = vi.fn()
      const unsub = t.subscribe(fn)
      unsub()
      t.begin('u')
      t.complete('u')
      expect(fn).not.toHaveBeenCalled()
    })

    it('multiple subscribers all fire', () => {
      const t = new PreloadTracker()
      const fn1 = vi.fn()
      const fn2 = vi.fn()
      t.subscribe(fn1)
      t.subscribe(fn2)
      t.begin('u')
      t.complete('u')
      expect(fn1).toHaveBeenCalledTimes(1)
      expect(fn2).toHaveBeenCalledTimes(1)
    })

    it('handles multiple urls independently', () => {
      const t = new PreloadTracker()
      t.begin('a')
      t.begin('b')
      expect(t.pendingCount).toBe(2)
      t.complete('a')
      expect(t.pendingCount).toBe(1)
      expect(t.cachedCount).toBe(1)
      t.complete('b')
      expect(t.pendingCount).toBe(0)
      expect(t.cachedCount).toBe(2)
    })
  })

describe('timeoutForUrl', () => {
    it('returns 10s for /pipeline/hips-float URLs (Hi-Q mode)', () => {
      // v8 branch coverage: true-branch of the `||` for /pipeline/hips-float.
      expect(timeoutForUrl('http://x/pipeline/hips-float?fov=2&object=test')).toBe(10000)
    })

    it('returns 10s for /pipeline/merge-rgb URLs (Hi-Q mode)', () => {
      // v8 branch coverage: true-branch of the `||` for /pipeline/merge-rgb.
      expect(timeoutForUrl('http://x/pipeline/merge-rgb?r_file=a&g_file=b&b_file=c')).toBe(10000)
    })

    it('returns 3s for CDS direct JPG URLs (Std mode)', () => {
      // v8 branch coverage: false-branch (both includes() return false).
      expect(timeoutForUrl('http://alasky.unistra.fr/DSS2/Norder3.jpg')).toBe(3000)
    })

    it('returns 3s for empty string', () => {
      expect(timeoutForUrl('')).toBe(3000)
    })
  })

  describe('preloadFits', () => {
    it('returns empty set for empty input', async () => {
      const r = await preloadFits([])
      expect(r.size).toBe(0)
    })

    it('caches URL when fetch returns ok', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => new Blob(['fits-data']),
      })
      const r = await preloadFits(['http://x/fit.fits'])
      expect(r.has('http://x/fit.fits')).toBe(true)
    })

    it('does not cache URL when fetch returns not-ok', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        blob: async () => new Blob(),
      })
      const r = await preloadFits(['http://x/missing.fits'])
      expect(r.has('http://x/missing.fits')).toBe(false)
      expect(r.size).toBe(0)
    })

    it('does not cache URL when fetch rejects', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('net'))
      const r = await preloadFits(['http://x/fit.fits'])
      expect(r.has('http://x/fit.fits')).toBe(false)
    })

    it('does not cache URL when fetch is aborted', async () => {
      globalThis.fetch = vi
        .fn()
        .mockImplementation(
          (_url: string, init?: RequestInit): Promise<unknown> => {
            return new Promise((_resolve, reject) => {
              init?.signal?.addEventListener('abort', () => {
                const e = new Error('aborted')
                e.name = 'AbortError'
                reject(e)
              })
            })
          },
        )
      const r = await preloadFits(['http://x/fit.fits'])
      expect(r.has('http://x/fit.fits')).toBe(false)
    })

    it('handles multiple URLs in parallel', async () => {
      // Simulate one URL hanging while another completes immediately.
      // Use a deferred object pattern to avoid TS narrowing issues with closure
      // assignment of Promise resolve functions.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const deferred: { resolve?: (v: any) => void } = {}
      const firstPromise = new Promise<unknown>((resolve) => {
        deferred.resolve = resolve
      })
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        if (url === 'http://x/a.fits') return firstPromise
        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['ok']),
        })
      })
      const promise = preloadFits(['http://x/a.fits', 'http://x/b.fits'])
      // Wait a tick so the b.fits fetch completes first
      await new Promise((r) => setTimeout(r, 10))
      // Now release the first one so the promise resolves
      if (deferred.resolve)
        deferred.resolve({ ok: true, blob: async () => new Blob() })
      const r = await promise
      expect(r.has('http://x/b.fits')).toBe(true)
    })

    it('calls onProgress with done and total counts', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => new Blob(),
      })
      const onProgress = vi.fn()
      await preloadFits(['http://x/a', 'http://x/b'], onProgress)
      expect(onProgress).toHaveBeenCalled()
      const lastCall = onProgress.mock.calls[onProgress.mock.calls.length - 1]
      expect(lastCall[0]).toBe(2)
      expect(lastCall[1]).toBe(2)
    })
  })
})
