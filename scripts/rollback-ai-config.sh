#!/bin/bash
#==============================================================================
# AI Config Rollback — GravitationalWave Platform v4.37
# Restores AI configuration from a snapshot.
#
# Usage:
#   bash scripts/rollback-ai-config.sh <snapshot-id>
#   bash scripts/rollback-ai-config.sh --list
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SNAPSHOT_DIR="${PROJECT_DIR}/version-snapshots/ai-config"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ ! -d "$SNAPSHOT_DIR" ]; then
  echo -e "${RED}No AI config snapshots found.${NC}"
  echo "Run snapshot-ai-config.sh first."
  exit 1
fi

case "${1:-}" in
  --list|-l)
    echo -e "${CYAN}Available AI Config Snapshots:${NC}"
    for snap in "${SNAPSHOT_DIR}"/snapshot_*/; do
      [ -d "$snap" ] || continue
      local name=$(basename "$snap")
      local count=$(find "$snap" -type f 2>/dev/null | wc -l)
      local size=$(du -sh "$snap" 2>/dev/null | cut -f1)
      echo "  ${name}  (${count} files, ${size})"
    done
    ;;
  --help|-h)
    echo "Usage: $0 <snapshot-id>"
    echo "       $0 --list"
    echo ""
    echo "Delegates to snapshot-ai-config.sh --restore"
    ;;
  *)
    if [ -z "${1:-}" ]; then
      echo "Usage: $0 <snapshot-id>"
      echo ""
      bash "$0" --list
      exit 1
    fi
    # Delegate to comprehensive snapshot script
    bash "${SCRIPT_DIR}/snapshot-ai-config.sh" --restore "$1"
    ;;
esac
