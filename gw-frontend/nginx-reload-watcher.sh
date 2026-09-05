#!/bin/bash
# R6.38: nginx config auto-reload watcher.
# Watches default.conf.template for changes and sends SIGHUP to nginx.
# Run this inside the gw-frontend container:
#   docker exec -d gw-frontend bash /usr/share/nginx/reload-watcher.sh

CONFIG="/etc/nginx/templates/default.conf.template"
RENDERED="/etc/nginx/conf.d/default.conf"

# Check tools available
if ! command -v inotifywait &> /dev/null; then
  # Fallback: poll every 5s (no inotifywait)
  while true; do
    sleep 5
    # nginx-template renders default.conf.template -> default.conf on every container start
    # For dev hot-reload, the devops person can run `docker exec gw-frontend nginx -s reload`
    if [ -f "$CONFIG" ]; then
      SIZE=$(stat -c%s "$CONFIG" 2>/dev/null || echo 0)
      echo "[nginx-reload-watcher] Config size: $SIZE (use 'docker exec gw-frontend nginx -s reload' to apply)"
    fi
  done
fi

# Real watcher (if inotifywait available)
inotifywait -m -e modify,create,delete "$CONFIG" 2>/dev/null | while read path action file; do
  echo "[nginx-reload-watcher] Config changed: $action"
  sleep 1  # debounce
  nginx -t 2>&1 && nginx -s reload && echo "[nginx-reload-watcher] nginx reloaded"
done
