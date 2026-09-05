#!/bin/bash
# Data backup script — GravitationalWave Platform v4.12
# Usage: bash scripts/backup.sh [backup-dir]
set -e
cd "$(dirname "$0")/.." || exit 1
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/gw-backup-$TIMESTAMP"
mkdir -p "$BACKUP_PATH"
echo "=== GW Platform Backup: $TIMESTAMP ==="

echo "[1/3] Config files..."
cp docker-compose.yml "$BACKUP_PATH/" 2>/dev/null || true
cp .env "$BACKUP_PATH/" 2>/dev/null || true
cp init_mongo.js "$BACKUP_PATH/" 2>/dev/null || true

echo "[2/3] MongoDB dump..."
docker exec gw-mongodb mongodump --authenticationDatabase admin --db gravitationalwave --out /data/backup 2>/dev/null && \
  docker cp gw-mongodb:/data/backup "$BACKUP_PATH/mongodb" 2>/dev/null && \
  echo "  MongoDB dumped" || echo "  MongoDB skipped"

echo "[3/3] Size summary..."
du -sh "$BACKUP_PATH"
echo "Backup complete: $BACKUP_PATH"
