#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Service Monitor & Auto-Restart (v4.15)
# Usage:
#   bash scripts/monitor.sh start     # Start monitor daemon (background)
#   bash scripts/monitor.sh stop      # Stop monitor daemon
#   bash scripts/monitor.sh status    # Show current health of all services
#   bash scripts/monitor.sh once      # Single health check (no loop)
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="${PROJECT_DIR}/docker-data/monitor.pid"
LOG_FILE="${PROJECT_DIR}/docker-data/monitor.log"
CHECK_INTERVAL=30        # seconds between health checks
RESTART_MAX=3             # max restarts per hour per container
RESTART_WINDOW=3600       # restart window in seconds (1 hour)
NOTIFY_CMD=""             # set to a command for alerts (e.g., webhook, email)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

notify() {
  if [ -n "$NOTIFY_CMD" ]; then
    eval "$NOTIFY_CMD" 2>/dev/null || true
  fi
}

# ── Declare restart counters ────────────────────────────────────────────────
declare -A RESTART_COUNT RESTART_WINDOW_START

# ═══════════════════════════════════════════════════════════════════════════
#  SINGLE CHECK — returns non-zero if any container is unhealthy
# ═══════════════════════════════════════════════════════════════════════════
check_all() {
  local unhealthy=0
  local containers
  containers=$(docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps -q 2>/dev/null)

  if [ -z "$containers" ]; then
    err "No Docker containers found. Is Docker running?"
    return 1
  fi

  for cid in $containers; do
    local cname
    cname=$(docker inspect --format '{{.Name}}' "$cid" | sed 's|^/||')
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo "gone")
    local health
    health=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "none")

    if [ "$status" != "running" ]; then
      err "  $cname: $status (NOT RUNNING)"
      unhealthy=$((unhealthy + 1))

      # Attempt restart if window allows
      attempt_restart "$cname" "$cid"
    elif [ "$health" = "unhealthy" ]; then
      warn "  $cname: $status (UNHEALTHY)"
      unhealthy=$((unhealthy + 1))
      attempt_restart "$cname" "$cid"
    else
      ok "  $cname: $status ($health)"
    fi
  done
  return $unhealthy
}

# ═══════════════════════════════════════════════════════════════════════════
#  RESTART WITH RATE-LIMITING
# ═══════════════════════════════════════════════════════════════════════════
attempt_restart() {
  local cname="$1"
  local cid="$2"
  local now=$(date +%s)
  local key="${cname}"

  # Reset window if expired
  if [ -z "${RESTART_WINDOW_START[$key]:-}" ] || \
     [ $((now - RESTART_WINDOW_START[$key])) -gt $RESTART_WINDOW ]; then
    RESTART_WINDOW_START[$key]=$now
    RESTART_COUNT[$key]=0
  fi

  if [ "${RESTART_COUNT[$key]:-0}" -ge $RESTART_MAX ]; then
    warn "  $cname: restart limit reached (${RESTART_MAX}/${RESTART_WINDOW}s). Skipping."
    log "RATE-LIMITED: $cname reached restart limit ${RESTART_MAX}/${RESTART_WINDOW}s"
    notify
    return
  fi

  warn "  Restarting $cname..."
  docker compose -f "${PROJECT_DIR}/docker-compose.yml" restart "$cname" 2>/dev/null || {
    err "  Failed to restart $cname"
    return
  }
  RESTART_COUNT[$key]=$((RESTART_COUNT[$key] + 1))
  log "RESTART: $cname (attempt ${RESTART_COUNT[$key]}/${RESTART_MAX} in window)"
}

# ═══════════════════════════════════════════════════════════════════════════
#  DAEMON LOOP
# ═══════════════════════════════════════════════════════════════════════════
run_daemon() {
  while true; do
    log "── Health check ──"
    check_all || true
    sleep "$CHECK_INTERVAL"
  done
}

# ═══════════════════════════════════════════════════════════════════════════
#  START / STOP / STATUS
# ═══════════════════════════════════════════════════════════════════════════
do_start() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    warn "Monitor is already running (PID $(cat "$PID_FILE"))."
    exit 0
  fi
  mkdir -p "$(dirname "$PID_FILE")"
  info "Starting service monitor daemon..."
  info "  Check interval: ${CHECK_INTERVAL}s  |  Restart limit: ${RESTART_MAX}/${RESTART_WINDOW}s"
  info "  Log: $LOG_FILE"
  # Run in background
  nohup bash "$0" _daemon_loop >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  ok "Monitor started (PID $!)."
}

do_stop() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      rm -f "$PID_FILE"
      ok "Monitor stopped (was PID $pid)."
    else
      warn "PID file exists but process $pid is dead. Cleaning up."
      rm -f "$PID_FILE"
    fi
  else
    info "Monitor is not running."
  fi
}

do_status_cmd() {
  echo ""
  echo "GravitationalWave Platform — Service Status"
  echo "═══════════════════════════════════════════════"
  echo ""
  check_all || true
  echo ""

  # Monitor daemon status
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    local pid=$(cat "$PID_FILE")
    local uptime
    uptime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs || echo "?")
    echo "Monitor daemon: RUNNING (PID $pid, uptime $uptime)"
  else
    echo "Monitor daemon: NOT RUNNING"
  fi

  # Restart counts this window
  echo ""
  echo "Restart stats (current window):"
  for c in "${!RESTART_COUNT[@]}"; do
    [ "${RESTART_COUNT[$c]}" -gt 0 ] && echo "  $c: ${RESTART_COUNT[$c]} restart(s)"
  done
  echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
# Safe .env loader — handles special chars (&, %, !) in values
if [ -f "${PROJECT_DIR}/.env" ]; then
  while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)  # trim whitespace
    # Skip comments and empty lines
    [ -z "$key" ] && continue
    [ "${key:0:1}" = "#" ] && continue
    # Only export specific vars we need — skip passwords with shell metacharacters
    case "$key" in
      NOTIFY_CMD|CHECK_INTERVAL|RESTART_MAX|RESTART_WINDOW)
        export "$key"="$value" 2>/dev/null || true ;;
    esac
  done < "${PROJECT_DIR}/.env"
fi

case "${1:-}" in
  start)
    do_start
    ;;
  stop)
    do_stop
    ;;
  status|st)
    do_status_cmd
    ;;
  once)
    check_all
    ;;
  _daemon_loop)
    run_daemon
    ;;
  *)
    echo "Usage: $0 {start|stop|status|once}"
    echo ""
    echo "  start    Start monitor as background daemon"
    echo "  stop     Stop the running daemon"
    echo "  status   Show health of all services + daemon status"
    echo "  once     Single health check (for cron / Task Scheduler)"
    echo ""
    echo "Configuration (in .env):"
    echo "  CHECK_INTERVAL=30          Seconds between checks"
    echo "  RESTART_MAX=3              Max restarts per window"
    echo "  RESTART_WINDOW=3600        Restart-rate window in seconds"
    echo "  NOTIFY_CMD='curl -X POST https://your-webhook/alert'"
    exit 1
    ;;
esac
