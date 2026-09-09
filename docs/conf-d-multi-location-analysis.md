# conf.d-bindmount multi-location analysis (R6.99 #4)

**Created**: 2026-09-10
**Status**: PROPOSAL (not yet implemented; awaiting USER auth)

## Current state

gw-platform nginx config lives in 4 separate directories:

| Local dir | Build-time vs Runtime | Container path | Purpose | Synced by |
|---|---|---|---|---|
| `gw-frontend/nginx.conf` | Build (COPY) | `/etc/nginx/nginx.conf` | Master config | `_sync_frontend_infra()` |
| `gw-frontend/nginx-includes/` | Build (COPY) | `/etc/nginx/includes/` | Shared http-level includes (gzip, mime, security headers) | Dockerfile only |
| `gw-frontend/nginx-shared/` | Build (COPY) | `/etc/nginx/shared/` | Shared location/server fragments | Dockerfile only |
| `gw-frontend/nginx-conf.d/` | Build (COPY) + Runtime bind-mount | `/etc/nginx/conf.d/` | Per-app server blocks (default.conf + envsubst templates) | `_sync_frontend_nginx_confd()` |
| `gw-frontend/nginx-conf.d-bindmount/` | Runtime bind-mount ONLY | `/etc/nginx/conf.d/bindmount/` | User-controlled static *.conf (smoketest, backend-health) | `_sync_frontend_nginx_confd_bindmount()` (R6.95) |

**Count**: 5 distinct dirs (incl. nginx.conf itself).

## The "multi-location" problem

Three pain points from having 5 separate dirs:

1. **Discovery friction**: New engineer must read 5 different sync functions to figure out where to put a config file. The "obvious" answer (drop in nginx-conf.d/) doesn't work for static *.conf (envsubst conflicts with templates).

2. **Sync coverage gaps**: nginx-includes/ and nginx-shared/ are **build-time only** — they get baked into the image at `docker compose build gw-frontend`. Adding a new shared header requires a full image rebuild (~minutes), not just a sync + reload (~1s).

3. **No single source of truth**: Which files are runtime-modifiable vs which require rebuild is scattered across:
   - Dockerfile (COPY lines)
   - docker-compose.yml (volume declarations)
   - sync-to-zjlab.py (which sync function copies what)

## Why it grew this way

The split was *gradual*, not designed:

- R6.66: 4 dirs baked at build (nginx.conf + nginx-conf.d/ + nginx-includes/ + nginx-shared/)
- R6.78u cascade: read_only: true broke runtime mutation of nginx-conf.d/
- R6.89b: bind-mounted nginx-conf.d/ for runtime mods (closed cascade entry #5)
- R6.95: introduced nginx-conf.d-bindmount/ to escape envsubst conflict (static *.conf that don't shadow templates)

Each fix added a dir rather than consolidating.

## Proposal (R6.99 #4 not yet implemented)

### Goal

ONE bind-mount pattern for ALL runtime-modifiable nginx config. No build-time COPY for files that need to change post-deploy.

### Target structure

| Local dir | Mode | Container path | Purpose |
|---|---|---|---|
| `gw-frontend/nginx.conf` | Build | `/etc/nginx/nginx.conf` | Master config (rare change) |
| `gw-frontend/nginx-conf.d/runtime/` | **Bind-mount** | `/etc/nginx/conf.d/runtime/` | All runtime-modifiable *.conf (replaces nginx-conf.d-bindmount/) |
| `gw-frontend/nginx-conf.d/templates/` | **Bind-mount** | `/etc/nginx/conf.d/templates/` | envsubst templates (env vars) |
| `gw-frontend/nginx-conf.d/static/` | **Bind-mount** | `/etc/nginx/conf.d/static/` | Static *.conf (no envsubst, loaded BEFORE templates/) |
| `gw-frontend/nginx-conf.d-baked/` | Build (COPY) | `/etc/nginx/conf.d-baked/` | Image-default *.conf (default.conf, mime-types, etc.) |

### Migration steps

1. Create new dirs locally: `runtime/`, `templates/`, `static/`, `baked/`
2. Move existing files to new homes:
   - `nginx-conf.d/default.conf` → `nginx-conf.d-baked/`
   - `nginx-conf.d/templates/*.template` → `nginx-conf.d-baked/templates/` (build-time envsubst) — OR keep as bind-mount if we want runtime envsubst
   - `nginx-conf.d-bindmount/*.conf` → `nginx-conf.d/runtime/` OR `static/` (depending on envsubst needs)
   - `nginx-includes/*` → either bake (if truly static) or move to `static/`
   - `nginx-shared/*` → either bake (if truly static) or move to `static/`
3. Update Dockerfile COPY lines for `nginx-conf.d-baked/`
4. Update docker-compose.yml bind-mount declarations
5. Update sync-to-zjlab.py:
   - `_sync_frontend_nginx_confd()` → split into `_sync_runtime_confd()` + `_sync_static_confd()`
   - Or consolidate into ONE `_sync_confd_subdirs()` helper
6. Update nginx.conf include order:
   ```
   include /etc/nginx/conf.d/static/*.conf;   # user static, shadow defaults
   include /etc/nginx/conf.d/runtime/*.conf;  # user runtime
   include /etc/nginx/conf.d-baked/*.conf;    # image defaults
   include /etc/nginx/conf.d/templates/*.conf; # envsubst output
   ```
7. Test + deploy (one commit per step to make rollback easy)

### Risks

| Risk | Mitigation |
|---|---|
| Lost envsubst templates during migration | Keep old dirs as `.bak` for 1 deploy cycle, then Recycle Bin |
| Server_name routing breaks (nginx picks first match) | Test each *.conf in isolation before deleting old location |
| docker-compose bind-mount path typo → silent fail | Add `docker exec gw-frontend nginx -t` to zsmoke.py (already there) |
| 3rd-party integration breaks (e.g., CSP headers in nginx-includes) | Verify all CSP/header includes still load |

### Out of scope (deliberately)

- nginx-includes/ gzip + http-common.conf — these are static defaults that rarely change. Keep build-time COPY. Document as "static default".
- nginx-shared/ — same, static defaults.

### Why this is R6.99 #4, not implemented today

- **Scope creep risk**: 5-dir migration touches Dockerfile, compose, nginx.conf, sync-to-zjlab.py, all 4 dir contents. 10+ files, 100+ lines. Wrong batch to do mid-R6.99.
- **USER auth per parallel-review-after-batch**: multi-file commit batch needs 3-perspective review BEFORE push. This proposal deserves its own review cycle.
- **R6.98c iron rule** (prefer bind-mount over new sync modes) ALREADY APPLIED for bindmount/ — proposal extends the same principle uniformly.
- **Low urgency**: Current 5-dir setup works. R6.95 bindmount/ pattern is sufficient for the 2 *.conf files we actually have.

## Recommendation

**DEFER to R6.100+** unless we add a 3rd bind-mount *.conf file. At that point, the cognitive overhead of 3+ scattered dirs will exceed the migration cost.

## Tracking

- Proposal doc: `D:/AliCPT/docs/conf-d-multi-location-analysis.md` (this file)
- Iron rule reference: `R6.98c (prefer bind-mount over new sync modes)` — already in `r698-summary.md`
- Migration script: TBD (R6.100)
- Verification: `python D:/AliCPT/scripts/zsmoke.py` (nginx-config-test check) catches most regressions

## Cross-references

- [r698-summary.md](C:/Users/28610/.claude/projects/C--Users-28610/memory/r698-summary.md) — R6.98 zkb migration + R6.98c iron rule
- [r695-summary.md](C:/Users/28610/.claude/projects/C--Users-28610/memory/r695-summary.md) — R6.95 created bindmount/ pattern
- [STATE_SNAPSHOT.md §45.85](E:/常用文件/科研项目/中科院国家天文台__中国科学院大学生创新实践训练计划/组会/0902组会/Software_Infor_File/STATE_SNAPSHOT.md) — R6.99 backlog state