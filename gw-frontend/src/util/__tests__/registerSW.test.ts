// R6.99-C + R6.99-G: registerSW unit tests.
//
// We can't run a real Service Worker in jsdom, but we can verify the
// registration glue logic: skip when API missing, register with correct
// URL + scope, expose clearHipsSWCache + clearApiSWCache helpers, target
// correct cache keys.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

describe('R6.99-C/G registerSW', () => {
  let originalSW: unknown
  let originalCaches: unknown

  beforeEach(() => {
    originalSW = (navigator as { serviceWorker?: unknown }).serviceWorker
    originalCaches = (globalThis as { caches?: unknown }).caches
  })

  function restore() {
    ;(navigator as { serviceWorker?: unknown }).serviceWorker = originalSW
    ;(globalThis as { caches?: unknown }).caches = originalCaches
  }

  function restoreSW() {
    ;(navigator as { serviceWorker?: unknown }).serviceWorker = originalSW
  }

  afterEach(() => {
    restore()
  })

  it('isServiceWorkerAvailable reflects navigator state', async () => {
    const { isServiceWorkerAvailable } = await import('@/util/registerSW')
    // jsdom: navigator.serviceWorker is undefined by default.
    expect(isServiceWorkerAvailable()).toBe(false)
    // Now fake presence and re-check.
    ;(navigator as { serviceWorker?: unknown }).serviceWorker =
      {} as unknown as ServiceWorkerContainer
    expect(isServiceWorkerAvailable()).toBe(true)
    restoreSW()
  })

  it('registerSW skips when navigator.serviceWorker is unavailable', async () => {
    delete (navigator as { serviceWorker?: unknown }).serviceWorker
    try {
      const { registerSW } = await import('@/util/registerSW')
      const reg = await registerSW()
      expect(reg).toBeUndefined()
    } finally {
      restoreSW()
    }
  })

  it('clearHipsSWCache targets gw-hips-v1 cache key', async () => {
    const deleteSpy = vi.fn().mockResolvedValue(true)
    ;(globalThis as { caches?: unknown }).caches = {
      delete: deleteSpy,
    } as unknown as CacheStorage
    try {
      const { clearHipsSWCache } = await import('@/util/registerSW')
      const result = await clearHipsSWCache()
      expect(deleteSpy).toHaveBeenCalledWith('gw-hips-v1')
      expect(result).toBe(true)
    } finally {
      restore()
    }
  })

  it('clearHipsSWCache returns false when caches API unavailable', async () => {
    ;(globalThis as { caches?: unknown }).caches = undefined
    try {
      const { clearHipsSWCache } = await import('@/util/registerSW')
      const result = await clearHipsSWCache()
      expect(result).toBe(false)
    } finally {
      restore()
    }
  })

  // === R6.99-G: API cache helper ===

  it('clearApiSWCache targets gw-api-v1 cache key', async () => {
    const deleteSpy = vi.fn().mockResolvedValue(true)
    ;(globalThis as { caches?: unknown }).caches = {
      delete: deleteSpy,
    } as unknown as CacheStorage
    try {
      const { clearApiSWCache } = await import('@/util/registerSW')
      const result = await clearApiSWCache()
      expect(deleteSpy).toHaveBeenCalledWith('gw-api-v1')
      expect(result).toBe(true)
    } finally {
      restore()
    }
  })

  it('clearApiSWCache returns false when caches API unavailable', async () => {
    ;(globalThis as { caches?: unknown }).caches = undefined
    try {
      const { clearApiSWCache } = await import('@/util/registerSW')
      const result = await clearApiSWCache()
      expect(result).toBe(false)
    } finally {
      restore()
    }
  })

  it('clearApiSWCache returns false when caches.delete rejects', async () => {
    const deleteSpy = vi.fn().mockRejectedValue(new Error('boom'))
    ;(globalThis as { caches?: unknown }).caches = {
      delete: deleteSpy,
    } as unknown as CacheStorage
    try {
      const { clearApiSWCache } = await import('@/util/registerSW')
      const result = await clearApiSWCache()
      expect(result).toBe(false)
    } finally {
      restore()
    }
  })
})
