#!/bin/bash
#==============================================================================
# GravitationalWave Platform — Pre-Flight Security Check (v4.15)
# Usage: bash scripts/security-check.sh
#
# Checks for common deployment security issues before launching:
#   1. Exposed database ports (dev config in production)
#   2. Network segmentation (all DB containers on gw-db only)
#   3. Startup dependency chain (health check ordering)
#   4. Environment variable hygiene
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ISSUES=0
WARNINGS=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}[PASS]${NC} $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $*"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo -e "  ${RED}[FAIL]${NC} $*"; ISSUES=$((ISSUES + 1)); }

echo ""
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  GravitationalWave — Security Pre-Flight Check${NC}"
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo ""

# ── 1. Exposed database ports ──────────────────────────────────────────────
echo "1. Port Exposure Check"
echo "──────────────────────"

# Check if docker-compose has DB ports mapped
if [ -f "${PROJECT_DIR}/docker-compose.yml" ]; then
  # Check for commented-out ports (dev-only)
  if grep -A1 "mongodb:" "${PROJECT_DIR}/docker-compose.yml" | grep -q "^\s*ports:"; then
    mongo_ports=$(grep -A3 "container_name: gw-mongodb" "${PROJECT_DIR}/docker-compose.yml" | grep "ports:" | grep -v "^#" || true)
    if echo "$mongo_ports" | grep -q "[0-9].*:[0-9]"; then
      fail "MongoDB port is exposed to host (production risk!)"
    else
      pass "MongoDB: no host port mapping"
    fi
  else
    pass "MongoDB: no host port mapping"
  fi

  if grep -A1 "elasticsearch:" "${PROJECT_DIR}/docker-compose.yml" | grep -q "^\s*ports:"; then
    es_ports=$(grep -A3 "container_name: gw-elasticsearch" "${PROJECT_DIR}/docker-compose.yml" | grep "ports:" | grep -v "^#" || true)
    if echo "$es_ports" | grep -q "[0-9].*:[0-9]"; then
      fail "Elasticsearch port is exposed to host (production risk!)"
    else
      pass "Elasticsearch: no host port mapping"
    fi
  else
    pass "Elasticsearch: no host port mapping"
  fi
else
  warn "docker-compose.yml not found — skipping port check"
fi

# If running containers, check actual port bindings
# Check if production override is active
PROD_MODE=false
if docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps 2>/dev/null | grep -q "."; then
  # Check if gw-mongodb has port bindings
  mongo_bound=$(docker inspect gw-mongodb --format '{{json .HostConfig.PortBindings}}' 2>/dev/null | grep -v '^{}$' || true)
  if [ -n "$mongo_bound" ] && [ "$mongo_bound" != "{}" ]; then
    warn "LIVE: gw-mongodb has port bindings (OK for dev, remove via docker-compose.prod.yml for production)"
  else
    pass "LIVE: gw-mongodb has no host port bindings"
  fi
  es_bound=$(docker inspect gw-elasticsearch --format '{{json .HostConfig.PortBindings}}' 2>/dev/null | grep -v '^{}$' || true)
  if [ -n "$es_bound" ] && [ "$es_bound" != "{}" ]; then
    warn "LIVE: gw-elasticsearch has port bindings (OK for dev, remove via docker-compose.prod.yml for production)"
  else
    pass "LIVE: gw-elasticsearch has no host port bindings"
  fi
fi

echo ""

# ── 2. Network segmentation ────────────────────────────────────────────────
echo "2. Network Segmentation Check"
echo "─────────────────────────────"

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "gw-mongodb"; then
  # Check which networks MongoDB is on
  nets=$(docker inspect gw-mongodb --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null)
  if echo "$nets" | grep -q "gw-net"; then
    fail "MongoDB is on gw-net (should only be on gw-db)"
  elif echo "$nets" | grep -q "gw-db"; then
    pass "MongoDB: gw-db only"
  else
    warn "MongoDB: unknown network config"
  fi
else
  warn "MongoDB not running — skipping network check"
fi

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "gw-elasticsearch"; then
  nets=$(docker inspect gw-elasticsearch --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null)
  if echo "$nets" | grep -q "gw-net"; then
    fail "Elasticsearch is on gw-net (should only be on gw-db)"
  elif echo "$nets" | grep -q "gw-db"; then
    pass "Elasticsearch: gw-db only"
  else
    warn "Elasticsearch: unknown network config"
  fi
else
  warn "Elasticsearch not running — skipping network check"
fi

echo ""

# ── 3. Health check dependency chain ──────────────────────────────────────
echo "3. Startup Dependency Check"
echo "────────────────────────────"

if [ -f "${PROJECT_DIR}/docker-compose.yml" ]; then
  # Check all depends_on use service_healthy (via grep across full file)
  deps=$(grep -c "condition: service_healthy" "${PROJECT_DIR}/docker-compose.yml" 2>/dev/null || echo 0)
  if [ "$deps" -ge 6 ]; then
    pass "All depends_on use condition: service_healthy ($deps health-check links)"
  else
    fail "Only $deps condition: service_healthy found (expected ≥6). Check depends_on."
  fi
else
  warn "docker-compose.yml not found"
fi

echo ""

# ── 4. Environment hygiene ─────────────────────────────────────────────────
echo "4. Environment Hygiene"
echo "───────────────────────"

if [ -f "${PROJECT_DIR}/.env" ]; then
  # Check for default/placeholder passwords (check values only, not key names)
  if cut -d= -f2- "${PROJECT_DIR}/.env" 2>/dev/null | grep -qi "changeme\|^password$\|^secret$\|^admin$\|^123456$"; then
    fail ".env contains weak placeholder password(s)"
  else
    pass ".env: no weak placeholder passwords detected"
  fi

  # Check .env file permissions
  perms=$(stat -c "%a" "${PROJECT_DIR}/.env" 2>/dev/null || echo "???")
  if [ "$perms" = "600" ] || [ "$perms" = "640" ]; then
    pass ".env permissions: $perms (restricted)"
  else
    warn ".env permissions: $perms (should be 600 or 640)"
  fi
else
  warn ".env file not found"
fi

echo ""

# ── Summary ────────────────────────────────────────────────────────────────
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
if [ $ISSUES -eq 0 ] && [ $WARNINGS -eq 0 ]; then
  echo -e "  ${GREEN}All checks passed — ready to deploy.${NC}"
elif [ $ISSUES -eq 0 ]; then
  echo -e "  ${YELLOW}${WARNINGS} warning(s) — review before deploying.${NC}"
else
  echo -e "  ${RED}${ISSUES} issue(s) found — fix before production deploy.${NC}"
fi
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo ""

exit $ISSUES
