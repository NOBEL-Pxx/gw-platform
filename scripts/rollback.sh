#!/bin/bash
# Image rollback — GravitationalWave Platform v4.12
# Usage: bash scripts/rollback.sh <tag> [service]
#   bash scripts/rollback.sh v4.11          # rollback all to v4.11
#   bash scripts/rollback.sh 20260724-xyz gw-backend  # rollback backend only
set -e
cd "$(dirname "$0")/.." || exit 1

TAG="$1"
SERVICE="${2:-all}"
if [ -z "$TAG" ]; then
  echo "Usage: bash scripts/rollback.sh <tag> [service]"
  echo ""
  echo "Available tags:"
  for img in alicpt-gw-backend alicpt-gw-frontend alicpt-gw-pipeline alicpt-gw-mcp-server; do
    docker images "$img" --format "  {{.Tag}}" 2>/dev/null | grep -v latest | head -5
  done
  exit 1
fi

SERVICES=(gw-backend gw-frontend gw-pipeline gw-mcp-server)
IMAGES=(alicpt-gw-backend alicpt-gw-frontend alicpt-gw-pipeline alicpt-gw-mcp-server)

rollback_one() {
  local svc=$1 img=$2
  if docker image inspect "$img:$TAG" >/dev/null 2>&1; then
    echo "  Rolling back $svc to $img:$TAG..."
    docker tag "$img:$TAG" "$img:latest"
    docker compose up -d --force-recreate "$svc"
  else
    echo "  SKIP $svc: tag $TAG not found"
  fi
}

echo "=== Rollback to: $TAG ==="
if [ "$SERVICE" = "all" ]; then
  for i in "${!SERVICES[@]}"; do
    rollback_one "${SERVICES[$i]}" "${IMAGES[$i]}"
  done
else
  idx=-1
  for i in "${!SERVICES[@]}"; do
    [ "${SERVICES[$i]}" = "$SERVICE" ] && idx=$i && break
  done
  if [ $idx -ge 0 ]; then
    rollback_one "$SERVICE" "${IMAGES[$idx]}"
  else
    echo "Unknown service: $SERVICE"
    exit 1
  fi
fi
echo "Rollback complete."
