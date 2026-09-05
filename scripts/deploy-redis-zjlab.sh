#!/bin/bash
# R6.54: zjlab Redis deployment script
# Run from bastion: ssh amax@11.tcp.vip.cpolar.cn -p 12394
# Or directly on zjlab: bash scripts/deploy-redis-zjlab.sh
#
# What this does:
#   1. Add redis service + backend env to docker-compose.yml
#   2. Restart gw-redis + gw-backend with SPRING_PROFILES_ACTIVE=local,redis
#   3. Verify health: redis ping + actuator/health

set -e

echo "=== Step 1: Sync updated docker-compose.yml + application-redis.properties ==="
cd /home/amax/AliCPT || cd ~/AliCPT || cd /opt/AliCPT || cd /root/AliCPT
pwd

# Confirm files updated
grep -q 'gw-redis' docker-compose.yml && echo '  docker-compose.yml has gw-redis: OK' || {
  echo '  docker-compose.yml missing gw-redis, abort'; exit 1
}
grep -q 'application-redis.properties' gw-backend/start/src/main/resources/ &&   echo '  application-redis.properties present: OK' || {
  echo '  application-redis.properties missing, abort'; exit 1
}

echo ""
echo "=== Step 2: Build new backend image (with redis profile deps) ==="
# bucket4j-redis + lettuce are <optional> in pom, so mvn will skip them in default jar.
# We need to either: a) build with redis deps included, or b) rely on dev profile only.
# For zjlab prod, we want redis rate limiting, so build with explicit include:
docker compose build gw-backend \
  --build-arg MAVEN_OPTS="-Dmaven.optional.include=com.bucket4j:bucket4j-redis,io.lettuce:lettuce-core,org.springframework.boot:spring-boot-starter-data-redis"

echo ""
echo "=== Step 3: Start Redis + restart backend with redis profile ==="
docker compose up -d redis
docker compose up -d --force-recreate --no-deps gw-backend

echo ""
echo "=== Step 4: Verify ==="
sleep 10
echo "--- Redis ping ---"
docker exec gw-redis redis-cli ping || echo "Redis ping FAILED"

echo ""
echo "--- Backend logs (last 30 lines, looking for 'Redis' / 'Lettuce' / 'redis profile') ---"
docker logs --tail 30 divs-backend | grep -iE "redis|lettuce|profile|ratelimit|rate.limit" || echo "No redis-related logs found"

echo ""
echo "--- Backend actuator/health (Redis indicator) ---"
curl -sf http://localhost:8093/actuator/health/redis || echo "actuator/health/redis endpoint not enabled"

echo ""
echo "=== Done ==="
echo "To toggle off Redis (back to in-memory rate limiting):"
echo "  docker compose stop redis"
echo "  docker compose up -d --force-recreate --no-deps --env SPRING_PROFILES_ACTIVE=local gw-backend"
