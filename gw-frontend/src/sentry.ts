// R6.45: Sentry SDK lazy init (DSN-gated).
//
// When VITE_SENTRY_DSN is unset (current production reality - no Sentry account),
// this module is a no-op and all calls fall through to the existing
// backend observability (/pipeline/observability/font-errors + ab-metrics).
//
// When VITE_SENTRY_DSN is set, this dynamically imports @sentry/react
// and initializes it with browserTracingIntegration, version-tagged release,
// 10% sample rate, and font-specific fingerprinting.
//
// Why lazy dynamic import:
//   - @sentry/react is ~50KB gzipped
//   - If no DSN, we don't pay the cost
//   - Vite code-splits the dynamic import → only loaded if DSN present
//
// Why keep backend observability in parallel:
//   - Lab has no Sentry account (cost + privacy)
//   - Backend SQLite is single source of truth for compliance
//   - When Sentry is added, both run side-by-side; can phase out backend later
//
// R6.47 release tracking: deploy.yml now sets VITE_APP_VERSION from ${{ github.ref_name }},
// so Sentry.init({ release }) gets the git tag automatically. Sentry UI shows deploys
// in timeline. No additional source changes needed.
// To enable Sentry:
//   1. `npm install @sentry/react`
//   2. Set VITE_SENTRY_DSN in .env (e.g. https://...@sentry.io/123)
//   3. (Optional) Set VITE_SENTRY_ENV=staging|production

// R6.57: narrow `import.meta as any` and `_sentry: any` to specific types
// so ESLint no-explicit-any warnings are eliminated while keeping the
// lazy dynamic-import pattern intact.

// Vite-typed env access (vite/client provides ImportMetaEnv types)
const SENTRY_DSN: string | undefined = import.meta.env.VITE_SENTRY_DSN
const SENTRY_PACKAGE = '@sentry/react' // string variable avoids build-time resolution
// R6.57: APP_VERSION injected at build time via vite.config.ts define.
// Fallback chain: VITE_APP_VERSION (build-time) -> hardcoded 'v4.62+R6.57' (dev fallback).
const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || 'v4.62+R6.57'
const APP_ENV: string = import.meta.env.MODE || 'production'

// Minimal Sentry capture interface — only the methods we use. Avoids `any`
// while still being compatible with the real @sentry/react API surface.
interface SentryLike {
  captureMessage(
    message: string,
    opts?: {
      level?: string
      tags?: Record<string, string>
      fingerprint?: string[]
    },
  ): void
  captureException(
    error: Error,
    opts?: { extra?: Record<string, unknown> },
  ): void
}

interface SentryEvent {
  exception?: { values?: Array<{ type?: string }> }
  fingerprint?: string[]
  tags?: Record<string, string>
}

interface SentryInitOptions {
  dsn: string
  release: string
  environment: string
  integrations: unknown[]
  tracesSampleRate: number
  beforeSend(event: SentryEvent): SentryEvent | null
}

let _initialized = false
let _sentry: SentryLike | null = null

export async function initSentry(): Promise<boolean> {
  if (_initialized) return true
  if (!SENTRY_DSN) {
    return false // No DSN → backend observability handles it
  }
  try {
    // String-based dynamic import = runtime only, Vite doesn't pre-bundle
    // @vite-ignore tells Vite to skip pre-bundling this dynamic import
    const Sentry = await import(/* @vite-ignore */ SENTRY_PACKAGE)
    const beforeSend = (event: SentryEvent): SentryEvent | null => {
      const hasFontFaceError =
        event.exception?.values?.some((v) => v.type?.includes('FontFace')) ??
        false
      if (hasFontFaceError) {
        event.fingerprint = ['font', String(event.tags?.family || 'unknown')]
      }
      return event
    }
    const opts: SentryInitOptions = {
      dsn: SENTRY_DSN,
      release: APP_VERSION,
      environment: APP_ENV,
      integrations: [
        (
          Sentry as unknown as {
            browserTracingIntegration: () => unknown
          }
        ).browserTracingIntegration(),
      ],
      tracesSampleRate: 0.1,
      beforeSend,
    }
    ;(Sentry as unknown as { init: (o: SentryInitOptions) => void }).init(opts)
    _sentry = Sentry as unknown as SentryLike
    _initialized = true

    console.info('[Sentry] Initialized', { version: APP_VERSION, env: APP_ENV })
    return true
  } catch (e) {
    console.warn('[Sentry] init failed (non-fatal):', e)
    return false
  }
}

export function captureFontError(
  family: string,
  weight: string,
  src: string,
): void {
  if (!_sentry) return
  _sentry.captureMessage(`Font load failed: ${family}/${weight}`, {
    level: 'warning',
    tags: { fontFamily: family, fontWeight: weight, fontSrc: src },
    fingerprint: ['font', family],
  })
}

export function captureException(
  error: Error,
  context?: Record<string, unknown>,
): void {
  if (!_sentry) return
  _sentry.captureException(error, { extra: context })
}

export function isSentryEnabled(): boolean {
  return _initialized
}

export const sentryConfig = {
  DSN_SET: !!SENTRY_DSN,
  VERSION: APP_VERSION,
  ENV: APP_ENV,
}
