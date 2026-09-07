# Build stage: Node.js
FROM node:21.6.2-bullseye AS builder

COPY package*.json ./
RUN rm -f package-lock.json && npm install --registry=https://registry.npmjs.org/
COPY . .
ARG APP_RUN_ENV
RUN if [ "$APP_RUN_ENV" = "prod" ]; then npm run build; else npm run dev; fi

# Runtime stage: Nginx
FROM nginx:1.19.9-alpine

# R6.67.1: install su-exec (small Alpine setuid wrapper) so the entrypoint
# can start as root, chown tmpfs paths (required when compose sets
# read_only: true + tmpfs mode:1777), then drop to USER nginx for workers.
RUN apk add --no-cache su-exec

COPY --from=builder build/ /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY mime.types /etc/nginx/mime.types
COPY nginx-includes/ /etc/nginx/includes/
COPY nginx-shared/ /etc/nginx/shared/
COPY ssl/ /etc/nginx/ssl/
COPY nginx.conf /etc/nginx/nginx.conf

# R6.67.1: pre-create writable paths at BUILD time as root.
# At RUNTIME the compose tmpfs mounts will overlay these paths; the
# entrypoint below will re-chown them so nginx user can write to them.
RUN mkdir -p /var/cache/nginx /var/run/nginx /var/log/nginx \
    && chown -R nginx:nginx /var/cache/nginx /var/run/nginx /var/log/nginx \
    && chmod 755 /var/cache/nginx /var/run/nginx /var/log/nginx \
    && chmod -R 755 /usr/share/nginx/html

# R6.67.1: startup wrapper (runs as root, chowns tmpfs paths, then
# drops to USER nginx via su-exec). This makes the container safe to
# run with `read_only: true` + tmpfs `mode: 1777` in compose.
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80
# R6.38: nginx config reload watcher (dev only)
COPY nginx-reload-watcher.sh /usr/share/nginx/reload-watcher.sh
EXPOSE 443

# R6.67.1: do NOT set USER nginx here -- entrypoint needs root to chown
# the tmpfs paths, then drops privileges via su-exec.
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
