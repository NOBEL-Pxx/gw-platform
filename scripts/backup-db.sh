#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Database Backup & Restore (v4.15)
# Usage:
#   bash scripts/backup-db.sh backup              # Full backup (MongoDB + ES)
#   bash scripts/backup-db.sh backup --name v4.14 # Named snapshot for rollback
#   bash scripts/backup-db.sh restore <dir>       # Restore from backup directory
#   bash scripts/backup-db.sh list                # List all backups
#   bash scripts/backup-db.sh clean --keep 5      # Keep only last 5 backups
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_ROOT="${PROJECT_DIR}/docker-data/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ── Colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Safe .env loader (handles special chars in passwords) ───────────────────
load_env() {
  if [ -f "${PROJECT_DIR}/.env" ]; then
    while IFS='=' read -r key value; do
      key=$(echo "$key" | xargs)
      [ -z "$key" ] && continue
      [ "${key:0:1}" = "#" ] && continue
      case "$key" in
        MONGO_ROOT_PASSWORD|MONGO_APP_PASSWORD|ES_PASSWORD|DEEPSEEK_API_KEY)
          export "$key"="$value" 2>/dev/null || true ;;
      esac
    done < "${PROJECT_DIR}/.env"
  fi
}
load_env

# ── Ensure containers are running ───────────────────────────────────────────
ensure_running() {
  local c="$1"
  if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
    err "Container $c is not running. Start it first: cd $PROJECT_DIR && docker compose up -d"
    exit 1
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  BACKUP
# ═══════════════════════════════════════════════════════════════════════════
do_backup() {
  local name="${1:-$TIMESTAMP}"
  local dir="${BACKUP_ROOT}/${name}"
  mkdir -p "$dir"

  info "Starting full database backup → ${dir}"
  info "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"

  # ── MongoDB via mongodump ────────────────────────────────────────────────
  ensure_running "gw-mongodb"
  info "Backing up MongoDB..."
  docker exec gw-mongodb mongodump \
    --host localhost \
    --port 27017 \
    --username admin \
    --password "${MONGO_ROOT_PASSWORD:-}" \
    --authenticationDatabase admin \
    --db gravitationalwave \
    --gzip \
    --archive=/tmp/mongo_backup.archive 2>/dev/null || {
      warn "MongoDB dump failed (may be empty or auth issue), continuing..."
    }
  docker cp gw-mongodb:/tmp/mongo_backup.archive "${dir}/mongo_backup.archive" 2>/dev/null || true
  docker exec gw-mongodb rm -f /tmp/mongo_backup.archive 2>/dev/null || true
  ok "MongoDB backed up: ${dir}/mongo_backup.archive ($(du -h "${dir}/mongo_backup.archive" 2>/dev/null | cut -f1 || echo '?') )"

  # ── Elasticsearch via snapshot API ────────────────────────────────────────
  ensure_running "gw-elasticsearch"
  info "Backing up Elasticsearch..."
  local es_url="http://elastic:${ES_PASSWORD:-}@localhost:9200"

  # Register snapshot repository (idempotent, filesystem location)
  docker exec gw-elasticsearch curl -sf -X PUT "${es_url}/_snapshot/gw_backup" \
    -H 'Content-Type: application/json' \
    -d '{"type":"fs","settings":{"location":"/usr/share/elasticsearch/data/backup","compress":true}}' >/dev/null 2>&1 || true

  local snap_name="snapshot_${TIMESTAMP}"
  docker exec gw-elasticsearch curl -sf -X PUT "${es_url}/_snapshot/gw_backup/${snap_name}?wait_for_completion=true" >/dev/null 2>&1 || {
    warn "ES snapshot failed (may be empty), continuing..."
  }

  # Copy snapshot files out of container
  mkdir -p "${dir}/es_snapshot"
  docker cp gw-elasticsearch:/usr/share/elasticsearch/data/backup/. "${dir}/es_snapshot/" 2>/dev/null || true
  ok "Elasticsearch backed up: ${dir}/es_snapshot/ ($(du -sh "${dir}/es_snapshot" 2>/dev/null | cut -f1 || echo '?') )"

  # ── Metadata ──────────────────────────────────────────────────────────────
  {
    echo "backup_name: $name"
    echo "timestamp: $(date -Iseconds)"
    echo "docker_images:"
    docker compose -f "${PROJECT_DIR}/docker-compose.yml" images 2>/dev/null | tail -n +2 || true
    echo "git_commit: $(cd "$PROJECT_DIR" && git rev-parse HEAD 2>/dev/null || echo 'not-a-git-repo')"
  } > "${dir}/backup_meta.yaml"

  # ── Disk usage ────────────────────────────────────────────────────────────
  local total_size
  total_size=$(du -sh "$dir" 2>/dev/null | cut -f1)
  ok "Backup complete: ${dir}  (${total_size})"
}

# ═══════════════════════════════════════════════════════════════════════════
#  RESTORE
# ═══════════════════════════════════════════════════════════════════════════
do_restore() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    err "Backup directory not found: $dir"
    echo "Available backups:"; do_list
    exit 1
  fi

  warn "⚠  RESTORE WILL OVERWRITE CURRENT DATABASE DATA."
  warn "   Backup dir: $dir"
  read -r -p "   Type 'YES' to confirm: " confirm
  [ "$confirm" != "YES" ] && { info "Aborted."; exit 0; }

  info "Stopping dependent services..."
  docker compose -f "${PROJECT_DIR}/docker-compose.yml" stop gw-backend gw-pipeline gw-mcp-server 2>/dev/null || true

  # ── MongoDB restore ───────────────────────────────────────────────────────
  if [ -f "${dir}/mongo_backup.archive" ]; then
    ensure_running "gw-mongodb"
    info "Restoring MongoDB..."
    docker cp "${dir}/mongo_backup.archive" gw-mongodb:/tmp/mongo_restore.archive
    docker exec gw-mongodb mongorestore \
      --host localhost --port 27017 \
      --username admin --password "${MONGO_ROOT_PASSWORD:-}" \
      --authenticationDatabase admin \
      --gzip --drop \
      --archive=/tmp/mongo_restore.archive 2>/dev/null || warn "MongoDB restore incomplete"
    docker exec gw-mongodb rm -f /tmp/mongo_restore.archive 2>/dev/null || true
    ok "MongoDB restored"
  else
    warn "No MongoDB backup file found in $dir"
  fi

  # ── Elasticsearch restore ──────────────────────────────────────────────────
  if [ -d "${dir}/es_snapshot" ] && [ "$(ls -A "${dir}/es_snapshot" 2>/dev/null)" ]; then
    ensure_running "gw-elasticsearch"
    info "Restoring Elasticsearch..."
    docker exec gw-elasticsearch curl -sf -X DELETE \
      "http://elastic:${ES_PASSWORD:-}@localhost:9200/_all" >/dev/null 2>&1 || true
    # Copy snapshot files back
    docker exec gw-elasticsearch mkdir -p /usr/share/elasticsearch/data/backup
    for f in "${dir}/es_snapshot/"*; do
      docker cp "$f" gw-elasticsearch:/usr/share/elasticsearch/data/backup/ 2>/dev/null || true
    done
    docker exec gw-elasticsearch chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/data/backup/ 2>/dev/null || true
    # Re-register and restore
    docker exec gw-elasticsearch curl -sf -X PUT \
      "http://elastic:${ES_PASSWORD:-}@localhost:9200/_snapshot/gw_backup" \
      -H 'Content-Type: application/json' \
      -d '{"type":"fs","settings":{"location":"/usr/share/elasticsearch/data/backup"}}' >/dev/null 2>&1 || true

    local snap_name
    snap_name=$(docker exec gw-elasticsearch curl -sf \
      "http://elastic:${ES_PASSWORD:-}@localhost:9200/_snapshot/gw_backup/_all" 2>/dev/null | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print(d['snapshots'][0]['snapshot'])" 2>/dev/null || echo "")

    if [ -n "$snap_name" ]; then
      docker exec gw-elasticsearch curl -sf -X POST \
        "http://elastic:${ES_PASSWORD:-}@localhost:9200/_snapshot/gw_backup/${snap_name}/_restore?wait_for_completion=true" >/dev/null 2>&1 || warn "ES restore incomplete"
      ok "Elasticsearch restored"
    else
      warn "No ES snapshot name found"
    fi
  else
    warn "No ES snapshot directory in $dir"
  fi

  info "Restarting dependent services..."
  docker compose -f "${PROJECT_DIR}/docker-compose.yml" up -d gw-backend gw-pipeline gw-mcp-server 2>/dev/null || true
  ok "Restore complete. Verify at https://localhost:6002"
}

# ═══════════════════════════════════════════════════════════════════════════
#  LIST
# ═══════════════════════════════════════════════════════════════════════════
do_list() {
  echo ""
  echo "Available backups at ${BACKUP_ROOT}:"
  echo "────────────────────────────────────────────────────────────"
  if [ -d "$BACKUP_ROOT" ] && [ "$(ls -A "$BACKUP_ROOT" 2>/dev/null)" ]; then
    for d in "$BACKUP_ROOT"/*/; do
      local name=$(basename "$d")
      local size=$(du -sh "$d" 2>/dev/null | cut -f1)
      local meta=""
      [ -f "${d}/backup_meta.yaml" ] && meta=$(head -2 "${d}/backup_meta.yaml" | tr '\n' ' ')
      printf "  %-30s %8s   %s\n" "$name" "$size" "$meta"
    done
  else
    echo "  (no backups yet)"
  fi
  echo "────────────────────────────────────────────────────────────"
  echo ""

  # Current live sizes for reference (may show N/A on Docker Desktop Windows)
  echo "Current live data sizes:"
  echo "  MongoDB:    $(docker exec gw-mongodb du -sh /data/db 2>/dev/null | cut -f1 || echo 'N/A (Docker VM)')"
  echo "  ES:         $(docker exec gw-elasticsearch du -sh /usr/share/elasticsearch/data 2>/dev/null | cut -f1 || echo 'N/A (Docker VM)')"
  echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
#  CLEAN — keep only last N backups
# ═══════════════════════════════════════════════════════════════════════════
do_clean() {
  local keep="${1:-5}"
  if [ ! -d "$BACKUP_ROOT" ]; then
    info "No backups directory; nothing to clean."
    exit 0
  fi
  local backups
  backups=($(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null))
  local total=${#backups[@]}
  if [ "$total" -le "$keep" ]; then
    info "Have ${total} backups, keeping up to ${keep}. Nothing to clean."
    exit 0
  fi
  local remove=$((total - keep))
  info "Removing ${remove} old backup(s), keeping last ${keep}..."
  for ((i=keep; i<total; i++)); do
    warn "Removing: ${backups[$i]}"
    rm -rf "${backups[$i]}"
  done
  ok "Cleaned. $(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | wc -l) backups remaining."
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
mkdir -p "$BACKUP_ROOT"

case "${1:-}" in
  backup)
    do_backup "${2:-$TIMESTAMP}"
    ;;
  restore)
    [ -z "${2:-}" ] && { err "Usage: backup-db.sh restore <backup_dir>"; exit 1; }
    do_restore "$2"
    ;;
  list|ls)
    do_list
    ;;
  clean)
    do_clean "${3:-5}"
    ;;
  *)
    echo "Usage: $0 {backup|restore|list|clean}"
    echo ""
    echo "  backup [--name <tag>]   Full backup (MongoDB + ES)"
    echo "  restore <dir>           Restore from backup directory"
    echo "  list                    List all backups with sizes"
    echo "  clean --keep N          Keep only last N backups (default 5)"
    echo ""
    echo "Examples:"
    echo "  $0 backup --name v4.14  # Named snapshot for version rollback"
    echo "  $0 restore docker-data/backups/v4.14"
    echo "  $0 clean --keep 5"
    exit 1
    ;;
esac
