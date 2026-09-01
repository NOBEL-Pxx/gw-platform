# R6.22 — Deployment Policy

> **Status**: Mandatory. Effective 2026-09-01. Supersedes all ad-hoc deploy procedures.
> **Owner**: PXX + Git history (this file is the source of truth).

This policy is the direct response to three documented incidents:

1. **3-week outage** (0826 record): `restart: on-failure` did not restart normally-exited containers.
2. **30h outage** (0901 observation): `gw-mongodb` and `gw-mcp-server` `Exited (0)` since 0830, undetected.
3. **Manual sync spaghetti**: 5+ overlapping scripts (`sync-to-zjlab.py`, `sync_remote_v438.py`, `tunnel.sh`, `start-gw.ps1`, `deploy_v438.py`) doing overlapping things, with manual `docker cp` hot-fixes that became invisible to anyone except the operator who ran them.

## 1. Single Source of Truth: Git

All code, configuration, and documentation lives in the Git repository at `D:\AliCPT\`.

| What | Where | Truth source |
|------|-------|--------------|
| Source files | Tracked in Git | `git log` |
| Version identity | Git tag | `git tag --list` |
| Container config | `docker-compose.yml` (tracked) | `git diff` |
| Secrets | `.env` files (NOT tracked) | `.env` is local-only |
| Historical archives | `version-snapshots/` | **DEPRECATED** — kept for history |

### Version scheme (unified)

**Format**: `v<MAJOR>.<MINOR>[-.<PATCH>]-R<BUILD>`

Examples:
- `v4.56-R6.22` (current target after this R6.22 work)
- `v4.56.0-R6.22` (with patch version)
- `v5.0.0-R7.0` (major version bump)

**Replaces**:
- Legacy system version `v4.55`
- Sub-versioning `R6.18`, `R6.19`, `R6.20`, `R6.21`
- Snapshot timestamps `snapshot_20260722_022048`

**Tooling**:
```bash
# Create a new version
python scripts/ci/version.py tag v4.56-R6.22 -m "R6.22 release"

# List versions
python scripts/ci/version.py list

# Current
python scripts/ci/version.py current

# Rollback
python scripts/ci/version.py rollback v4.55-R6.21
```

## 2. Container Restart Policy

**Required**: `restart: unless-stopped` (was: `on-failure`).

```yaml
services:
    restart: unless-stopped  # R6.22 — was on-failure (does not restart exit 0)
```

### Why

| Policy | Exit code 0 (normal) | Exit code != 0 (crash) | User docker stop |
|--------|---------------------|------------------------|-------------------|
| `no`           | does not restart | does not restart | does not restart |
| `on-failure`   | **does not restart** ← bug | restarts | does not restart |
| `unless-stopped` | restarts | restarts | does not restart |
| `always`       | restarts | restarts | restarts (even explicit stop) |

`on-failure` was the wrong choice for production services. Any process that calls `System.exit(0)` or `os._exit(0)` on graceful shutdown would be left down forever.

### Health checks

All services MUST have `healthcheck:` with `start_period:` to avoid boot-time false positives.

```yaml
healthcheck:
    test: ["CMD", "..."]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s    # R6.22 — required (was optional)
```

## 3. No Hot-Fix `docker cp`

**Banned**: running `docker cp` to push code into a live container.

**Why banned**:
- The container's filesystem diverges from its image.
- A `docker compose up -d --force-recreate` (the standard deploy) **discards** all `docker cp` changes silently.
- Two operators looking at the same container see different code.
- Git history has no record.

**When (rarely) allowed**:
- Emergency debug only.
- Must be followed by a Git commit + image rebuild within **24 hours**.
- Recorded in `.deploy-audit.log`.

**Replacement**: Always rebuild images.

```bash
# WRONG (banned):
docker cp ./fix.py gw-frontend:/app/fix.py

# RIGHT (mandatory):
# 1. Edit code in tracked files
# 2. Commit
git add fix.py && git commit -m "fix: ..."

# 3. Rebuild image
docker compose build gw-frontend

# 4. Force-recreate container (image is the new code)
docker compose up -d --force-recreate --no-deps gw-frontend
```

Or use the unified pipeline:
```bash
bash scripts/ci/deploy.sh all v4.56-R6.22
```

## 4. CI/CD Pipeline

`scripts/ci/deploy.sh` (Bash) and `scripts/ci/deploy.ps1` (PowerShell) replace the 5+ manual scripts:

| Stage | What it does | Replaces |
|-------|--------------|----------|
| `check` | Tree clean + container health | manual inspection |
| `tag`   | Create versioned Git tag | manual v4.55 + R6.21 numbering |
| `build` | Rebuild all images | manual `docker compose build` |
| `test`  | Health check endpoints | manual `curl /actuator/health` |
| `deploy`| Git checkout tag + force-recreate | manual `docker cp` + `--force-recreate` + `patch_pipeline.py` |
| `sync-zh` | Bundle + SCP + remote deploy | manual `sync-to-zjlab.py` + `sync_remote_v438.py` + `tunnel.sh` |
| `rollback` | Previous tag + redeploy | manual `version-snapshot.py restore` |

`.github/workflows/deploy.yml` is the GitHub Actions spec for when this repo is pushed to GitHub (currently local-only, ready for future migration).

## 5. Audit Trail

Every deploy writes to `.deploy-audit.log`:

```
2026-09-01T14:35:22+08:00 | v4.56-R6.22 | DEPLOY    | target=local  | pxx
2026-09-01T15:12:04+08:00 | v4.55-R6.21 | ROLLBACK  | from=v4.56-R6.22 | pxx
2026-09-01T16:01:33+08:00 | v4.56-R6.22 | SKIP_TESTS | pxx
```

**Required**: any time tests are skipped, the audit log MUST show it.

## 6. Deployment Environments

| Environment | Host | Config | Deploy method |
|-------------|------|--------|---------------|
| Local       | Windows 11 (laptop) | `docker-compose.yml` | `bash scripts/ci/deploy.sh all` |
| Zhejiang Lab | `10.107.207.103:6001/6002` | `docker-compose.zjlab.yml` | same script + sync-zh |
| Cloudflare tunnel | `https://wallpaper-asia-clusters-eco.trycloudflare.com` | same as local | manual tunnel start (R6.23 candidate) |

## 7. Disaster Recovery

### Rollback
```bash
# Automatic via the deploy script
python scripts/ci/version.py rollback v4.55-R6.21

# Or manual
git checkout v4.55-R6.21
docker compose up -d --force-recreate --no-deps
```

### Recovery from a wedged container
```bash
# 1. Stop and remove
docker compose stop gw-frontend
docker compose rm -f gw-frontend

# 2. Inspect why it exited
docker logs gw-frontend --tail 100

# 3. Bring it back from a known tag
git checkout v4.55-R6.21
docker compose up -d --force-recreate --no-deps gw-frontend
```

## 8. Anti-Patterns (Forbidden)

These actions will leave the system in an unrecoverable state and are explicitly forbidden:

| ❌ Forbidden | ✅ Correct |
|-------------|-----------|
| `docker cp ./src gw-frontend:/app/src` | `git commit` + `docker compose build` + `force-recreate` |
| Edit files inside a live container | Edit on host, commit, rebuild |
| `restart: on-failure` | `restart: unless-stopped` |
| Manual version numbering (`v4.55 + R6.21`) | Git tag (`v4.55-R6.21`) |
| `version-snapshot.py restore` for new work | `git checkout <tag>` |
| Manual `sync-to-zjlab.py` | `bash scripts/ci/deploy.sh sync-zh` |
| Five scripts doing overlapping things | One `deploy.sh` script |

## 9. Compliance check: before declaring a release complete

```bash
# Must all return true
git status --porcelain | wc -l                 # = 0 (clean)
docker inspect gw-mongodb --format '{{.State.RestartCount}}'  # increasing (restarting on crash)
docker inspect gw-mongodb --format '{{.State.Status}}'        # = running
grep -q 'restart: unless-stopped' docker-compose.yml           # present
ls scripts/ci/version.py                                          # exists
cat .deploy-audit.log | tail -1                                   # last deploy recorded
```

---

*This document is part of `引力波天文数据平台技术详解.md` section v4.54 R6.22.*
*Last updated: 2026-09-01 by PXX*
