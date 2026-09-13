// R6.99-C: Service Worker registration glue.
//
// Registers /sw.js with scope '/' on app mount. Skips in dev to avoid stale
// SW state across HMR. Exposes clearHipsSWCache() for debugging via devtools
// or future "reset" buttons.
//
// Iron rules R6.99-C:
//   - sw-update-ux:  on controllerchange, reload to pick up new SW (version-keyed,
//                    not binary flag — fixes review finding PERF #5)
//   - sw-scope:      scope '/' is required for cross-origin HiPS interception

const SW_URL = '/sw.js'
const SW_SCOPE = '/'
// FIX PERF #5: track SW version instead of binary reload flag. Each NEW
// version triggers exactly one reload; future updates in same tab also reload.
const SW_VERSION_KEY = 'gw-sw-version'

export function isServiceWorkerAvailable(): boolean {
  return typeof navigator !== 'undefined' && 'serviceWorker' in navigator
}

/**
 * Register the HiPS Service Worker. Safe to call multiple times; the browser
 * dedupes. Returns the registration (or undefined in dev).
 */
export async function registerSW(): Promise<
  ServiceWorkerRegistration | undefined
> {
  // R6.99-C: skip in dev to keep HMR clean
  if (import.meta.env.DEV) return undefined
  if (!isServiceWorkerAvailable()) return undefined

  try {
    const reg = await navigator.serviceWorker.register(SW_URL, {
      scope: SW_SCOPE,
    })

    // FIX correctness MEDIUM #1: only attach controllerchange listener when
    // there IS already a controller. First install (controller was null) does
    // NOT trigger a reload — the page just gets controlled silently.
    if (navigator.serviceWorker.controller) {
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        // FIX PERF #5: compare SW scriptURL/version instead of binary flag.
        // Each NEW SW version triggers exactly one reload.
        const newSw = navigator.serviceWorker.controller
        if (!newSw) return
        const newVer = newSw.scriptURL + '@' + (reg.active?.state || 'unknown')
        const lastVer = sessionStorage.getItem(SW_VERSION_KEY)
        if (newVer === lastVer) return
        sessionStorage.setItem(SW_VERSION_KEY, newVer)
        window.location.reload()
      })
    } else {
      // No prior controller — this is first install. Don't reload.
      // Record initial version so future updates can be detected.
      const initialVer =
        (reg.active || reg.installing || reg.waiting)?.scriptURL || SW_URL
      sessionStorage.setItem(SW_VERSION_KEY, initialVer)
    }

    return reg
  } catch (e) {
    console.warn('[sw] registration failed:', e)
    return undefined
  }
}

/**
 * Clear the HiPS Service Worker cache. Useful for debugging when a stale
 * tile is suspected. Returns true on success.
 */
export async function clearHipsSWCache(): Promise<boolean> {
  if (!isServiceWorkerAvailable()) return false
  // FIX TEST: assert correct cache key. Also handle jsdom where caches is undefined.
  if (typeof caches === 'undefined') return false
  try {
    const deleted = await caches.delete('gw-hips-v1')
    return deleted
  } catch (e) {
    console.warn('[sw] cache delete failed:', e)
    return false
  }
}
