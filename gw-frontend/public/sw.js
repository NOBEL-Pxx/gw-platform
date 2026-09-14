// R6.99-C + R6.99-G: Service Worker — HiPS tile cache + /api/* /v3/* cache
// Both strategies share one SW; each has its own Cache Storage entry and lifecycle.
//
// R6.99-C: HiPS tile cache
//   cache-first strategy for HiPS tile fetches. Repeat visits load from
//   Cache Storage in <50ms instead of 1.5s+ network roundtrip.
//
// R6.99-G: API cache (NEW, 2026-09-14)
//   stale-while-revalidate for /api/* and /v3/* GETs. 60s fresh / 300s stale
//   window. Authorization-bearing requests bypass cache entirely. POST/PUT/
//   DELETE/PATCH trigger path-prefix cache invalidation.
//
// Iron rules:
//   R6.99-C-sw-update-ux:  skipWaiting() inside install + controllerchange reload
//   R6.99-C-sw-scope:      scope MUST be '/' (root) to intercept cross-origin HiPS
//   R6.99-C-sw-versioning: HIPS CACHE_NAME MUST include version; bump on schema change
//   R6.99-G-sw-versioning: API_CACHE_NAME MUST include version; separate from HIPS
//   R6.99-G-auth-isolation: ANY request with Authorization header MUST bypass cache
//   R6.99-G-stale-window:  60s fresh / 60-300s stale-while-revalidate / >300s refetch
//   R6.99-G-mutation-invalidation: non-GET requests to /api/* or /v3/* clear cached GETs

const HIPS_CACHE_NAME = 'gw-hips-v1'
const HIPS_MAX_ENTRIES = 5000
const HIPS_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000 // 30 days

const API_CACHE_NAME = 'gw-api-v1'
const API_FRESH_MS = 60 * 1000       // 60s: cache hit, no revalidate
const API_STALE_MS = 5 * 60 * 1000   // 5min: cache hit + background revalidate
const API_MAX_ENTRIES = 200          // ~200 x 20KB ~ 4MB cap

// HiPS endpoint allowlist (R6.99-C, unchanged)
const HIPS_HOSTS = new Set([
  'alasky.cds.unistra.fr',
  'aladin.u-strasbg.fr',
  'archives.esac.esa.int',
  'alaskybis.cds.unistra.fr',
  'alasky.unistra.fr',
  'alaskybis.unistra.fr',
  'aladin.cds.unistra.fr',
  'hips.china-vo.org',
  'irsa.ipac.caltech.edu',
  'healpix.ias.u-psud.fr',
  'skies.esac.esa.int',
])

// R6.99-G: API path prefixes that we cache (same-origin only)
const API_PATH_PREFIXES = ['/api/', '/v3/']

const HIPS_CACHEABLE_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/fits',
  'application/octet-stream',
])

function isHipsRequest(url) {
  return url.protocol === 'https:' && HIPS_HOSTS.has(url.hostname)
}

// R6.99-G: same-origin + path prefix
function isApiRequest(url) {
  if (url.protocol !== self.location.protocol) return false
  if (url.host !== self.location.host) return false
  return API_PATH_PREFIXES.some((p) => url.pathname.startsWith(p))
}

// R6.99-G-auth-isolation: ANY Authorization header -> bypass cache
function hasAuthHeader(req) {
  return req.headers.has('Authorization')
}

function isCacheableHipsResponse(response) {
  if (!response) return false
  if (response.type === 'opaque') return true
  if (response.status !== 200) return false
  const ct = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase()
  return HIPS_CACHEABLE_TYPES.has(ct)
}

// R6.99-G: respect backend Cache-Control: no-store / private signals
function isCacheableApiResponse(response) {
  if (!response || response.type === 'opaque') return false
  if (response.status !== 200) return false
  const cc = (response.headers.get('cache-control') || '').toLowerCase()
  if (cc.includes('no-store') || cc.includes('private')) return false
  const ct = response.headers.get('content-type') || ''
  return ct.includes('application/json') || ct.includes('text/')
}

function isFreshHips(response) {
  if (!response) return false
  const fetchedAt = response.headers.get('sw-fetched-at')
  const dateHeader = response.headers.get('date')
  const ts = fetchedAt ? parseInt(fetchedAt, 10) :
             dateHeader ? Date.parse(dateHeader) : 0
  if (!ts) return false
  return Date.now() - ts < HIPS_MAX_AGE_MS
}

// R6.99-G: 3-tier freshness — fresh / stale / expired
function apiCacheAge(response) {
  const fetchedAt = parseInt(response.headers.get('sw-fetched-at') || '0', 10)
  if (!fetchedAt) return Infinity
  return Date.now() - fetchedAt
}

// Single-flight trim (R6.99-C pattern, replicated for API cache)
const hipsTrimInFlight = { current: null }
const apiTrimInFlight = { current: null }

async function trimCacheIfNeeded(cache, maxEntries, ref) {
  if (ref.current) return ref.current
  ref.current = (async () => {
    try {
      const keys = await cache.keys()
      if (keys.length <= maxEntries) return
      const toDelete = keys.length - maxEntries
      for (let i = 0; i < toDelete; i++) {
        await cache.delete(keys[i])
      }
    } finally {
      ref.current = null
    }
  })()
  return ref.current
}

// Stamp sw-fetched-at on cacheable response (non-opaque only)
async function stampAndWrap(response) {
  if (response.type === 'opaque') return response
  const headers = new Headers(response.headers)
  headers.set('sw-fetched-at', String(Date.now()))
  return new Response(await response.clone().blob(), {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}

// === R6.99-C HiPS handler (unchanged behavior) ===
async function handleHipsRequest(req) {
  const cache = await caches.open(HIPS_CACHE_NAME)
  const cached = await cache.match(req)
  if (cached && (await isFreshHips(cached))) {
    return cached
  }
  if (cached) {
    cache.delete(req).catch(() => {})
  }
  try {
    const network = await fetch(req)
    if (isCacheableHipsResponse(network)) {
      const toCache = await stampAndWrap(network)
      cache
        .put(req, toCache)
        .then(() => trimCacheIfNeeded(cache, HIPS_MAX_ENTRIES, hipsTrimInFlight))
        .catch((e) => console.warn('[sw-hips] cache put failed:', e))
    }
    return network
  } catch (e) {
    if (cached) return cached
    throw e
  }
}

// === R6.99-G API handler (stale-while-revalidate) ===
async function handleApiRequest(req) {
  if (hasAuthHeader(req)) {
    return fetch(req)
  }
  const cache = await caches.open(API_CACHE_NAME)
  const cached = await cache.match(req)

  if (cached) {
    const age = apiCacheAge(cached)
    if (age < API_FRESH_MS) {
      return cached // fresh
    }
    if (age < API_STALE_MS) {
      // stale-while-revalidate: return cached NOW, refresh in background
      refreshApiInBackground(req, cache)
      return cached
    }
    // past stale window — drop and refetch
    cache.delete(req).catch(() => {})
  }

  // fetch fresh
  try {
    const network = await fetch(req)
    if (isCacheableApiResponse(network)) {
      const toCache = await stampAndWrap(network)
      cache
        .put(req, toCache)
        .then(() => trimCacheIfNeeded(cache, API_MAX_ENTRIES, apiTrimInFlight))
        .catch((e) => console.warn('[sw-api] cache put failed:', e))
    }
    return network
  } catch (e) {
    if (cached) return cached
    throw e
  }
}

// Background refresh: fire-and-forget; failures are silent
async function refreshApiInBackground(req, cache) {
  try {
    const network = await fetch(req)
    if (isCacheableApiResponse(network)) {
      const toCache = await stampAndWrap(network)
      await cache.put(req, toCache)
      await trimCacheIfNeeded(cache, API_MAX_ENTRIES, apiTrimInFlight)
    }
  } catch (e) {
    // silent — user already got stale cached response
  }
}

// R6.99-G-mutation-invalidation: clear cached GETs sharing the same path prefix
async function invalidateApiCacheByPrefix(req) {
  try {
    const url = new URL(req.url)
    if (!isApiRequest(url)) return
    const cache = await caches.open(API_CACHE_NAME)
    const keys = await cache.keys()
    const segs = url.pathname.split('/').filter(Boolean)
    const prefix = '/' + segs.slice(0, -1).join('/') + '/'
    await Promise.all(
      keys
        .filter((k) => {
          try {
            return new URL(k.url).pathname.startsWith(prefix)
          } catch {
            return false
          }
        })
        .map((k) => cache.delete(k)),
    )
  } catch (e) {
    console.warn('[sw-api] mutation invalidation failed:', e)
  }
}

// === Lifecycle ===
self.addEventListener('install', (event) => {
  // Iron rule R6.99-C-sw-update-ux: skipWaiting so new SW activates promptly
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys()
      // R6.99-C/G-sw-versioning: clean stale versioned caches for BOTH namespaces
      await Promise.all(
        names
          .filter(
            (name) =>
              (name.startsWith('gw-hips-') && name !== HIPS_CACHE_NAME) ||
              (name.startsWith('gw-api-') && name !== API_CACHE_NAME),
          )
          .map((name) => caches.delete(name)),
      )
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request

  // R6.99-G-mutation-invalidation: intercept mutations, invalidate after success
  if (
    req.method === 'POST' ||
    req.method === 'PUT' ||
    req.method === 'DELETE' ||
    req.method === 'PATCH'
  ) {
    let url
    try {
      url = new URL(req.url)
    } catch {
      return
    }
    if (isApiRequest(url)) {
      event.respondWith(
        (async () => {
          const response = await fetch(req)
          if (response.ok) {
            event.waitUntil(invalidateApiCacheByPrefix(req))
          }
          return response
        })(),
      )
      return
    }
    // non-API mutation: pass through
    return
  }

  // GET only from here
  if (req.method !== 'GET') return

  let url
  try {
    url = new URL(req.url)
  } catch {
    return
  }

  // Dispatch by strategy
  if (isHipsRequest(url)) {
    event.respondWith(handleHipsRequest(req))
    return
  }
  if (isApiRequest(url)) {
    // R6.99-G-auth-isolation: bypass cache for Authorization-bearing requests
    if (hasAuthHeader(req)) return
    event.respondWith(handleApiRequest(req))
    return
  }
  // everything else: pass through to network
})
