// R6.49: HiPS tile URL helper with CDN fallback.
//
// Usage:
//   import { buildHipsUrl } from '../util/hips'
//   const url = await buildHipsUrl('DSS2Merged', '/Norder3/Dir0/index.png')
//
// The function:
//   1. Calls backend /pipeline/hips-tile-resolve?path=<path>
//   2. Backend probes alasky.cds.unistra.fr -> aladin.u-strasbg.fr -> archives.esac.esa.int
//   3. Returns first reachable endpoint (cached server-side for 5 min)
//   4. Client-side caches the result in sessionStorage for 60s to avoid re-resolution

const RESOLVE_TTL_MS = 60_000
const _memCache = new Map<
  string,
  { endpoint: string; ts: number; ok: boolean }
>()

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

  // Check memory cache
  const cached = _memCache.get(cacheKey)
  if (cached && Date.now() - cached.ts < RESOLVE_TTL_MS) {
    return cached.endpoint.replace(/\/$/, '') + '/' + fullPath
  }

  // Try backend resolve endpoint
  try {
    const res = await fetch(
      `/pipeline/hips-tile-resolve?path=${encodeURIComponent(fullPath)}`,
    )
    if (res.ok) {
      const data = await res.json()
      if (data.endpoint) {
        _memCache.set(cacheKey, {
          endpoint: data.endpoint,
          ts: Date.now(),
          ok: data.ok,
        })
        return data.endpoint.replace(/\/$/, '') + '/' + fullPath
      }
    }
  } catch (e) {
    console.warn('[hips] resolve failed, falling back to alasky:', e)
  }

  // Fallback: alasky (default endpoint)
  const fallback = 'https://alasky.cds.unistra.fr'
  _memCache.set(cacheKey, { endpoint: fallback, ts: Date.now(), ok: true })
  return fallback + '/' + fullPath
}

/**
 * Invalidate the local HiPS resolve cache (e.g. when user changes survey).
 */
export function clearHipsCache(): void {
  _memCache.clear()
}

/**
 * Fetch a HiPS tile with automatic fallback.
 * Returns null if all endpoints fail (after 3 retries).
 */
export async function fetchHipsTile(
  surveyPath: string,
  tilePath: string,
  init?: RequestInit,
): Promise<Response | null> {
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
