#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Cross-Platform Launcher (v4.15)
# Supports: Linux, macOS, Windows (Git Bash / WSL2)
#
# Features:
#   - Starts all 7 Docker containers
#   - SSH tunnel with auto-reconnect (localhost.run)
#   - Optional service monitor
#   - Health check with progress display
#
# Usage:
#   bash start-gw.sh            # Start all, with tunnel
#   bash start-gw.sh --no-tunnel # Start without public tunnel
#   bash start-gw.sh --monitor   # Start with background health monitor
#   bash start-gw.sh --stop      # Stop everything
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
URL_FILE="${PROJECT_DIR}/docker-data/public-url.txt"
PID_FILE_TUNNEL="${PROJECT_DIR}/docker-data/tunnel.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Safe .env loader (only for optional config, not passwords) ───────────────
if [ -f "${PROJECT_DIR}/.env" ]; then
  while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    [ -z "$key" ] && continue
    [ "${key:0:1}" = "#" ] && continue
    case "$key" in
      GW_LOG_REMOTE) export "$key"="$value" 2>/dev/null || true ;;
    esac
  done < "${PROJECT_DIR}/.env"
fi

banner() {
  echo ""
  echo -e "${MAGENTA}========================================${NC}"
  echo -e "${MAGENTA}  GravitationalWave Platform Launcher${NC}"
  echo -e "${MAGENTA}  v4.15 — Cross-Platform${NC}"
  echo -e "${MAGENTA}========================================${NC}"
  echo ""
}

# ── Parse flags ─────────────────────────────────────────────────────────────
USE_TUNNEL=true
USE_MONITOR=false
DO_STOP=false
while [ $# -gt 0 ]; do
  case "$1" in
    --no-tunnel) USE_TUNNEL=false; shift ;;
    --monitor)   USE_MONITOR=true; shift ;;
    --stop)      DO_STOP=true; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# ═══════════════════════════════════════════════════════════════════════════
#  STOP
# ═══════════════════════════════════════════════════════════════════════════
do_stop() {
  banner
  info "Stopping GravitationalWave Platform..."
  # Stop monitor if running
  if [ -f "${PROJECT_DIR}/docker-data/monitor.pid" ]; then
    bash "${PROJECT_DIR}/scripts/monitor.sh" stop 2>/dev/null || true
  fi
  # Kill tunnel
  if [ -f "$PID_FILE_TUNNEL" ]; then
    kill "$(cat "$PID_FILE_TUNNEL")" 2>/dev/null || true
    rm -f "$PID_FILE_TUNNEL"
  fi
  # Stop Docker containers
  docker compose -f "${PROJECT_DIR}/docker-compose.yml" down 2>/dev/null || true
  ok "All services stopped."
  exit 0
}

[ "$DO_STOP" = true ] && do_stop

# ═══════════════════════════════════════════════════════════════════════════
#  HEALTH WAIT — poll until all 7 containers healthy or timeout
# ═══════════════════════════════════════════════════════════════════════════
wait_for_healthy() {
  local max_wait=180  # seconds
  local waited=0
  info "Waiting for all 7 services to become healthy... (timeout ${max_wait}s)"
  while [ $waited -lt $max_wait ]; do
    local healthy
    healthy=$(docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps 2>/dev/null | grep -c "healthy" || echo 0)
    echo -ne "  ${healthy}/7 healthy (${waited}s elapsed)...\r"
    if [ "$healthy" -ge 7 ]; then
      echo ""
      ok "All 7 services healthy! (took ${waited}s)"
      return 0
    fi
    sleep 5
    waited=$((waited + 5))
  done
  warn "Timeout waiting for services. Check: docker compose ps"
  return 1
}

# ═══════════════════════════════════════════════════════════════════════════
#  TUNNEL LOOP — SSH tunnel with auto-reconnect
# ═══════════════════════════════════════════════════════════════════════════
start_tunnel() {
  local max_retries=10
  local retry=0
  local backoff=5

  while [ $retry -lt $max_retries ]; do
    info "Starting SSH tunnel (attempt $((retry + 1))/${max_retries})..."
    # Run SSH in background, capture output
    ssh -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -R 80:localhost:6001 \
        nokey@localhost.run \
        > "${PROJECT_DIR}/docker-data/tunnel-output.txt" 2>&1 &
    local ssh_pid=$!
    echo $ssh_pid > "$PID_FILE_TUNNEL"

    # Wait for URL to appear in output
    local wait_count=0
    while [ $wait_count -lt 30 ]; do
      if grep -q "https://.*\.lhr\.life" "${PROJECT_DIR}/docker-data/tunnel-output.txt" 2>/dev/null; then
        local url
        url=$(grep -o 'https://[a-z0-9]\{8,\}\.lhr\.life' "${PROJECT_DIR}/docker-data/tunnel-output.txt" | head -1)
        if [ -n "$url" ]; then
          echo "$url" > "$URL_FILE"
          ok "Tunnel active! Public URL: ${GREEN}${url}${NC}"
          ok "URL saved to: ${URL_FILE}"

          # Background reconnection watcher
          (
            while true; do
              sleep 30
              if ! kill -0 $ssh_pid 2>/dev/null; then
                echo "[$(date)] Tunnel died! Restarting..." >> "${PROJECT_DIR}/docker-data/tunnel-watchdog.log"
                # Signal main process to restart tunnel
                kill -USR1 $$ 2>/dev/null || break
                break
              fi
            done
          ) &
          echo $! > "${PROJECT_DIR}/docker-data/tunnel-watchdog.pid"
          return 0
        fi
      fi
      # Check if SSH is still running
      if ! kill -0 $ssh_pid 2>/dev/null; then
        warn "SSH process died. Retrying..."
        break
      fi
      sleep 1
      wait_count=$((wait_count + 1))
    done

    # If we get here, URL wasn't found. Kill SSH and retry.
    kill $ssh_pid 2>/dev/null || true
    retry=$((retry + 1))
    if [ $retry -lt $max_retries ]; then
      warn "Could not get tunnel URL. Retrying in ${backoff}s..."
      sleep $backoff
      backoff=$((backoff + 5))  # exponential-ish backoff
    fi
  done

  err "Failed to establish tunnel after ${max_retries} attempts."
  warn "Local access: https://localhost:6002"
  return 1
}

# ═══════════════════════════════════════════════════════════════════════════
#  TUNNEL MONITOR — auto-reconnect watchdog
# ═══════════════════════════════════════════════════════════════════════════
tunnel_watchdog() {
  # Trap USR1 signal to trigger reconnect
  trap 'start_tunnel' USR1
  # Initial start
  start_tunnel

  # Keep script alive; watchdog background job sends USR1 on disconnect
  while true; do
    sleep 60
    # If tunnel PID is dead but we wanted a tunnel, restart
    if [ -f "$PID_FILE_TUNNEL" ]; then
      local pid=$(cat "$PID_FILE_TUNNEL")
      if ! kill -0 $pid 2>/dev/null; then
        warn "Tunnel process lost. Reconnecting..."
        start_tunnel
      fi
    fi
  done
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
banner

# Step 1: Start Docker
info "[1/4] Starting Docker containers..."
cd "$PROJECT_DIR"
docker compose up -d 2>&1 | tail -5
ok "Docker containers starting..."

# Step 2: Wait for healthy
info "[2/4] Waiting for services..."
if ! wait_for_healthy; then
  err "Some services failed to become healthy."
  docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps
  exit 1
fi

# Step 3: Start monitor (optional)
if [ "$USE_MONITOR" = true ]; then
  info "[3/4] Starting service monitor daemon..."
  if [ -f "${PROJECT_DIR}/scripts/monitor.sh" ]; then
    bash "${PROJECT_DIR}/scripts/monitor.sh" start
  else
    warn "monitor.sh not found; skipping."
  fi
else
  info "[3/4] Service monitor skipped (use --monitor to enable auto-restart)."
fi

# Step 4: Tunnel (optional)
if [ "$USE_TUNNEL" = true ]; then
  info "[4/4] Starting public tunnel with auto-reconnect..."
  tunnel_watchdog &
  # Give it a moment
  sleep 2
else
  info "[4/4] Public tunnel skipped (use --no-tunnel to disable)."
fi

# ── Final summary ───────────────────────────────────────────────────────────
echo ""
echo -e "${MAGENTA}========================================${NC}"
echo -e "${GREEN}  Platform is running!${NC}"
echo ""
echo -e "  LOCAL:   ${CYAN}https://localhost:6002${NC}"
if [ -f "$URL_FILE" ]; then
  echo -e "  PUBLIC:  ${GREEN}$(cat "$URL_FILE")${NC}"
fi
echo ""
echo "  Commands:"
echo "    bash start-gw.sh --stop       Stop everything"
echo "    bash scripts/monitor.sh status   Health check"
echo "    bash scripts/backup-db.sh backup  Backup databases"
echo "    bash scripts/log-mgmt.sh status   Log status"
echo -e "${MAGENTA}========================================${NC}"
echo ""

# Keep alive if tunnel is running
if [ "$USE_TUNNEL" = true ]; then
  echo -e "${YELLOW}Press Ctrl+C to stop (tunnel + monitor will be killed).${NC}"
  # Wait for any child process
  wait
fi
