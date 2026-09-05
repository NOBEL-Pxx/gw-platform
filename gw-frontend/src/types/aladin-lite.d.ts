// Aladin Lite loaded via CDN script in index.html
// Provides global 'A' object
declare const A: {
  init: Promise<void>
  aladin: (
    container: string | HTMLElement,
    options?: Record<string, unknown>,
  ) => unknown
  image: (url: string, options?: Record<string, unknown>) => unknown
  catalog: (options?: Record<string, unknown>) => unknown
  source: (ra: number, dec: number, data?: Record<string, unknown>) => unknown
  MOCFromJSON: (json: unknown, options?: Record<string, unknown>) => unknown
}
