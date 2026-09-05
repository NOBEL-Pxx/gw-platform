#!/bin/bash
# Unified log viewer — GravitationalWave Platform v4.12
# Usage: bash scripts/logs.sh [container] [--follow] [--errors] [--tail N]
cd "$(dirname "$0")/.." || exit 1

CONTAINER="${1:-all}"
shift 2>/dev/null || true
FOLLOW=""
ERRORS=""
TAIL="--tail 50"

for arg in "$@"; do
  case "$arg" in
    --follow|-f) FOLLOW="--follow" ;;
    --errors|-e) ERRORS="1"; TAIL="--tail 200" ;;
    --tail) shift; TAIL="--tail $2"; shift ;;
  esac
done

if [ "$CONTAINER" = "all" ]; then
  echo "=== All containers ==="
  if [ -n "$ERRORS" ]; then
    docker compose logs $TAIL --no-log-prefix 2>/dev/null | grep -iE "error|exception|fail|warn|critical|emerg"
  else
    docker compose logs $TAIL $FOLLOW
  fi
else
  echo "=== $CONTAINER ==="
  if [ -n "$ERRORS" ]; then
    docker logs $TAIL "$CONTAINER" 2>&1 | grep -iE "error|exception|fail|warn"
  else
    docker logs $TAIL $FOLLOW "$CONTAINER" 2>&1
  fi
fi
