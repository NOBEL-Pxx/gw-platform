#!/bin/bash
# R6.48: Upload Vite production sourcemaps to Sentry.
# Triggered by deploy.yml after `npm run build`.
# Skips if SENTRY_AUTH_TOKEN is unset (R6.45 lazy-init pattern).

set -e

# Required env vars (all gated by secrets in deploy.yml):
#   SENTRY_AUTH_TOKEN       — Sentry user auth token with project:releases scope
#   SENTRY_ORG              — Sentry org slug
#   SENTRY_PROJECT          — Sentry project slug
#   SENTRY_URL              — defaults to https://sentry.io
#   VITE_APP_VERSION        — release name (set by deploy.yml from ${{ github.ref_name }})

if [ -z "$SENTRY_AUTH_TOKEN" ]; then
  echo "[sentry-sourcemaps] SENTRY_AUTH_TOKEN unset, skipping upload (no-op)"
  exit 0
fi

if [ -z "$VITE_APP_VERSION" ]; then
  echo "[sentry-sourcemaps] VITE_APP_VERSION unset, cannot tag release"
  exit 1
fi

# R6.49: Sentry deploy environment. Defaults to production.
# deploy.yml sets this based on git ref: tags -> production, branches -> staging.
SENTRY_ENV="${SENTRY_ENV:-production}"
echo "[sentry-sourcemaps] Deploy environment: $SENTRY_ENV"

if ! command -v sentry-cli >/dev/null 2>&1; then
  echo "[sentry-sourcemaps] sentry-cli not installed, attempting npm install..."
  npm install -g @sentry/cli 2>&1 | tail -3 || {
    echo "[sentry-sourcemaps] npm install sentry-cli failed, skipping upload"
    exit 0
  }
fi

BUILD_DIR="gw-frontend/build"
if [ ! -d "$BUILD_DIR" ]; then
  echo "[sentry-sourcemaps] $BUILD_DIR not found, skipping upload"
  exit 0
fi

# Count .map files (Vite produces them only when build.sourcemap=true)
MAP_COUNT=$(find "$BUILD_DIR" -name "*.map" 2>/dev/null | wc -l | tr -d ' ')
echo "[sentry-sourcemaps] Found $MAP_COUNT .map files in $BUILD_DIR"

if [ "$MAP_COUNT" = "0" ]; then
  echo "[sentry-sourcemaps] No sourcemaps found. Enable build.sourcemap=true in vite.config.ts to generate."
  exit 0
fi

export SENTRY_URL="${SENTRY_URL:-https://sentry.io}"

echo "[sentry-sourcemaps] Creating release $VITE_APP_VERSION ..."
sentry-cli releases new "$VITE_APP_VERSION" \
  --org "$SENTRY_ORG" \
  --project "$SENTRY_PROJECT" \
  --auth-token "$SENTRY_AUTH_TOKEN" \
  --env "$SENTRY_ENV" \
  2>&1 | head -5 || echo "release may already exist, continuing"

echo "[sentry-sourcemaps] Uploading sourcemaps ..."
# --rewrite normalizes asset paths in the sourcemap
# --url-prefix matches Vite's base path
sentry-cli releases files "$VITE_APP_VERSION" upload-sourcemaps \
  "$BUILD_DIR" \
  --org "$SENTRY_ORG" \
  --project "$SENTRY_PROJECT" \
  --auth-token "$SENTRY_AUTH_TOKEN" \
  --url-prefix "~/static" \
  --rewrite \
  2>&1 | tail -10

# R6.49: Mark deploy in Sentry so env is visible in release dashboard
echo "[sentry-sourcemaps] Marking deploy env=$SENTRY_ENV ..."
DEPLOY_NAME="${GITHUB_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"
sentry-cli releases deploys "$VITE_APP_VERSION" new \
  --org "$SENTRY_ORG" \
  --project "$SENTRY_PROJECT" \
  --auth-token "$SENTRY_AUTH_TOKEN" \
  --env "$SENTRY_ENV" \
  --name "$DEPLOY_NAME" \
  2>&1 | head -3 || echo "deploy mark may have failed (non-fatal)"

echo "[sentry-sourcemaps] Finalizing release ..."
sentry-cli releases finalize "$VITE_APP_VERSION" \
  --org "$SENTRY_ORG" \
  --project "$SENTRY_PROJECT" \
  --auth-token "$SENTRY_AUTH_TOKEN" \
  2>&1 | head -3

echo "[sentry-sourcemaps] Done. Release $VITE_APP_VERSION deployed to Sentry."
