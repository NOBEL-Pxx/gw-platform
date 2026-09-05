#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Log Management (v4.15)
# Usage:
#   bash scripts/log-mgmt.sh compress          # Gzip all current Docker logs
#   bash scripts/log-mgmt.sh push user@host:/path  # Push compressed logs to remote
#   bash scripts/log-mgmt.sh status            # Show log disk usage
#   bash scripts/log-mgmt.sh clean --days 30   # Remove logs older than N days
#   bash scripts/log-mgmt.sh cron              # Run compress + clean (for cron)
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${PROJECT_DIR}/docker-data/logs"
ARCHIVE_DIR="${LOG_DIR}/archive"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Environment ─────────────────────────────────────────────────────────────
DOCKER_COMPOSE_DIR="$PROJECT_DIR"

# Safe .env loader for GW_LOG_REMOTE
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

# ═══════════════════════════════════════════════════════════════════════════
#  COMPRESS — export current Docker logs, gzip, store in archive
# ═══════════════════════════════════════════════════════════════════════════
do_compress() {
  mkdir -p "$ARCHIVE_DIR"
  local archive_name="gw-logs-${TIMESTAMP}.tar.gz"
  local tmp_dir="${LOG_DIR}/tmp_${TIMESTAMP}"
  mkdir -p "$tmp_dir"

  info "Exporting Docker logs for all containers..."
  local containers
  containers=$(docker compose -f "${DOCKER_COMPOSE_DIR}/docker-compose.yml" ps -q 2>/dev/null)

  if [ -z "$containers" ]; then
    warn "No running containers found. Skipping log export."
    rm -rf "$tmp_dir"
    exit 0
  fi

  for cid in $containers; do
    local cname
    cname=$(docker inspect --format '{{.Name}}' "$cid" | sed 's|^/||')
    info "  Exporting: $cname"
    docker logs --timestamps "$cid" > "${tmp_dir}/${cname}.log" 2>&1 || true
  done

  info "Compressing logs → ${archive_name}"
  cd "$tmp_dir" && tar -czf "${ARCHIVE_DIR}/${archive_name}" ./*.log
  cd "$PROJECT_DIR"

  # Clean up
  rm -rf "$tmp_dir"

  local size
  size=$(du -h "${ARCHIVE_DIR}/${archive_name}" | cut -f1)
  ok "Compressed logs saved: ${ARCHIVE_DIR}/${archive_name} (${size})"

  # Rotate: keep max 30 daily archives, delete older
  local archives
  archives=($(ls -1t "${ARCHIVE_DIR}"/gw-logs-*.tar.gz 2>/dev/null))
  if [ ${#archives[@]} -gt 30 ]; then
    warn "Rotating: removing ${#archives[@]} - 30 old archives"
    for ((i=30; i<${#archives[@]}; i++)); do
      rm -f "${archives[$i]}"
    done
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  PUSH — SCP archive to remote server
# ═══════════════════════════════════════════════════════════════════════════
do_push() {
  local remote="${1:-}"
  if [ -z "$remote" ]; then
    err "Usage: $0 push user@host:/path/to/logs/"
    echo ""
    echo "  Set GW_LOG_REMOTE in .env to skip specifying each time:"
    echo "    GW_LOG_REMOTE=user@192.168.1.100:/backup/gw-logs/"
    exit 1
  fi

  # GW_LOG_REMOTE already loaded at top of script, but double-check
  if [ -z "${GW_LOG_REMOTE:-}" ] && [ -f "${PROJECT_DIR}/.env" ]; then
    GW_LOG_REMOTE=$(grep '^GW_LOG_REMOTE=' "${PROJECT_DIR}/.env" | cut -d= -f2- | xargs 2>/dev/null || true)
  fi
  remote="${GW_LOG_REMOTE:-$remote}"

  info "Pushing log archives to ${remote}..."
  if [ ! -d "$ARCHIVE_DIR" ] || [ -z "$(ls -A "$ARCHIVE_DIR" 2>/dev/null)" ]; then
    warn "No archived logs to push. Run 'compress' first."
    exit 1
  fi

  # Push all archives not already on remote
  for f in "${ARCHIVE_DIR}"/gw-logs-*.tar.gz; do
    local fname=$(basename "$f")
    info "  Pushing: $fname"
    scp -o ConnectTimeout=10 "$f" "${remote}/${fname}" 2>/dev/null || {
      warn "SCP push failed for $fname (check connectivity and remote path)"
    }
  done
  ok "Push complete."
}

# ═══════════════════════════════════════════════════════════════════════════
#  STATUS — show log disk usage
# ═══════════════════════════════════════════════════════════════════════════
do_status() {
  echo ""
  echo "GravitationalWave Platform — Log Status"
  echo "═══════════════════════════════════════════════"

  # Docker log sizes (json-file driver)
  echo ""
  echo "Docker container logs (live):"
  docker ps --format '{{.Names}}' 2>/dev/null | while read c; do
    # Docker Desktop Windows: LogPath is inside the VM, not accessible from host
    # Fall back to docker-compose logs size estimate
    local logpath
    logpath=$(docker inspect "$c" --format '{{.LogPath}}' 2>/dev/null)
    if [ -f "$logpath" ]; then
      printf "  %-20s  %s\n" "$c" "$(du -h "$logpath" | cut -f1)"
    else
      # Estimate from docker logs last 100 lines
      local lines
      lines=$(docker logs --tail 100 "$c" 2>/dev/null | wc -l)
      printf "  %-20s  ~%s lines (Docker VM)\n" "$c" "$lines"
    fi
  done

  # Archived logs
  echo ""
  echo "Archived logs:"
  if [ -d "$ARCHIVE_DIR" ] && [ "$(ls -A "$ARCHIVE_DIR" 2>/dev/null)" ]; then
    local count=$(ls -1 "${ARCHIVE_DIR}"/gw-logs-*.tar.gz 2>/dev/null | wc -l)
    local size=$(du -sh "$ARCHIVE_DIR" 2>/dev/null | cut -f1)
    echo "  ${count} archives, total: ${size}"
    echo ""
    ls -1lh "${ARCHIVE_DIR}"/gw-logs-*.tar.gz 2>/dev/null | head -10
  else
    echo "  (no archives yet)"
  fi
  echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
#  CLEAN — remove archives older than N days
# ═══════════════════════════════════════════════════════════════════════════
do_clean() {
  local days="${2:-30}"
  if [ -d "$ARCHIVE_DIR" ]; then
    info "Removing log archives older than ${days} days..."
    find "$ARCHIVE_DIR" -name "gw-logs-*.tar.gz" -mtime "+${days}" -delete -print 2>/dev/null || true
    ok "Cleanup complete."
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  CRON — compress + clean (for scheduled runs)
# ═══════════════════════════════════════════════════════════════════════════
do_cron() {
  info "Scheduled log rotation: $(date)"
  do_compress
  do_clean --days 30
  ok "Cron run complete."
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
mkdir -p "$ARCHIVE_DIR"

case "${1:-}" in
  compress)
    do_compress
    ;;
  push)
    do_push "${2:-}"
    ;;
  status|st)
    do_status
    ;;
  clean)
    do_clean "${@}"
    ;;
  cron)
    do_cron
    ;;
  *)
    echo "Usage: $0 {compress|push|status|clean|cron}"
    echo ""
    echo "  compress          Export + gzip all Docker logs into archive/"
    echo "  push <remote>     SCP log archives to remote server"
    echo "  status            Show log disk usage overview"
    echo "  clean --days N    Remove archived logs older than N days (default 30)"
    echo "  cron              compress + clean — for cron.daily / Task Scheduler"
    echo ""
    echo "Remote push setup — add to .env:"
    echo "  GW_LOG_REMOTE=user@192.168.1.100:/backup/gw-logs/"
    exit 1
    ;;
esac
