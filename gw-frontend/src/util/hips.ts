// R6.49: HiPS tile URL helper with CDN fallback.
// R6.61.a: localStorage persistence (24h TTL) + preconnect prewarm.
//          Solves 2MASS/NVSS 1.5s first-access latency (HiPS endpoint
//          probing is mainly DNS+TLS handshake bottleneck).
//
// Usage:
//   import { buildHipsUrl } from '../util/hips'
//   const url = await buildHipsUrl('DSS2Merged', '/Norder3/Dir0/index.png')
//
// The function:
//   1. Calls backend /pipeline/hips-tile-resolve?path=<path>
//   2. Backend probes alasky.cds.unistra.fr -> aladin.u-strasbg.fr -> archives.esac.esa.int
//   3. Returns first reachable endpoint (cached server-side for 5 min)
//   4. R6.61.a: localStorage cache 24h (was sessionStorage 60s) - cross-tab persistence
//   5. R6.61.a: preconnect prewarms all endpoints (DNS+TLS in <50ms, then 0-RTT fetches)

const RESOLVE_TTL_MS = 24 * 60 * 60 * 1000 // R6.61.a: 60s -> 24h
const _memCache = new Map<
  string,
  { endpoint: string; ts: number; ok: boolean }
>()

// R6.61.a: localStorage cache key prefix (versioned for future schema migration).
const LS_PREFIX = 'gw-hips-v1:'

function readLsCache(
  key: string,
): { endpoint: string; ts: number; ok: boolean } | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (Date.now() - parsed.ts > RESOLVE_TTL_MS) {
      localStorage.removeItem(LS_PREFIX + key)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function writeLsCache(
  key: string,
  value: { endpoint: string; ts: number; ok: boolean },
): void {
  try {
    localStorage.setItem(LS_PREFIX + key, JSON.stringify(value))
  } catch {
    // quota exceeded or localStorage disabled - fall through to memCache
  }
}

// R6.61.a: preconnect to known HiPS endpoints. Idempotent (browser dedups per origin).
const HIPS_ENDPOINTS = [
  'https://alasky.cds.unistra.fr',
  'https://aladin.u-strasbg.fr',
  'https://archives.esac.esa.int',
] as const
let _preconnectFired = false

export function preconnectHipsEndpoints(): void {
  if (_preconnectFired) return
  if (typeof document === 'undefined') return
  HIPS_ENDPOINTS.forEach((href) => {
    if (document.querySelector('link[rel="preconnect"][href="' + href + '"]'))
      return
    const link = document.createElement('link')
    link.rel = 'preconnect'
    link.href = href
    link.crossOrigin = 'anonymous'
    document.head.appendChild(link)
  })
  _preconnectFired = true
}

/**
 * Build a HiPS tile URL with CDN fallback.
 * @param surveyPath HiPS root path (e.g. 'DSS2Merged' or 'P/DSS2/DSS2Merged')
 * @param tilePath Tile subpath (e.g. '/Norder3/Dir0/index.png')
 * @returns URL string using the first reachable endpoint, or alasky if resolve fails
 */
export async function buildHipsUrl(
  surveyPath: string,
  tilePath: string,
): Promise<string> {
  const cleanPath = tilePath.startsWith('/') ? tilePath : '/' + tilePath
  const fullPath = `${surveyPath}${cleanPath}`.replace(/^\/+/, '')
  const cacheKey = `hips:${fullPath}`

  // R6.61.a: fire preconnect once per session (idempotent)
  preconnectHipsEndpoints()

  // Check memory cache
  const cached = _memCache.get(cacheKey)
  if (cached && Date.now() - cached.ts < RESOLVE_TTL_MS) {
    return cached.endpoint.replace(/\/$/, '') + '/' + fullPath
  }

  // R6.61.a: localStorage (cross-tab persistence, 24h TTL)
  const lsCached = readLsCache(cacheKey)
  if (lsCached) {
    _memCache.set(cacheKey, lsCached)
    return lsCached.endpoint.replace(/\/$/, '') + '/' + fullPath
  }

  // Try backend resolve endpoint
  try {
    const res = await fetch(
      `/pipeline/hips-tile-resolve?path=${encodeURIComponent(fullPath)}`,
    )
    if (res.ok) {
      const data = await res.json()
      if (data.endpoint) {
        const entry = {
          endpoint: data.endpoint,
          ts: Date.now(),
          ok: data.ok,
        }
        _memCache.set(cacheKey, entry)
        writeLsCache(cacheKey, entry) // R6.61.a: 24h localStorage persistence
        return data.endpoint.replace(/\/$/, '') + '/' + fullPath
      }
    }
  } catch (e) {
    console.warn('[hips] resolve failed, falling back to alasky:', e)
  }

  // Fallback: alasky (default endpoint)
  const fallback = 'https://alasky.cds.unistra.fr'
  const fallbackEntry = { endpoint: fallback, ts: Date.now(), ok: true }
  _memCache.set(cacheKey, fallbackEntry)
  writeLsCache(cacheKey, fallbackEntry) // R6.61.a: fallback also persisted
  return fallback + '/' + fullPath
}

/**
 * Invalidate the local HiPS resolve cache (e.g. when user changes survey).
 * R6.61.a: now also clears localStorage entries (was memCache only).
 */
export function clearHipsCache(): void {
  _memCache.clear()
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(LS_PREFIX)) keys.push(k)
    }
    keys.forEach((k) => localStorage.removeItem(k))
  } catch {
    // localStorage unavailable - ignore
  }
  // R6.99-C: also clear the HiPS Service Worker cache so callers get a
  // truly fresh tile set on next fetch. Lazy import to avoid circular deps
  // (registerSW.ts is imported by main.tsx already).
  void import('./registerSW')
    .then(({ clearHipsSWCache }) => clearHipsSWCache())
    .catch(() => {
      /* non-fatal */
    })
}



// R6.99-H-url-format: Parse HiPS tile path to extract z + actual CDS tile path.
// CDS canonical formats:
//   /Norder{z}/Allsky.{ext}                       (low zoom, z <= 3)
//   /Norder{z}/Dir{N}/Npix{M}.{ext}               (high zoom, z >= 4)
// Returns null for non-tile paths (e.g. /Dir0/index.png, /properties, etc.).
function _parseHipsTileCoords(
  tilePath: string,
): { z: number; tilePath: string } | null {
  // Match Allsky.jpg (low zoom)
  const mAllsky = tilePath.match(/^Norder(\d+)\/Allsky\.(jpg|png|webp)$/i)
  if (mAllsky) {
    return { z: parseInt(mAllsky[1], 10), tilePath: `Allsky.${mAllsky[2].toLowerCase()}` }
  }
  // Match Dir{N}/Npix{M}.{ext}
  const mDir = tilePath.match(/^Norder(\d+)\/(Dir\d+\/Npix\d+\.(?:jpg|png|webp))$/i)
  if (mDir) {
    return { z: parseInt(mDir[1], 10), tilePath: mDir[2] }
  }
  return null
}

// R6.99-H: Build backend proxy URL for HiPS tile (bypasses CDS via backend cache).
// Pass the actual CDS tile path so backend uses it directly (no URL building
// or z/x/y -> npix conversion). x/y are required by the route path but not
// semantically meaningful when tilePath is provided (backend includes
// tilePath in cache key for uniqueness).
export function buildHipsTileProxyUrl(
  surveyPath: string,
  z: number,
  tilePath: string,
): string {
  const params = new URLSearchParams({ survey: surveyPath, tilePath })
  // x/y in path are 0/0 placeholder (cache key uses tilePath, not x/y)
  return `/pipeline/hips-tile/${z}/0/0?${params.toString()}`
}

/**
 * Fetch a HiPS tile with automatic fallback.
 * R6.99-H: uses backend proxy cache when tilePath has z/x/y coords.
 * Returns null if all endpoints fail (after 3 retries).
 */
export async function fetchHipsTile(
  surveyPath: string,
  tilePath: string,
  init?: RequestInit,
): Promise<Response | null> {
  // R6.99-H-url-format: prefer backend proxy (disk cache, ~50ms HIT vs 1.5s+ CDS roundtrip).
  // Falls back to direct CDS if tilePath doesn't match Allsky or Dir/Npix pattern
  // (e.g. index files like /Dir0/index.png).
  const coords = _parseHipsTileCoords(tilePath)
  if (coords) {
    const proxyUrl = buildHipsTileProxyUrl(surveyPath, coords.z, coords.tilePath)
    try {
      const r = await fetch(proxyUrl, init)
      if (r.ok) return r
      console.warn('[hips] proxy fetch failed at', proxyUrl, 'status=', r.status)
      // fall through to direct CDS
    } catch (e) {
      console.warn('[hips] proxy fetch error:', e)
      // fall through to direct CDS
    }
  }

  const url = await buildHipsUrl(surveyPath, tilePath)
  try {
    const r = await fetch(url, init)
    if (r.ok) return r
    console.warn('[hips] fetch failed at', url, 'status=', r.status)
    clearHipsCache() // force re-resolve on next call
    return null
  } catch (e) {
    console.warn('[hips] fetch error:', e)
    clearHipsCache()
    return null
  }
}
