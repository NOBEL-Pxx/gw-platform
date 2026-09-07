#!/usr/bin/env bash
# R6.69-#3: zjlab redis ACL + ES port 9200 cleanup (diagnostic + safe)
#
# What this does:
#   1. Read-only diagnostic of redis, port 9200, docker orphans
#   2. Identifies dead/exited containers (candidates for `docker rm`)
#   3. Lists anonymous users in Redis ACL
#   4. Proposes cleanup actions (printed, NOT executed)
#
# Pre-conditions:
#   - Run as zjlab user on zjlab server (10.107.207.103 via bastion or cpolar)
#   - User has sudo for docker commands (or be in docker group)
#
# Manual confirm before any destructive op (per memory manual-confirm-major-changes)

set -euo pipefail
SCRIPT_NAME="r669-zjlab-redis-es-cleanup"
LOG_DIR="${HOME}/.r669-logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S)-redis-es-cleanup.log"

echo "=== R6.69-#3 zjlab redis + ES diagnostic ===" | tee "$LOG"
echo "[$(date +%FT%TZ)] user=$(whoami) host=$(hostname)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Section 1: docker compose stack status ──────────────────────────────
echo "[1/6] docker compose stack (gravitationalwave-v4.31)" | tee -a "$LOG"
cd /home/zjlab/gravitationalwave-v4.31 2>/dev/null || cd /opt/gravitationalwave-v4.31 || {
    echo "  [WARN] stack dir not found in standard paths; trying docker ps -a instead" | tee -a "$LOG"
}
docker compose -f docker-compose.yml -f docker-compose.zjlab.yml     -f docker-compose.monitoring.yml ps 2>&1 | tee -a "$LOG" | head -40
echo "" | tee -a "$LOG"

# ── Section 2: port 9200 mapping check (was conflict with K8s) ──────────
echo "[2/6] port 9200 host mapping (should be EMPTY on zjlab)" | tee -a "$LOG"
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E '9200|elasticsearch' || echo "  [OK] no host port 9200 mapped (compose override cleared)" | tee -a "$LOG"
ss -ltn 2>/dev/null | grep ':9200\s' && echo "  [WARN] something is listening on host :9200" | tee -a "$LOG" || echo "  [OK] no host listener on :9200" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Section 3: redis state ──────────────────────────────────────────────
echo "[3/6] redis state" | tee -a "$LOG"
if docker ps --format '{{.Names}}' | grep -q '^gw-redis$'; then
    echo "  gw-redis is RUNNING" | tee -a "$LOG"
    echo "  -- ping --" | tee -a "$LOG"
    docker exec gw-redis redis-cli ping 2>&1 | tee -a "$LOG"
    echo "  -- ACL WHOAMI --" | tee -a "$LOG"
    docker exec gw-redis redis-cli ACL WHOAMI 2>&1 | tee -a "$LOG"
    echo "  -- ACL LIST (truncated to 10) --" | tee -a "$LOG"
    docker exec gw-redis redis-cli ACL LIST 2>&1 | head -10 | tee -a "$LOG"
    echo "  -- CONFIG GET requirepass --" | tee -a "$LOG"
    docker exec gw-redis redis-cli CONFIG GET requirepass 2>&1 | tee -a "$LOG"
    echo "  -- CLIENT LIST (sample 5) --" | tee -a "$LOG"
    docker exec gw-redis redis-cli CLIENT LIST 2>&1 | head -5 | tee -a "$LOG"
else
    echo "  [WARN] gw-redis NOT running" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Section 4: docker orphans (candidates for `docker rm`) ──────────────
echo "[4/6] docker orphans (Exited status, candidates for cleanup)" | tee -a "$LOG"
docker ps -a --filter 'status=exited' --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}' 2>&1 | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "  Candidates for cleanup (NOT auto-executed):" | tee -a "$LOG"
EXITS=$(docker ps -a --filter 'status=exited' --format '{{.Names}}' 2>/dev/null | grep -v '^gw-' || true)
if [ -n "$EXITS" ]; then
    echo "$EXITS" | while read -r NAME; do
        echo "    - docker rm $NAME   # verify it's safe first (docker inspect)" | tee -a "$LOG"
    done
else
    echo "  [OK] no orphan containers" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Section 5: docker image orphans (candidates for `docker rmi`) ────────
echo "[5/6] dangling docker images (candidates for cleanup)" | tee -a "$LOG"
docker images --filter 'dangling=true' --format 'table {{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}' 2>&1 | tee -a "$LOG"
DANGLING_COUNT=$(docker images --filter 'dangling=true' -q 2>/dev/null | wc -l)
echo "  Dangling image count: $DANGLING_COUNT" | tee -a "$LOG"
if [ "$DANGLING_COUNT" -gt 0 ]; then
    echo "  Candidates: docker image prune (NOT auto-executed)" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ── Section 6: zjlab disk + memory state ────────────────────────────────
echo "[6/6] disk + memory state" | tee -a "$LOG"
df -h / /home /data 2>/dev/null | tee -a "$LOG"
free -h | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── Final summary ───────────────────────────────────────────────────────
echo "=== END diagnostic ===" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Log saved: $LOG"
echo ""
echo "MANUAL REVIEW NEEDED BEFORE CLEANUP:"
echo "  1. Check the log for [WARN] markers"
echo "  2. If 'host port 9200 mapped' appears: docker compose restart (zjlab override should clear it)"
echo "  3. If 'requirepass' is empty + you want defense-in-depth:"
echo "       a) Add --requirepass to redis command in docker-compose.yml"
echo "       b) Update RATE_LIMIT_REDIS_URI to redis://:PASSWORD@redis:6379 in .env"
echo "       c) Restart redis + dependent services"
echo "  4. For each orphan container in Section 4: docker inspect NAME first, then docker rm NAME"
echo "  5. For dangling images: docker image prune (will free disk)"
