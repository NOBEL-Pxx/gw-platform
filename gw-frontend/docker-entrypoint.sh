#!/bin/sh
# R6.67.1 + R6.67.3: docker-entrypoint.sh for gw-frontend (nginx:1.19.9-alpine)
#
# Purpose: enable `read_only: true` + tmpfs `mode=1777` in compose by
# re-chowning the writable paths to nginx:nginx after tmpfs mounts.
# Then run envsubst on /etc/nginx/templates/*.template -> /etc/nginx/conf.d/*.conf
# (R6.67.3: stock nginx entrypoint did this; our R6.67.1 entrypoint dropped it,
#  causing HTTPS 6002 to silently fall back to stock default.conf with no SSL).
# Finally drop to USER nginx for the actual nginx processes.

set -e

# R6.67.3: envsubst on templates (replaces stock nginx:alpine behavior).
# Filter only the env vars we care about to avoid leaking host env into config.
if [ -d /etc/nginx/templates ]; then
    for tmpl in /etc/nginx/templates/*.template; do
        [ -e "$tmpl" ] || continue
        out="/etc/nginx/conf.d/$(basename "$tmpl" .template)"
        if [ -n "$NGINX_ENVSUBST_FILTER" ]; then
            # R6.67.3c: envsubst expects a regex pattern, not a var list.
            # Build "$VAR1|$VAR2" (stock nginx entrypoint pattern).
            # Stock `envsubst "$NGINX_ENVSUBST_FILTER"` (quoted) only works in
            # bash, busybox sh treats inner space as a separator, so
            # explicitly join vars with `|`.
            PATTERN=""
            for v in $NGINX_ENVSUBST_FILTER; do
                if [ -z "$PATTERN" ]; then
                    PATTERN="\$$v"
                else
                    PATTERN="$PATTERN|\$$v"
                fi
            done
            envsubst "$PATTERN" < "$tmpl" > "$out"
        else
            envsubst < "$tmpl" > "$out"
        fi
        echo "[entrypoint] envsubst: $tmpl -> $out"
    done
fi

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
