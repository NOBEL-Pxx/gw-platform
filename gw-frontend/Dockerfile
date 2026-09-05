# Build stage: Node.js
FROM node:21.6.2-bullseye AS builder

COPY package*.json ./
RUN rm -f package-lock.json && npm install --registry=https://registry.npmjs.org/
COPY . .
ARG APP_RUN_ENV
RUN if [ "$APP_RUN_ENV" = "prod" ]; then npm run build; else npm run dev; fi

# Runtime stage: Nginx
FROM nginx:1.19.9-alpine
COPY --from=builder build/ /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY mime.types /etc/nginx/mime.types
COPY nginx-includes/ /etc/nginx/includes/
COPY nginx-shared/ /etc/nginx/shared/
COPY ssl/ /etc/nginx/ssl/
COPY nginx.conf /etc/nginx/nginx.conf

# v4.37: Security hardening — use built-in nginx user + fix permissions
RUN chown -R nginx:nginx /usr/share/nginx/html /etc/nginx /var/cache/nginx /var/log/nginx \
    && chmod -R 755 /usr/share/nginx/html
USER nginx

EXPOSE 80
# R6.38: nginx config reload watcher (dev only)
COPY nginx-reload-watcher.sh /usr/share/nginx/reload-watcher.sh
EXPOSE 443
CMD ["nginx", "-g", "daemon off;"]
