/**
 * R6.18: Splash-Synchronized Preload Utility
 *
 * Pre-loads all images/FITS for a Multi-band Observation, tracking progress.
 * Designed to fire while the AliCPT splash is showing, so by the time the
 * user can click any tile, every URL is already in browser cache.
 *
 * Key features:
 *   - preloadImages(urls): returns Promise + progress callback
 *   - preloadFits(urls): fetches FITS bytes into browser cache
 *   - With 8s timeout fallback so UI never blocks longer than splash
 *   - fetchPriority='low' to not compete with page-load bandwidth
 */

export interface PreloadProgress {
  total: number
  done: number
  failed: number
  pct: number
  phase: 'thumbnails' | 'bigImages' | 'fits' | 'done'
}

export interface PreloadResult {
  thumbnails: Set<string>
  bigImages: Set<string>
  fits: Set<string>
}

// R6.27g: tighter timeouts + 90% force-settle (R6.27e honest pattern).
// User feedback: "splash 卡住 立即解决". With cloudflared tunnel sometimes
// blocking 1-2 HiPS tiles indefinitely, waiting 6-9.5s per observation feels
// broken. New behavior:
//   - Typical case (no zombies): splash hides when real work completes (~1-2s)
//   - One zombie: hide at 3s (per-URL hard timeout, was 6s)
//   - Many zombies: hide at 3s, splash still shows real counts so user knows
//   - 90% success: hide early even if 1 URL hangs forever (force-settle honest)
// R6.29b: Hi-Q URLs (/pipeline/hips-float, /pipeline/merge-rgb) take longer
// than Std (CDS direct jpg) because backend reads raw 32-bit FITS and applies
// Floyd-Steinberg dither. Empirical: Hi-Q 4-8s/tile vs Std 0.5-2s/tile.
// Per-URL timeout is URL-type-aware: Hi-Q gets 10s, Std keeps 3s.
// R6.103-J: removed unused TIMEOUT_MS global; replaced by per-type
// MAX(STD, HI_Q) + 1.5s guard = 11.5s (see preloadImages / preloadFits).
const STD_URL_TIMEOUT_MS = 3000
const HI_Q_URL_TIMEOUT_MS = 10000
// R6.103-J: 6-way concurrency cap. Chrome limits per-host connections to 6;
// firing 50 URLs simultaneously serializes through this bottleneck AND
// saturates bandwidth. Worker-pool pattern: 6 workers share one URL queue.
const CONCURRENCY = 6

/**
 * R6.29b: Determine per-URL timeout based on URL pattern.
 * Hi-Q URLs route through /pipeline/ (slow FITS pipeline).
 * Std URLs hit CDS directly (fast jpg).
 *
 * Exported for testing (v8 branch coverage requires direct calls).
 */
export function timeoutForUrl(url: string): number {
  if (
    url.includes('/pipeline/hips-float') ||
    url.includes('/pipeline/merge-rgb')
  ) {
    return HI_Q_URL_TIMEOUT_MS
  }
  return STD_URL_TIMEOUT_MS
}
/** Pre-load a list of image URLs into browser cache, with progress callback. */
export function preloadImages(
  urls: string[],
  onProgress?: (done: number, total: number) => void,
): Promise<Set<string>> {
  const done = new Set<string>()
  if (urls.length === 0) return Promise.resolve(done)

  return new Promise((resolve) => {
    let finished = 0
    const total = urls.length
    let resolved = false
    const finish = () => {
      if (resolved) return
      resolved = true
      resolve(done)
    }
    // R6.27g global guard: TIMEOUT_MS + 1.5s = 4.5s max. Per-URL 3s catches
    // zombies fast; this is the absolute backstop in case tick logic somehow misses.
    // R6.103-J: Hi-Q-aware global guard. Was TIMEOUT_MS (3s) + 1.5s = 4.5s;
    // Hi-Q tiles take 4-8s each (per [[mbpanel-divs-thumbnails]] empirical),
    // so splash closed before Hi-Q completed -> tiles appear one-by-one after.
    // New guard = MAX(STD, HI_Q) + 1.5s = 11.5s backstop.
    const MAX_PER_URL_MS = Math.max(STD_URL_TIMEOUT_MS, HI_Q_URL_TIMEOUT_MS)
    const guard = setTimeout(finish, MAX_PER_URL_MS + 1500)

    const tick = () => {
      onProgress?.(finished, total)
      if (finished >= total) {
        clearTimeout(guard)
        finish()
      }
    }

    // R6.103-J: worker-pool pattern (CONCURRENCY=6). Each worker pulls the
    // next URL from a shared cursor when its current load settles. Matches
    // Chrome per-host connection cap so we do not queue behind ourselves.
    // R6.27e honesty preserved: per-URL timeout still = fail, not success.
    let cursor = 0
    const worker = async (): Promise<void> => {
      while (cursor < total) {
        const idx = cursor++
        const url = urls[idx]
        await new Promise<void>((resolveOne) => {
          const img = new Image()
          img.decoding = 'async'
          ;(img as HTMLImageElement).fetchPriority = 'low'
          let settled = false
          const settle = (succeeded: boolean) => {
            if (settled) return
            settled = true
            if (succeeded) done.add(url)
            finished++
            tick()
            resolveOne()
          }
          const perTimer = setTimeout(() => settle(false), timeoutForUrl(url))
          img.onload = () => {
            clearTimeout(perTimer)
            settle(true)
          }
          img.onerror = () => {
            clearTimeout(perTimer)
            settle(false)
          }
          img.src = url
        })
      }
    }
    const workerCount = Math.min(CONCURRENCY, total)
    const workers = Array.from({ length: workerCount }, () => worker())
    Promise.all(workers).then(finish)
  })
}

/** Pre-load FITS bytes into browser cache via fetch. */
export function preloadFits(
  urls: string[],
  onProgress?: (done: number, total: number) => void,
): Promise<Set<string>> {
  const done = new Set<string>()
  if (urls.length === 0) return Promise.resolve(done)

  return new Promise((resolve) => {
    let finished = 0
    const total = urls.length
    let resolved = false
    const finish = () => {
      if (resolved) return
      resolved = true
      resolve(done)
    }
    // R6.103-J: Hi-Q-aware global guard. Was TIMEOUT_MS (3s) + 1.5s = 4.5s;
    // Hi-Q tiles take 4-8s each (per [[mbpanel-divs-thumbnails]] empirical),
    // so splash closed before Hi-Q completed -> tiles appear one-by-one after.
    // New guard = MAX(STD, HI_Q) + 1.5s = 11.5s backstop.
    const MAX_PER_URL_MS = Math.max(STD_URL_TIMEOUT_MS, HI_Q_URL_TIMEOUT_MS)
    const guard = setTimeout(finish, MAX_PER_URL_MS + 1500)

    const tick = () => {
      onProgress?.(finished, total)
      if (finished >= total) {
        clearTimeout(guard)
        finish()
      }
    }

    // R6.103-J: worker-pool pattern (CONCURRENCY=6). Same rationale as
    // preloadImages. R6.27e honesty preserved: AbortController + per-URL
    // timeout still = fail, not success; .finally() handles finished++.
    let cursor = 0
    const worker = async (): Promise<void> => {
      while (cursor < total) {
        const idx = cursor++
        const url = urls[idx]
        await new Promise<void>((resolveOne) => {
          const ac = new AbortController()
          const perTimer = setTimeout(() => ac.abort(), timeoutForUrl(url))
          fetch(url, { credentials: 'same-origin', signal: ac.signal })
            .then((r) => {
              if (r.ok) done.add(url)
              return r.blob()
            })
            .catch(() => {
              /* abort or HTTP error - don't cache */
            })
            .finally(() => {
              clearTimeout(perTimer)
              finished++
              tick()
              resolveOne()
            })
        })
      }
    }
    const workerCount = Math.min(CONCURRENCY, total)
    const workers = Array.from({ length: workerCount }, () => worker())
    Promise.all(workers).then(finish)
  })
}

/** React-style reactive tracker: subscribe to update events for cache progress. */
export class PreloadTracker {
  private cached = new Set<string>()
  private pending = new Set<string>()
  private listeners: Array<() => void> = []

  isReady(url: string): boolean {
    return this.cached.has(url)
  }
  get cachedCount(): number {
    return this.cached.size
  }
  get pendingCount(): number {
    return this.pending.size
  }

  begin(url: string): boolean {
    if (this.cached.has(url)) return true
    this.pending.add(url)
    return false
  }

  complete(url: string) {
    this.pending.delete(url)
    this.cached.add(url)
    this.listeners.forEach((fn) => fn())
  }

  subscribe(fn: () => void): () => void {
    this.listeners.push(fn)
    return () => {
      this.listeners = this.listeners.filter((x) => x !== fn)
    }
  }
}
