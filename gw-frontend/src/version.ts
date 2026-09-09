// R6.71: Single source of truth for APP_VERSION + APP_ENV.
//
// Resolution chain (highest priority first):
//   1. import.meta.env.VITE_APP_VERSION - set by:
//      a. CI: deploy.yml passes ${{ github.ref_name }} -> vite build
//      b. Build: vite.config.ts resolves via `git describe --tags --long --dirty`
//         -> JSON.stringify(appVersion) -> `define:` injection
//      c. Dev:  vite.config.ts resolves same way (if git tags exist) OR
//         falls back to `v${pkg.version}+dev`
//   2. Hardcoded fallback `'v4.63+R6.86'` - only used in dev when git tags
//      don't exist AND pkg.version is missing AND no env var.
//
// Why a shared module instead of inline `import.meta.env` in sentry.ts:
//   - Before R6.71: useFontMonitor.ts had `const APP_VERSION = 'v4.63+R6.86'`
//     (pure hardcoded, no env lookup). One forgotten bump -> Sentry reports
//     wrong release tag forever.
//   - After R6.71: both sentry.ts and useFontMonitor.ts import from here.
//     Build pipeline upgrades trickle to both. Dev fallback also lives in
//     ONE place, not two.

export const APP_VERSION: string =
  import.meta.env.VITE_APP_VERSION || 'v4.63+R6.86'

export const APP_ENV: string = import.meta.env.MODE || 'production'

// R6.71 diagnostics: log the resolved version at module load (dev only).
// In prod, vite tree-shakes the import.meta.env.DEV check.
if (import.meta.env.DEV) {
  console.info('[version] APP_VERSION =', APP_VERSION, 'APP_ENV =', APP_ENV)
}
