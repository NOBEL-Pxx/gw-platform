#!/bin/bash
# Unified build + tag — GravitationalWave Platform v4.12
# Usage: bash scripts/build.sh [service] [--tag VERSION]
#   bash scripts/build.sh             # build all, tag with timestamp
#   bash scripts/build.sh gw-backend  # build only backend
#   bash scripts/build.sh --tag v4.12 # build all, tag as v4.12
set -e
cd "$(dirname "$0")/.." || exit 1

TAG="${2:-$(date +%Y%m%d-%H%M%S)}"
SERVICE="${1:-all}"
if [ "$1" = "--tag" ]; then TAG="$2"; SERVICE="all"; fi

echo "=== Build: $SERVICE (tag: $TAG) ==="

SERVICES=(gw-backend gw-frontend gw-pipeline gw-mcp-server)
IMAGES=(alicpt-gw-backend alicpt-gw-frontend alicpt-gw-pipeline alicpt-gw-mcp-server)

build_and_tag() {
  local svc=$1 img=$2
  echo "  Building $svc..."
  docker compose build "$svc"
  docker tag "$img:latest" "$img:$TAG"
  echo "  Tagged $img:$TAG"
}

if [ "$SERVICE" = "all" ]; then
  for i in "${!SERVICES[@]}"; do
    build_and_tag "${SERVICES[$i]}" "${IMAGES[$i]}"
  done
else
  idx=-1
  for i in "${!SERVICES[@]}"; do
    [ "${SERVICES[$i]}" = "$SERVICE" ] && idx=$i && break
  done
  if [ $idx -ge 0 ]; then
    build_and_tag "$SERVICE" "${IMAGES[$idx]}"
  else
    echo "Unknown service: $SERVICE (valid: ${SERVICES[*]})"
    exit 1
  fi
fi

echo ""
echo "Build complete. Available tags for rollback:"
for img in "${IMAGES[@]}"; do
  docker images "$img" --format "  {{.Repository}}:{{.Tag}}" 2>/dev/null | head -5
done
