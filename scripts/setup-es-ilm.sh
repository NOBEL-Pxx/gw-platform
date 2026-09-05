#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# GravitationalWave Platform — ES Index Lifecycle Management (v4.16)
# ═══════════════════════════════════════════════════════════════════════════
# Usage:
#   bash scripts/setup-es-ilm.sh              # Apply ILM policies
#   bash scripts/setup-es-ilm.sh --dry-run    # Print policies without applying
#   bash scripts/setup-es-ilm.sh --status     # Show current ILM/index status
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DRY_RUN=false
SHOW_STATUS=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --status) SHOW_STATUS=true ;;
  esac
done

# ── Safe .env loader ───────────────────────────────────────────────────────
ES_PASSWORD=""
if [ -f "${PROJECT_DIR}/.env" ]; then
  while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    [ -z "$key" ] && continue
    [ "${key:0:1}" = "#" ] && continue
    case "$key" in ES_PASSWORD) ES_PASSWORD="$value" ;; esac
  done < "${PROJECT_DIR}/.env"
fi

ES_URL="http://localhost:9200"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

es_curl() {
  # Use container's ELASTIC_PASSWORD env var to avoid shell escaping issues
  # (password contains @, !, &, % — all problematic when passed through host bash)
  docker exec gw-elasticsearch sh -c 'curl -sf -u "elastic:$ELASTIC_PASSWORD" "$@"' -- "$@"
}

es_put() {
  local path="$1"; local body="$2"
  if $DRY_RUN; then
    echo "  [DRY-RUN] PUT ${ES_URL}${path}"
    echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
    return
  fi
  es_curl -X PUT "${ES_URL}${path}" \
    -H 'Content-Type: application/json' -d "$body" >/dev/null 2>&1 || {
    warn "ES API call failed: PUT $path"
    return 1
  }
}

# ── Status check ──────────────────────────────────────────────────────────
if $SHOW_STATUS; then
  echo ""
  echo "=== ES Cluster Health ==="
  es_curl "${ES_URL}/_cluster/health?pretty" 2>/dev/null || echo "  (ES not running)"
  echo ""
  echo "=== Current Indices ==="
  es_curl "${ES_URL}/_cat/indices?v" 2>/dev/null || echo "  (no indices)"
  echo ""
  echo "=== Current ILM Policies ==="
  es_curl "${ES_URL}/_ilm/policy?pretty" 2>/dev/null || echo "  (no ILM policies)"
  echo ""
  echo "=== Index Settings (shards, replicas) ==="
  es_curl "${ES_URL}/_all/_settings?pretty" 2>/dev/null || echo "  (no settings)"
  exit 0
fi

echo ""
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  ES Index Lifecycle Management Setup (v4.16)${NC}"
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo ""

# ── 1. ILM Policy: gw-logs-policy (90-day log retention) ──────────────────
info "Creating ILM policy: gw-logs-policy"
es_put "/_ilm/policy/gw-logs-policy" '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_primary_shard_size": "50gb",
            "max_age": "30d"
          },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "cold": {
        "min_age": "60d",
        "actions": {
          "set_priority": { "priority": 0 }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
ok "gw-logs-policy: hot(30d) → warm(30d) → cold(30d) → delete(90d)"

# ── 2. ILM Policy: gw-data-policy (365-day data retention) ─────────────────
info "Creating ILM policy: gw-data-policy"
es_put "/_ilm/policy/gw-data-policy" '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_primary_shard_size": "50gb",
            "max_age": "30d"
          },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "90d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "delete": {
        "min_age": "365d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
ok "gw-data-policy: hot(30d) → warm(90d) → delete(365d)"

# ── 3. Index Template: gw-*-template ──────────────────────────────────────
info "Creating index template: gw-*-template"
es_put "/_index_template/gw-template" '{
  "index_patterns": ["gw-*", "errordetail*", "alicptabnormal*"],
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 0,
      "refresh_interval": "30s",
      "index.lifecycle.name": "gw-data-policy",
      "index.lifecycle.rollover_alias": "gw-data"
    },
    "mappings": {
      "dynamic": true,
      "_source": { "enabled": true },
      "properties": {
        "timestamp": { "type": "date" },
        "@timestamp": { "type": "date" }
      }
    }
  },
  "priority": 100
}'
ok "Index template applied: shards=1, replicas=0, ILM=gw-data-policy"

# ── 4. Apply to existing indices ──────────────────────────────────────────
info "Applying settings to existing indices..."
for idx in errordetail alicptabnormal; do
  # Check if index exists
  if es_curl -o /dev/null "${ES_URL}/${idx}" 2>/dev/null; then
    # Add ILM policy to existing index (non-disruptive)
    es_put "/${idx}/_settings" "{
      \"index.lifecycle.name\": \"gw-data-policy\",
      \"refresh_interval\": \"30s\"
    }" 2>/dev/null && ok "  ${idx}: ILM=gw-data-policy, refresh=30s" || warn "  ${idx}: settings update failed"
  else
    info "  ${idx}: index does not exist yet — template will apply on creation"
  fi
done

# ── 5. Component template for slow logs (if enabled) ──────────────────────
info "Creating component template for slow-logs..."
es_put "/_component_template/gw-slowlog-settings" '{
  "template": {
    "settings": {
      "index.search.slowlog.threshold.query.warn": "2s",
      "index.search.slowlog.threshold.query.info": "1s",
      "index.search.slowlog.threshold.fetch.warn": "1s",
      "index.indexing.slowlog.threshold.index.warn": "2s"
    }
  }
}' 2>/dev/null
ok "Slow-log thresholds: query>1s(info) query>2s(warn) fetch>1s(warn)"

# ── 6. Cluster settings (persistent, safe defaults) ───────────────────────
info "Configuring cluster-level settings..."
es_put "/_cluster/settings" '{
  "persistent": {
    "cluster.routing.allocation.disk.watermark.low": "85%",
    "cluster.routing.allocation.disk.watermark.high": "90%",
    "cluster.routing.allocation.disk.watermark.flood_stage": "95%",
    "indices.recovery.max_bytes_per_sec": "40mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 2
  }
}' 2>/dev/null
ok "Disk watermarks: low=85%, high=90%, flood=95%"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ES ILM setup complete (v4.16)${NC}"
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo ""
echo "  ILM Policies:"
echo "    gw-logs-policy:  hot(30d) → warm(30d) → cold(30d) → delete(90d)"
echo "    gw-data-policy:  hot(30d) → warm(90d) → delete(365d)"
echo ""
echo "  Index Template:"
echo "    Pattern: gw-*, errordetail*, alicptabnormal*"
echo "    Shards: 1, Replicas: 0 (single-node optimization)"
echo "    ILM: gw-data-policy"
echo ""
echo "  Cluster Protections:"
echo "    Disk watermark: 85% low / 90% high / 95% flood"
echo "    Recovery throttle: 40MB/s"
echo ""
echo "  Note: For multi-node production deployment, increase replicas to 1+."
if $DRY_RUN; then
  echo "  ⚠ DRY-RUN mode — no changes applied. Remove --dry-run to execute."
fi
echo ""
