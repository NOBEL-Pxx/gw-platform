#!/bin/bash
#==============================================================================
# Log Shipper — GravitationalWave Platform v4.37
# Ships Docker container logs to MongoDB audit collection for unified search.
#
# Usage:
#   bash scripts/log-shipper.sh             # Ship all logs once
#   bash scripts/log-shipper.sh --daemon    # Run continuously (ship every 60s)
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SHIP_INTERVAL="${LOG_SHIP_INTERVAL:-60}"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

# Containers whose logs to ship
CONTAINERS=("gw-pipeline" "gw-mcp-server" "gw-backend")

ship_once() {
  local timestamp
  timestamp=$(date -Iseconds)

  for container in "${CONTAINERS[@]}"; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
      echo "  SKIP: $container (not running)"
      continue
    fi

    # Get logs since last ship
    local last_ship_file="${PROJECT_DIR}/docker-data/.last_ship_${container}"
    local since_arg=""
    if [ -f "$last_ship_file" ]; then
      local last_ts
      last_ts=$(cat "$last_ship_file")
      since_arg="--since $last_ts"
    fi

    local log_count
    log_count=$(docker logs "$since_arg" --tail 500 "$container" 2>&1 | wc -l)

    if [ "$log_count" -gt 0 ]; then
      # Try to ship via pipeline audit endpoint
      docker logs "$since_arg" --tail 500 "$container" 2>&1 | while IFS= read -r line; do
        # Only ship lines that look like audit events (contain user/session/action patterns)
        if echo "$line" | grep -qiE "audit|compliance|token|auth|login|error|warn"; then
          curl -s -X POST "http://localhost:8200/pipeline/admin/audit/ship" \
            -H "Content-Type: application/json" \
            -d "{\"source\":\"${container}\",\"timestamp\":\"${timestamp}\",\"message\":$(echo "$line" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || echo '""')}" \
            -o /dev/null 2>/dev/null || true
        fi
      done
      echo "  $container: shipped $log_count lines"
    fi

    # Update last ship timestamp
    date -Iseconds > "$last_ship_file"
  done
}

run_daemon() {
  echo -e "${CYAN}Log Shipper daemon started (interval=${SHIP_INTERVAL}s)${NC}"
  while true; do
    echo "[$(date '+%H:%M:%S')] Shipping logs..."
    ship_once
    sleep "$SHIP_INTERVAL"
  done
}

case "${1:-}" in
  --daemon|-d)
    run_daemon
    ;;
  *)
    ship_once
    echo -e "${GREEN}[OK] Log shipping complete${NC}"
    ;;
esac
