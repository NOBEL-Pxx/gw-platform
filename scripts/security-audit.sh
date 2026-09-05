#!/bin/bash
# Security audit — GravitationalWave Platform v4.12
# Usage: bash scripts/security-audit.sh
cd "$(dirname "$0")/.." || exit 1
echo "=== GW Platform Security Audit: $(date) ==="
echo ""

# 1. Port exposure check
echo "[1/5] Port exposure"
docker ps --filter "name=gw-" --format "{{.Names}} {{.Ports}}" | while read name ports; do
  if echo "$ports" | grep -q "0.0.0.0"; then
    echo "  WARN: $name has host-exposed ports: $ports"
  else
    echo "  OK:   $name ($ports)"
  fi
done
echo ""

# 2. Image digests + versions
echo "[2/5] Container images"
docker ps --filter "name=gw-" --format "{{.Names}} {{.Image}}" | while read name img; do
  digest=$(docker inspect "$name" --format '{{.Image}}' 2>/dev/null | cut -c1-12)
  echo "  $name: $img ($digest)"
done
echo ""

# 3. CSP / HTTPS check
echo "[3/5] HTTPS + CSP"
curl -skI https://localhost:6002/ 2>/dev/null | grep -iE "strict-transport|content-security" | while read line; do
  echo "  $line"
done
echo ""

# 4. Auth check
echo "[4/5] Auth endpoints"
curl -sk -o /dev/null -w "  POST /register: %{http_code}\n" "https://localhost:6002/api/auth/register" -X POST -H "Content-Type: application/json" -d '{"username":"_audit_test_","password":"_audit_test_"}' 2>/dev/null
curl -sk https://localhost:6002/api/auth/verify 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  GET  /verify (no token): {d[\"error\"][\"code\"]}')" 2>/dev/null
echo ""

# 5. Database auth
echo "[5/5] Database auth"
ES_PW=$(grep ES_PASSWORD .env 2>/dev/null | cut -d= -f2)
MONGO_PW=$(grep MONGO_ROOT_PASSWORD .env 2>/dev/null | cut -d= -f2)

# ES: without auth should fail
ES_NOAUTH=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:9200 2>/dev/null)
echo "  ES (no auth): $ES_NOAUTH (expect 000/401)"

# Mongo: without auth should fail
MONGO_NOAUTH=$(docker exec gw-mongodb mongosh --quiet --eval "db.runCommand({connectionStatus:1})" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok',0))" 2>/dev/null)
echo "  MongoDB (no auth): ${MONGO_NOAUTH:-blocked} (expect 0/blocked)"
echo ""

echo "Audit complete."
