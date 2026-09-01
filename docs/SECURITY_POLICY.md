# Security Policy (R6.25)

Consolidates all security-related settings, flags the v4.54 MongoDB no-auth
regression as fixed, and locks the rotate-keys / validate-compose workflows.

## v4.54 Security Regression — RESOLVED in R6.25

In v4.54 (commit on remote backend JAR), MongoDB authentication was disabled
by commenting out the username/password source to fix a cross-environment
inconsistency. This was a **P0 security regression**:

- Remote MongoDB was reachable without credentials.
- An attacker with network access could read/write/delete all error-detail
  records, comments, favorites — anything the `gw-app` user could touch.

**Fix in R6.25** (see [引カ波天文データプラットフォーム技術詳解 v4.58 + R6.24 doc](../0826%E7%BB%84%E4%BC%9A/%E5%BC%95%E5%8A%9B%E6%B3%A2%E5%A4%A9%E6%96%87%E6%95%B0%E6%8D%AE%E5%B9%B3%E5%8F%B0%E6%8A%80%E6%9C%AF%E8%AF%A6%E8%A7%A3.md)):

- `docker-compose.yml` uses `${MONGO_APP_PASSWORD}` env var injection
  (re-enabled; v4.54 had commented it out).
- Backend `SPRING_DATA_MONGODB_USERNAME/PASSWORD/AUTHENTICATION_DATABASE`
  restored.
- v4.54 changelog row flagged with 🔴 + cross-reference to this fix.

## Current Security Posture

### Network Isolation

Two bridge networks, segmented by data tier (R6.25 verified):

| Network | Services | External Exposure |
|---------|----------|-------------------|
| `gw-net` | frontend, backend, pipeline, mcp-server, firefly | frontend 6001/6002 only (proxied by nginx) |
| `gw-db`  | mongodb, elasticsearch, backend | none in prod (ports `[]`) |

Pipeline/MCP/Frontend/Firefly **cannot** reach MongoDB or Elasticsearch
directly — they must go through `gw-backend`, which is the only service
on both networks.

### Authentication

| Service | Auth | Credentials |
|---------|------|-------------|
| MongoDB | YES (SCRAM-SHA-256) | `${MONGO_ROOT_PASSWORD}` for admin, `${MONGO_APP_PASSWORD}` for gw-app |
| Elasticsearch | YES (xpack.security) | `${ES_PASSWORD}` (built-in `elastic` user) |
| Backend API | YES (JWT) | `${JWT_SECRET}` (HS256, 64-char hex) |
| Frontend → Backend | YES (JWT in cookie/header) | same `${JWT_SECRET}` |
| LLM (DeepSeek) | YES (API key) | `${DEEPSEEK_API_KEY}` |
| Image Cutout (external) | YES (basic auth) | `${IMAGECUTOUT_USERNAME}` / `${IMAGECUTOUT_PASSWORD}` |

### Production Lockdown

Production deployment MUST use:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

What `docker-compose.prod.yml` enforces:

- MongoDB: `ports: []` — no host exposure
- Elasticsearch: `ports: []` — no host exposure
- Backend: `ports: []` — only via nginx proxy
- Pipeline/MCP/Firefly: `ports: []` — only via nginx proxy
- Frontend: keeps 6001/6002 — the ONLY externally-accessible ports
- `SKIP_SEED_DATA=true` — no demo data inserted
- Rate limit: 30 req/min (dev is 120 req/min)
- Backend `SPRING_PROFILES_ACTIVE=prod` — picks up stricter settings

### Secret Hygiene

- `.env` is `.gitignore`d — never commit real secrets.
- `.env.example` and `.env.template` are committed; they only contain
  placeholders.
- API keys appearing in [documentation](../0826组会/引力波天文数据平台技术详解.md)
  are redacted to `<REDACTED — 详见 .env>` even if they were already
  partially masked.
- See `scripts/ci/verify-compose-security.sh` for CI-time enforcement.

## Secret Rotation Policy

| Secret | Rotation Frequency | Procedure |
|--------|-------------------|-----------|
| `DEEPSEEK_API_KEY` | Every 90 days OR on suspected leak | Generate new key at DeepSeek dashboard → update `.env` → `docker compose up -d --force-recreate --no-deps gw-backend gw-pipeline gw-mcp-server` → smoke test `/api/llm/status` |
| `MONGO_ROOT_PASSWORD` | Annually | Update `.env` → `docker compose down mongodb` → `rm -rf docker-data/mongodb-data` (DESTRUCTIVE) → `docker compose up -d` → re-run `init_mongo.js` |
| `MONGO_APP_PASSWORD` | Annually | Update `.env` → `docker compose restart mongodb` → update backend env via recreate |
| `ES_PASSWORD` | Annually | Update `.env` → `docker compose restart elasticsearch` → update backend env via recreate |
| `JWT_SECRET` | On suspected leak only | Update `.env` → restart backend → **all existing JWTs invalidated** (users must re-login) |

**WARNING**: MongoDB root password rotation is DESTRUCTIVE (deletes data dir).
Always take a backup first: `mongodump --uri="mongodb://admin:${MONGO_ROOT_PASSWORD}@localhost:27017/gravitationalwave?authSource=admin"`.

## CI / Pre-deployment Validation

Run before any production deploy:

```bash
bash scripts/ci/verify-compose-security.sh
```

Checks:

1. `grep -r "xpack.security.enabled=false" docker-compose*.yml` → 0 matches
   (xpack must be ON in both dev and prod).
2. `grep -r "SPRING_DATA_MONGODB_USERNAME" docker-compose*.yml` → 1 match
   (MongoDB auth must be wired).
3. `grep -r "ELASTIC_PASSWORD=" docker-compose*.yml` → 1 match
   (ES password must be env-injected, not hardcoded).
4. `docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q`
   (compose files parse cleanly when combined).
5. `grep -r "sk-[a-zA-Z0-9]{20}" docs/` → 0 matches (no API key leaks).

## Incident Response

If a secret is suspected leaked:

1. **Rotate immediately** (don't wait for scheduled rotation).
2. **Audit access logs** (`docker logs gw-mongodb` for auth failures;
   ES audit log at `/usr/share/elasticsearch/logs/` if enabled).
3. **Document incident** in `docs/incidents/YYYY-MM-DD-secret-leak.md`.
4. **Update R6.x.x record** in
   [引力波天文数据平台技术详解.md](../0826组会/引力波天文数据平台技术详解.md).

## Out of Scope (Not Addressed in R6.25)

- TLS certificates for ES (commented out in `docker-compose.prod.yml`).
  Follow `docs/es-auth-config-v4.16.md` for one-click setup.
- Network policies beyond docker networks (no k8s yet).
- Audit logging in MongoDB (currently logs only via container stdout).
- Backup automation (manual `mongodump` only).
