#!/usr/bin/env bash
# R6.22 — Remote deploy (runs on target machine after sync)
# Usage: bash remote-deploy.sh <tag>
set -euo pipefail
tag="${1:?tag required}"

echo "═══ Remote deploy for tag: $tag ═══"
cd "/tmp/gw-${tag}" || { echo "tag dir not found"; exit 1; }

# Verify tag is checked out
current_tag=$(git describe --tags --exact-match 2>/dev/null || echo "unknown")
if [ "$current_tag" != "$tag" ]; then
    echo "WARNING: HEAD is not at expected tag ($current_tag vs $tag)"
    exit 1
fi

# Pull latest images / rebuild
docker compose pull || true
docker compose up -d --force-recreate --no-deps

# Health check
sleep 30
docker ps --format "table {{.Names}}\t{{.Status}}"

echo "═══ Remote deploy complete ═══"
