#!/bin/bash
#==============================================================================
# AI Configuration Snapshot — GravitationalWave Platform v4.37
# Captures prompts, thresholds, MCP tool params for version rollback.
#
# Usage:
#   bash scripts/snapshot-ai-config.sh              # Snapshot now
#   bash scripts/snapshot-ai-config.sh --restore SNAPSHOT_DIR  # Restore
#   bash scripts/snapshot-ai-config.sh --list       # List snapshots
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SNAPSHOT_DIR="${PROJECT_DIR}/version-snapshots/ai-config"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_PATH="${SNAPSHOT_DIR}/snapshot_${TIMESTAMP}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── Sources to snapshot ────────────────────────────────────────────────────
PIPELINE_DIR="${PROJECT_DIR}/gw-pipeline/src/pipeline"

SOURCES=(
  # System prompts
  "${PIPELINE_DIR}/agent/agent_loop.py"
  # Tool schemas
  "${PIPELINE_DIR}/agent/tool_schemas.py"
  # Tool implementations
  "${PIPELINE_DIR}/agent/tools.py"
  # Server config (thresholds, compliance, quotas)
  "${PIPELINE_DIR}/server.py"
  # RBAC config
  "${PIPELINE_DIR}/rbac.py"
  # Local LLM config
  "${PIPELINE_DIR}/local_llm.py"
)

# ── Extract key config values ──────────────────────────────────────────────
extract_config() {
  local out="${SNAPSHOT_PATH}/config-values.txt"
  mkdir -p "${SNAPSHOT_PATH}"

  echo "AI Config Snapshot: $(date)" > "$out"
  echo "========================================" >> "$out"
  echo "" >> "$out"

  # Extract system prompt from agent_loop.py
  echo "[System Prompt]" >> "$out"
  grep -A5 "AGENT_SYSTEM_PROMPT\|SYSTEM_PROMPT" "${PIPELINE_DIR}/agent/agent_loop.py" 2>/dev/null | head -20 >> "$out" || echo "  (not found)" >> "$out"
  echo "" >> "$out"

  # Extract model config
  echo "[Model Config]" >> "$out"
  grep -E "DEEPSEEK_MODEL|temperature|max_tokens|max_tool_rounds" "${PIPELINE_DIR}/server.py" 2>/dev/null | head -10 >> "$out" || echo "  (not found)" >> "$out"
  echo "" >> "$out"

  # Extract compliance level
  echo "[Compliance]" >> "$out"
  grep -E "COMPLIANCE_LEVEL|_COMPLIANCE_LEVEL" "${PIPELINE_DIR}/server.py" 2>/dev/null | head -5 >> "$out" || echo "  (not found)" >> "$out"
  echo "" >> "$out"

  # Extract quota config
  echo "[Quotas]" >> "$out"
  grep -E "_LLM_DAILY_QUOTA|_SESSION_QUOTA|_QUOTA_WARN" "${PIPELINE_DIR}/server.py" 2>/dev/null | head -10 >> "$out" || echo "  (not found)" >> "$out"
  echo "" >> "$out"

  # RBAC config
  echo "[RBAC Roles]" >> "$out"
  grep -E "_ROLE_PERMISSIONS|GW_ROLE_CONFIG" "${PIPELINE_DIR}/rbac.py" 2>/dev/null | head -10 >> "$out" || echo "  (not found)" >> "$out"

  echo "Config values extracted to: $out"
}

# ── Copy source files ──────────────────────────────────────────────────────
copy_sources() {
  for src in "${SOURCES[@]}"; do
    if [ -f "$src" ]; then
      local rel="${src#$PROJECT_DIR/}"
      local dst="${SNAPSHOT_PATH}/${rel}"
      mkdir -p "$(dirname "$dst")"
      cp "$src" "$dst"
      echo "  $(basename "$src")"
    fi
  done

  # Also snapshot docker-compose and .env (non-secret parts)
  if [ -f "${PROJECT_DIR}/docker-compose.yml" ]; then
    cp "${PROJECT_DIR}/docker-compose.yml" "${SNAPSHOT_PATH}/"
    echo "  docker-compose.yml"
  fi

  # Snapshot .env key names only (NEVER values)
  if [ -f "${PROJECT_DIR}/.env" ]; then
    grep -E '^[A-Z_]+\s*=' "${PROJECT_DIR}/.env" | cut -d= -f1 > "${SNAPSHOT_PATH}/env-keys-only.txt" 2>/dev/null || true
    echo "  .env (keys only)"
  fi
}

# ── Compute checksums ──────────────────────────────────────────────────────
compute_checksums() {
  cd "${SNAPSHOT_PATH}" || return
  find . -type f -exec md5sum {} \; | sort > checksums.md5
  echo "  checksums.md5 ($(wc -l < checksums.md5) files)"
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

do_snapshot() {
  echo -e "${CYAN}AI Config Snapshot v4.37${NC}"
  echo "Snapshot: ${SNAPSHOT_PATH}"
  echo ""

  if [ -d "${SNAPSHOT_PATH}" ]; then
    echo -e "${YELLOW}Snapshot already exists, overwriting...${NC}"
    rm -rf "${SNAPSHOT_PATH}"
  fi

  mkdir -p "${SNAPSHOT_PATH}"

  echo "Copying sources..."
  copy_sources

  echo ""
  echo "Extracting config values..."
  extract_config

  echo ""
  echo "Computing checksums..."
  compute_checksums

  # Update manifest
  local manifest="${SNAPSHOT_DIR}/manifest.json"
  local count=$(find "${SNAPSHOT_DIR}" -maxdepth 1 -type d -name 'snapshot_*' | wc -l)
  echo "{\"last_snapshot\": \"${TIMESTAMP}\", \"total_snapshots\": ${count}, \"path\": \"${SNAPSHOT_PATH}\"}" > "${manifest}"

  echo ""
  echo -e "${GREEN}[OK] AI config snapshot created${NC}"
  echo "  Files in snapshot: $(find "${SNAPSHOT_PATH}" -type f | wc -l)"
  echo "  Size: $(du -sh "${SNAPSHOT_PATH}" | cut -f1)"
  echo ""
  echo "To restore: bash $0 --restore ${TIMESTAMP}"
}

do_list() {
  echo -e "${CYAN}AI Config Snapshots:${NC}"
  if [ ! -d "${SNAPSHOT_DIR}" ]; then
    echo "  No snapshots found."
    return
  fi
  for snap in "${SNAPSHOT_DIR}"/snapshot_*/; do
    local name=$(basename "$snap")
    local count=$(find "$snap" -type f | wc -l)
    local size=$(du -sh "$snap" 2>/dev/null | cut -f1)
    echo "  ${name}  (${count} files, ${size})"
  done
}

do_restore() {
  local target="$1"
  local target_path="${SNAPSHOT_DIR}/snapshot_${target}"

  if [ ! -d "$target_path" ]; then
    echo -e "${RED}[ERROR] Snapshot not found: ${target_path}${NC}"
    echo "Available snapshots:"
    do_list
    exit 1
  fi

  echo -e "${YELLOW}Restoring AI config from: ${target}${NC}"
  echo ""
  echo "Files to restore:"
  find "${target_path}" -type f -name '*.py' | while read f; do
    echo "  ${f#${target_path}/}"
  done
  echo ""

  # Confirm
  echo -n "Restore these files? This will OVERWRITE current config. [y/N]: "
  read -r confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    return
  fi

  # Restore Python source files
  local restored=0
  for src in "${SOURCES[@]}"; do
    local rel="${src#$PROJECT_DIR/}"
    local backup="${target_path}/${rel}"
    if [ -f "$backup" ]; then
      cp "$backup" "$src"
      echo "  [OK] Restored: ${rel}"
      restored=$((restored + 1))
    fi
  done

  echo ""
  echo -e "${GREEN}[OK] Restored ${restored} AI config files${NC}"
  echo -e "${YELLOW}Rebuild and restart containers for changes to take effect.${NC}"
}

# ── Parse args ─────────────────────────────────────────────────────────────
case "${1:-}" in
  --list|-l)
    do_list
    ;;
  --restore|-r)
    if [ -z "${2:-}" ]; then
      echo "Usage: $0 --restore <timestamp>"
      do_list
      exit 1
    fi
    do_restore "$2"
    ;;
  --help|-h)
    echo "Usage: $0 [--list|--restore <id>]"
    echo "  (no args)   Create new AI config snapshot"
    echo "  --list      List all snapshots"
    echo "  --restore   Restore AI config from snapshot"
    ;;
  *)
    do_snapshot
    ;;
esac
