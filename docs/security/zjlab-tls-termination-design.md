# R6.76 zjlab TLS Termination — Design Doc

**Status**: R6.76 design + script. R6.77+ requires zjlab host + domain + DNS access.

## Problem

Currently gw-frontend nginx listens on HTTP (port 80 → 6001) and HTTPS (port 443 → 6002)
with self-signed certs. Production deployment at zjlab should use Let's Encrypt
with auto-renewal.

## Solution

Add a separate nginx instance in front of gw-frontend that:
1. Terminates TLS using Let's Encrypt certs
2. Forwards plaintext to gw-frontend (port 6001)
3. Auto-renews certs via certbot timer

## Architecture

```
Internet (HTTPS:443)
   |
   v
[zjlab-nginx] <-- Let's Encrypt certs (auto-renewed)
   |
   v HTTP:80 (internal Docker network)
   |
[gw-frontend] (existing)
```

## Files to add (R6.77+)

### `zjlab-deploy/tls-termination/nginx.conf`
```nginx
server {
    listen 80;
    server_name gw-platform.zhejianglab.cn;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name gw-platform.zhejianglab.cn;

    ssl_certificate     /etc/letsencrypt/live/gw-platform.zhejianglab.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gw-platform.zhejianglab.cn/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://gw-frontend:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### `zjlab-deploy/tls-termination/init-certbot.sh`
```bash
#!/bin/bash
DOMAIN=gw-platform.zhejianglab.cn
EMAIL=ops@zhejianglab.cn
docker run --rm \
    -v /etc/letsencrypt:/etc/letsencrypt:rw \
    -v /var/www/certbot:/var/www/certbot:rw \
    certbot/certbot certonly --webroot \
    --webroot-path=/var/www/certbot \
    --email $EMAIL --agree-tos --no-eff-email \
    -d $DOMAIN
```

### `zjlab-deploy/tls-termination/docker-compose.yml`
```yaml
version: '3.8'
services:
  nginx:
    image: nginx:1.25-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /var/www/certbot:/var/www/certbot:ro
    depends_on: [certbot-renew]
    restart: unless-stopped

  certbot-renew:
    image: certbot/certbot
    entrypoint: "/bin/sh -c 'while :; do certbot renew --webroot -w /var/www/certbot; sleep 12h; done'"
    volumes:
      - /etc/letsencrypt:/etc/letsencrypt:rw
      - /var/www/certbot:/var/www/certbot:rw
    restart: unless-stopped
```

## DNS Prerequisite
Add A record: `gw-platform.zhejianglab.cn -> 10.107.207.103`

## zjlab Requirements
- Public DNS control for zhejianglab.cn (or subdomain delegation)
- Outbound HTTPS to Let's Encrypt (acme-v02.api.letsencrypt.org)
- Inbound 80/443 from internet (currently: only 6001/6002 via cloudflared tunnel)

## Migration Plan
1. R6.77: zjlab team deploys zjlab-nginx with self-signed cert (testing)
2. R6.78: certbot init-certbot.sh runs, Let's Encrypt cert issued
3. R6.79: cloudflared tunnel deprecated (or kept as backup), direct HTTPS works
4. R6.80: HSTS preload list submission (optional, irreversible)

## Why this design
- **Standard pattern**: nginx + certbot is the canonical Let's Encrypt setup
- **Auto-renewal**: 12h loop ensures certs never expire
- **Webroot challenge**: no port 80 conflict (only used for ACME challenge)
- **Existing app unchanged**: gw-frontend still serves HTTP, zjlab-nginx does TLS

## Open questions
1. Domain ownership confirmed? (PXX to verify with zjlab DNS admin)
2. Cloudflared tunnel: remove entirely or keep as backup?
3. HSTS preload: opt-in (R6.80) or skip?

## Estimated effort
- nginx.conf: 1 hour
- init-certbot.sh: 30 minutes
- docker-compose.yml: 30 minutes
- DNS setup (zjlab team): 1-2 days (depends on approval chain)
- Cert issuance + verification: 1 hour
- **Total: 1-2 days (excluding DNS approval)**
