#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# verify-compose-security.sh (R6.25)
# CI gate: validate Docker Compose security posture before deploy.
# Exits non-zero on any failure (build-blocking).
# ═══════════════════════════════════════════════════════════════════════════

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

fail=0
pass=0

check() {
    local desc="$1"
    local cmd="$2"
    local expected="$3"  # "0" or "1" or ">0"

    result=$(eval "$cmd" 2>&1 | grep -E "^[0-9]+$" | head -1 || echo "0")
    result=${result:-0}

    case "$expected" in
        "0")
            if [ "$result" = "0" ]; then
                echo -e "${GREEN}[OK]${NC} $desc (matches=0)"
                pass=$((pass + 1))
            else
                echo -e "${RED}[FAIL]${NC} $desc (matches=$result, expected 0)"
                fail=$((fail + 1))
            fi
            ;;
        ">0")
            if [ "$result" -gt "0" ]; then
                echo -e "${GREEN}[OK]${NC} $desc (matches=$result)"
                pass=$((pass + 1))
            else
                echo -e "${RED}[FAIL]${NC} $desc (matches=$result, expected >0)"
                fail=$((fail + 1))
            fi
            ;;
    esac
}

echo "=== R6.25 Compose Security Verification ==="
echo ""

# Check 1: xpack.security must be ON in main compose (R6.25 fixes v4.54)
check "xpack.security.enabled=true in main compose" \
      "grep -c 'xpack.security.enabled=true' docker-compose.yml" \
      ">0"

# Check 2: MongoDB auth must be wired (not commented out)
check "SPRING_DATA_MONGODB_USERNAME wired in gw-backend" \
      "grep -c 'SPRING_DATA_MONGODB_USERNAME' docker-compose.yml" \
      ">0"

check "SPRING_DATA_MONGODB_PASSWORD env var injection" \
      "grep -c 'SPRING_DATA_MONGODB_PASSWORD.*MONGO_APP_PASSWORD' docker-compose.yml" \
      ">0"

# Check 3: ES password must be env-injected
check "ES_PASSWORD env var injection (not hardcoded)" \
      "grep -c 'ELASTIC_PASSWORD=.*ES_PASSWORD' docker-compose.yml" \
      ">0"

# Check 4: Prod compose must remove host ports for data tier
check "Prod compose removes MongoDB host port" \
      "grep -A3 'mongodb:' docker-compose.prod.yml | grep -c 'ports: \[\]' || true" \
      ">0"

check "Prod compose removes ES host port" \
      "grep -A3 'elasticsearch:' docker-compose.prod.yml | grep -c 'ports: \[\]' || true" \
      ">0"

# Check 5: Dev compose must keep auth ON (no v4.54 regression)
check "Dev compose does NOT disable MongoDB auth" \
      "grep -c 'SPRING_DATA_MONGODB_USERNAME' docker-compose.dev.yml || echo 0" \
      ">0"

# Check 6: No API key leaks in docs
check "No API keys leaked in docs/" \
      "grep -rE 'sk-[a-zA-Z0-9]{20}' docs/ 2>/dev/null | wc -l" \
      "0"

# Check 7: .env files must NOT be tracked
check ".env not tracked by git" \
      "git ls-files | grep -c '^\.env$' || echo 0" \
      "0"

# Check 8: docker-compose.prod.yml exists
check "docker-compose.prod.yml exists" \
      "test -f docker-compose.prod.yml && echo 1 || echo 0" \
      ">0"

# Check 9: docker-compose.dev.yml exists (R6.25 added)
check "docker-compose.dev.yml exists" \
      "test -f docker-compose.dev.yml && echo 1 || echo 0" \
      ">0"

# Check 10: Combined compose config validates
echo ""
echo "=== Combined compose validation ==="
if docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q 2>/dev/null; then
    echo -e "${GREEN}[OK]${NC} Combined dev+prod compose validates"
    pass=$((pass + 1))
else
    echo -e "${RED}[FAIL]${NC} Combined dev+prod compose has errors"
    docker compose -f docker-compose.yml -f docker-compose.prod.yml config 2>&1 | tail -20
    fail=$((fail + 1))
fi

echo ""
echo "=== Summary ==="
echo -e "Passed: ${GREEN}${pass}${NC}"
echo -e "Failed: ${RED}${fail}${NC}"

if [ "$fail" -gt "0" ]; then
    echo ""
    echo -e "${RED}COMPOSE SECURITY VERIFICATION FAILED${NC}"
    echo "See docs/SECURITY_POLICY.md for remediation guidance."
    exit 1
fi

echo ""
echo -e "${GREEN}COMPOSE SECURITY VERIFICATION PASSED${NC}"
exit 0
