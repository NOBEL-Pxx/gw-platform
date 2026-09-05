#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Cache Preheat Script (v4.15)
# Warms the Nginx proxy cache by pre-fetching FITS thumbnails and static files.
# Run after deploy or FITS data update to pre-populate the cache.
#
# Usage:
#   bash scripts/cache-preheat.sh              # Preheat all
#   bash scripts/cache-preheat.sh --survey DSS2 # Preheat single survey
#   bash scripts/cache-preheat.sh --dry-run    # List what would be fetched
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${GW_PREHEAT_URL:-http://localhost:6001}"
DRY_RUN=false
TARGET_SURVEY=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --survey) TARGET_SURVEY="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --url) BASE_URL="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# ── Discover FITS file list via pipeline API ───────────────────────────────
info "Fetching file list from pipeline..."
survey_param=""
[ -n "$TARGET_SURVEY" ] && survey_param="?survey=${TARGET_SURVEY}"

FILE_LIST=$(curl -sf "${BASE_URL}/pipeline/files${survey_param}" 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d.get('files', [])
surveys = d.get('surveys', [])
print(f'COUNT:{len(files)}')
print(f'SURVEYS:{len(surveys)}')
for f in files:
    print(f['name'])
" 2>/dev/null) || {
  err "Failed to fetch file list. Is the platform running?"
  exit 1
}

COUNT=$(echo "$FILE_LIST" | grep 'COUNT:' | cut -d: -f2)
SURVEY_COUNT=$(echo "$FILE_LIST" | grep 'SURVEYS:' | cut -d: -f2)
FILES=$(echo "$FILE_LIST" | grep -v 'COUNT:\|SURVEYS:')

info "Found ${COUNT} FITS files across ${SURVEY_COUNT} surveys"
[ "$DRY_RUN" = true ] && echo "$FILES" && exit 0

# ── Fetch thumbnail for each FITS file (primary cache load) ─────────────────
FETCHED=0
SKIPPED=0
START_TIME=$(date +%s)

info "Preheating thumbnail cache..."
for f in $FILES; do
  # Thumbnail endpoint (heavy — generates image from FITS)
  local url="${BASE_URL}/pipeline/thumbnail?filename=${f}&size=256"
  local status
  status=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    FETCHED=$((FETCHED + 1))
  else
    SKIPPED=$((SKIPPED + 1))
  fi
  # Progress every 10
  [ $(( (FETCHED + SKIPPED) % 10 )) -eq 0 ] && \
    printf "  %3d/%d  (ok:%d skip:%d)\r" $((FETCHED + SKIPPED)) "$COUNT" "$FETCHED" "$SKIPPED"
done
printf "\n"

# ── Static-file FITS downloads (secondary cache load) ───────────────────────
# Fetch the raw FITS downloads through the nginx proxy cache
# Only do a subset (first 5 per survey) to avoid overwhelming the system
info "Preheating FITS proxy cache (first 5 per survey)..."
FITS_COUNT=0
for f in $FILES; do
  # Only cache first 5 files total for raw FITS (they're large)
  if [ $FITS_COUNT -ge 5 ]; then break; fi
  local url="${BASE_URL}/static-files/fits/${f}"
  curl -sf -o /dev/null "$url" 2>/dev/null && FITS_COUNT=$((FITS_COUNT + 1)) || true
done
printf "  %d FITS files cached\n" "$FITS_COUNT"

# ── Summary ─────────────────────────────────────────────────────────────────
ELAPSED=$(($(date +%s) - START_TIME))
echo ""
echo "════════════════════════════════════════════════"
echo "  Cache Preheat Complete"
echo "  Thumbnails: $FETCHED ok, $SKIPPED skipped"
echo "  FITS files: $FITS_COUNT cached"
echo "  Time: ${ELAPSED}s"
echo "════════════════════════════════════════════════"
