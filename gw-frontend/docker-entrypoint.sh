#!/bin/sh
# R6.67.1: docker-entrypoint.sh for gw-frontend (nginx:1.19.9-alpine)
#
# Purpose: enable `read_only: true` + tmpfs `mode: 1777` in compose by
# re-chowning the writable paths to nginx:nginx after tmpfs mounts.
# Then drop to USER nginx for the actual nginx processes.
#
# Why this works:
#   1. compose mounts tmpfs /var/cache/nginx /var/run/nginx /var/log/nginx
#      with mode 1777 — the tmpfs is initially root:root 1777.
#   2. nginx master (run by us as root) chowns them to nginx:nginx.
#   3. su-exec drops to USER nginx before exec'ing nginx.
#   4. nginx workers (specified by `user nginx;` in nginx.conf) run as nginx.
#
# Required compose setup:
#   read_only: true
#   tmpfs:
#     - /var/cache/nginx:mode=1777
#     - /var/run/nginx:mode=1777
#     - /var/log/nginx:mode=1777
#     - /tmp:mode=1777
#     - /var/run:mode=1777

set -e

# Re-chown writable paths (in case tmpfs masked our build-time chown)
chown -R nginx:nginx \
    /var/cache/nginx \
    /var/run/nginx \
    /var/log/nginx

# Ensure nginx user owns the pid directory specifically
mkdir -p /var/run/nginx
chown nginx:nginx /var/run/nginx

# Drop privileges and exec nginx
echo "[entrypoint] dropping to nginx user via su-exec..."
exec su-exec nginx "$@"
