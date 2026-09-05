#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Tunnel (v4.16 final)
# Provider: localhost.run via SSH key auth (plan@)
#
# Usage:
#   bash scripts/tunnel.sh              # Start tunnel
#   bash scripts/tunnel.sh status       # Show status
#   bash scripts/tunnel.sh stop         # Stop tunnel
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
URL_FILE="${PROJECT_DIR}/docker-data/public-url.txt"
PID_DIR="${PROJECT_DIR}/docker-data/tunnels"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

mkdir -p "$PID_DIR"

do_start() {
  local pidfile="${PID_DIR}/lhr.pid"
  local outfile="${PID_DIR}/lhr-output.txt"

  info "Starting tunnel (plan@localhost.run)..."
  ssh -o StrictHostKeyChecking=no \
      -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -o ExitOnForwardFailure=yes \
      -R 80:localhost:6001 \
      plan@localhost.run \
      > "$outfile" 2>&1 &
  local pid=$!
  echo $pid > "$pidfile"

  # Extract URL
  for i in $(seq 1 20); do
    sleep 1.5
    local url
    url=$(grep -oP 'https://[a-z0-9]+\.lhr\.life' "$outfile" 2>/dev/null | head -1 || true)
    if [ -n "$url" ]; then
      echo "$url" > "$URL_FILE"
      ok "Tunnel active: ${url}"
      return 0
    fi
    if ! kill -0 $pid 2>/dev/null; then
      warn "SSH connection died."
      return 1
    fi
  done
  warn "Timed out waiting for URL."
  kill $pid 2>/dev/null || true
  return 1
}

do_stop() {
  info "Stopping tunnel..."
  for pf in "${PID_DIR}"/*.pid; do
    [ -f "$pf" ] || continue
    local pid=$(cat "$pf")
    kill $pid 2>/dev/null && warn "Killed PID $pid ($(basename "$pf"))" || true
    rm -f "$pf"
  done
  ok "Tunnel stopped."
}

do_status() {
  echo ""
  echo "Tunnel Status:"
  echo "──────────────"
  local found=false
  for pf in "${PID_DIR}"/*.pid; do
    [ -f "$pf" ] || continue
    found=true
    local name=$(basename "$pf" .pid)
    local pid=$(cat "$pf")
    if kill -0 $pid 2>/dev/null; then
      echo "  ${name}: RUNNING (PID $pid)"
    else
      echo "  ${name}: DEAD"
    fi
  done
  [ "$found" = false ] && echo "  (not running)"
  echo ""
  if [ -f "$URL_FILE" ]; then
    echo "  URL: $(cat "$URL_FILE")"
  fi
  echo ""
}

case "${1:-start}" in
  start)  do_start ;;
  stop)   do_stop ;;
  status) do_status ;;
  *)      echo "Usage: $0 {start|stop|status}" ;;
esac
