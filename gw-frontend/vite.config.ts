import { defineConfig, loadEnv } from 'vite'
import { execSync } from 'child_process'
import { readFileSync } from 'fs'
import react from '@vitejs/plugin-react'
import path from 'path'
import mockPlugin from './vite-plugin-mock-simple'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendBaseUrl = env.VITE_BACKEND_BASE_URL || 'http://localhost:8093'

  // R6.47: Resolve APP_VERSION at build time.
  // Priority: VITE_APP_VERSION env (set by CI from ${{ github.ref_name }})
  //          -> 'v' + package.json version + '+R' + tag suffix (from git describe)
  //          -> 'v0.0.0+dev' (fallback when no git tags yet)
  let appVersion = env.VITE_APP_VERSION
  if (!appVersion) {
    try {
      const pkg = JSON.parse(readFileSync('package.json', 'utf8'))
      const describe = execSync(
        'git describe --tags --long --dirty 2>/dev/null',
        { encoding: 'utf8' },
      ).trim()
      const m = describe.match(/^v?([0-9.]+)-(\d+)-g([0-9a-f]+)/)
      appVersion = m
        ? `v${m[1]}+R${m[2]}-g${m[3].slice(0, 7)}`
        : `v${pkg.version}+dev`
    } catch (_e) {
      appVersion = 'v0.0.0+dev'
    }
  }
  return {
    define: {
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    },
    plugins: [react(), mockPlugin()],
    build: {
      outDir: 'build',
      // R6.48: generate sourcemaps for Sentry upload (R6.48 release tracking).
      // hidden: true means .map files emitted but not referenced in JS (saves bandwidth).
      // uploaded via gw-frontend/scripts/upload-sentry-sourcemaps.sh in deploy.yml.
      sourcemap: process.env.SENTRY_AUTH_TOKEN ? 'hidden' : false,
      rollupOptions: {
        output: {
          // R6.27.c: REVERT to R6.22-R6.26 single-vendor strategy. The 2-way
          // split (vendor-react + vendor-antd) STILL has circular deps:
          //
          //   vendor-react first stmt: import { g as pc } from "./vendor-antd"
          //   vendor-antd  first stmt: import { R, a, r, b, c, d } from "./vendor-react"
          //
          // When vendor-antd top-level code runs `i.createContext(null)`
          // (i = vendor-react's `var P = vc.exports`), P is still undefined
          // because vendor-react hasn't executed yet (it's waiting for
          // vendor-antd). Error: "Cannot read properties of undefined".
          //
          // FIX: merge ALL node_modules into ONE chunk. R6.22-R6.26 worked
          // fine with a 1.5 MB vendor chunk. Tradeoff: no chunk-level cache,
          // but the app loads instantly on first visit anyway. Module-level
          // code-splitting for user code stays enabled.
          manualChunks: (id) => {
            if (!id.includes('node_modules/')) return undefined
            return 'vendor'
          },
        },
      },
      chunkSizeWarningLimit: 2000, // R6.27.c: single vendor chunk ~1.3 MB
    },
    // Pre-bundle Ant Design for tree-shaking: Vite + esbuild will eliminate
    // unused components when using named imports (the codebase already does this).
    // This also speeds up cold-start dev server by pre-bundling these libraries.
    optimizeDeps: {
      include: ['antd', '@ant-design/icons', '@ant-design/cssinjs'],
    },
    server: {
      port: 6001,
      proxy: {
        '/api': {
          target: `${backendBaseUrl}/`,
          changeOrigin: true,
        },
        '/static-files': {
          target: `${backendBaseUrl}/`,
          changeOrigin: true,
        },
        '/pipeline': {
          target: 'http://localhost:8200/',
          changeOrigin: true,
        },
        '/firefly': {
          target: 'http://localhost:8080/',
          changeOrigin: true,
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
        '@common': path.resolve(__dirname, 'src/pages/common'),
      },
    },
  }
})
