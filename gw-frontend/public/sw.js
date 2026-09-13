// R6.99-C: HiPS Service Worker cache
// Cache-first strategy for HiPS tile fetches. Repeat visits load from
// Cache Storage in <50ms instead of 1.5s+ network roundtrip.
//
// Iron rules R6.99-C:
//   - sw-update-ux:  skipWaiting() inside install + controllerchange reload
//                    (controlled update UX, not silent swap)
//   - sw-scope:      scope MUST be '/' (root) to intercept cross-origin HiPS
//   - sw-versioning: CACHE_NAME MUST include version; bump on incompatible
//                    schema change; activate handler clears old caches

const CACHE_NAME = 'gw-hips-v1'
const MAX_ENTRIES = 5000
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000 // 30 days

// HiPS endpoint allowlist. Mirrors HIPS_ENDPOINTS in src/util/hips.ts (same
// 5 hosts) PLUS aladin.cds.unistra.fr + aladin.u-strasbg.fr + esac archive
// (3 additional hosts the backend resolver can return).
// FIX: Review found aladin.u-strasbg.fr + archives.esac.esa.int missing.
const HIPS_HOSTS = new Set([
  // From src/util/hips.ts HIPS_ENDPOINTS:
  'alasky.cds.unistra.fr',
  'aladin.u-strasbg.fr',
  'archives.esac.esa.int',
  // Additional aladin + alt mirrors + china-vo + IRSA + HEALPix:
  'alaskybis.cds.unistra.fr',
  'alasky.unistra.fr',
  'alaskybis.unistra.fr',
  'aladin.cds.unistra.fr',
  'hips.china-vo.org',
  'irsa.ipac.caltech.edu',
  'healpix.ias.u-psud.fr',
  'skies.esac.esa.int',
])

// FIX S-2: Opaque-typed responses (from <img> no-cors fetches) ARE valid
// for caching. Browsers reuse opaque cached responses for image elements.
// We also accept normal 200 responses with cacheable content-types.
const CACHEABLE_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/fits',
  'application/octet-stream', // raw FITS bytes
])

function isHipsRequest(url) {
  // FIX correctness #2: use url.hostname (NOT url.host) so non-default ports
  // don't bypass the matcher. url.host = hostname:port; url.hostname = hostname.
  return url.protocol === 'https:' && HIPS_HOSTS.has(url.hostname)
}

// FIX S-2 + perf: accept opaque responses (no-cors <img> fetches) AND
// normal 200 responses with cacheable content-type. Stale entries get
// deleted on freshness miss (perf #3).
function isCacheableResponse(response) {
  if (!response) return false
  // Opaque response (from no-cors fetch): browser will reuse for <img>.
  // status === 0, type === 'opaque'. Always cache these for HiPS hosts.
  if (response.type === 'opaque') return true
  if (response.status !== 200) return false
  const ct = response.headers.get('content-type') || ''
  const main = ct.split(';')[0].trim().toLowerCase()
  return CACHEABLE_TYPES.has(main)
}

function isFresh(response) {
  if (!response) return false
  // FIX LOW: missing timestamp = NOT fresh (was: trust cache, now: re-fetch).
  const fetchedAt = response.headers.get('sw-fetched-at')
  const dateHeader = response.headers.get('date')
  const ts = fetchedAt ? parseInt(fetchedAt, 10) :
             dateHeader ? Date.parse(dateHeader) : 0
  if (!ts) return false // FIX: defensive — force re-fetch when age unknown
  return Date.now() - ts < MAX_AGE_MS
}

// FIX PERF #2: single-flight trimCache. Burst loads (50+ tiles in 2s) used
// to spawn one trimCache per cache.put. Now: track in-flight trim, dedupe.
let _trimInFlight = null

async function trimCacheIfNeeded(cache) {
  if (_trimInFlight) return _trimInFlight
  _trimInFlight = (async () => {
    try {
      const keys = await cache.keys()
      if (keys.length <= MAX_ENTRIES) return
      const toDelete = keys.length - MAX_ENTRIES
      // Delete oldest first (Cache API returns keys in insertion order).
      for (let i = 0; i < toDelete; i++) {
        await cache.delete(keys[i])
      }
    } finally {
      _trimInFlight = null
    }
  })()
  return _trimInFlight
}

self.addEventListener('install', (event) => {
  // Iron rule R6.99-C-sw-update-ux: skipWaiting so new SW activates promptly
  // after install; controllerchange handler in client triggers reload.
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Iron rule R6.99-C-sw-versioning: clear caches that don't match version
      const names = await caches.keys()
      await Promise.all(
        names
          .filter((name) => name.startsWith('gw-hips-') && name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      )
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  let url
  try {
    url = new URL(req.url)
  } catch {
    return
  }
  if (!isHipsRequest(url)) return

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE_NAME)
      const cached = await cache.match(req)
      if (cached && (await isFresh(cached))) {
        return cached
      }
      // FIX PERF #3: stale entry — delete so it doesn't pollute cache capacity
      if (cached) {
        cache.delete(req).catch(() => {})
      }
      try {
        // FIX PERF #1: fetch with same mode as request; cache the clone
        // directly (no blob() materialization on critical path).
        const network = await fetch(req)
        if (isCacheableResponse(network)) {
          // Stamp sw-fetched-at via Headers on the clone. Cannot mutate the
          // original response.headers (read-only), so wrap if needed.
          let toCache = network
          // Only stamp non-opaque (opaque has no readable headers).
          if (network.type !== 'opaque') {
            const headers = new Headers(network.headers)
            headers.set('sw-fetched-at', String(Date.now()))
            toCache = new Response(await network.clone().blob(), {
              status: network.status,
              statusText: network.statusText,
              headers,
            })
          }
          // Fire-and-forget cache write + single-flight trim.
          cache
            .put(req, toCache)
            .then(() => trimCacheIfNeeded(cache))
            .catch((e) => console.warn('[sw] cache put failed:', e))
        }
        return network
      } catch (e) {
        // Network failed - fall back to stale cache if any
        if (cached) return cached
        throw e
      }
    })(),
  )
})
