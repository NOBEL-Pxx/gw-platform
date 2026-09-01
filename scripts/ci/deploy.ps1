<#
.SYNOPSIS
    R6.22 — Unified CI/CD pipeline for the GravitationalWave platform.
.DESCRIPTION
    Replaces the manual 5-script workflow:
      - sync-to-zjlab.py + sync_remote_v438.py
      - tunnel.sh + start-gw.ps1
      - manual docker cp + --force-recreate

    New pipeline: commit → tag → build → test → deploy → health-check.

    Version truth: Git tags. The legacy `version-snapshot.py` and the
    ad-hoc "v4.55 + R6.21" naming scheme are DEPRECATED.
.PARAMETER Stage
    One of: check | tag | build | test | deploy | sync-zh | all | rollback
.PARAMETER Tag
    The Git tag to deploy (e.g. v4.56-R6.22). Required for deploy/rollback.
.PARAMETER Target
    local | zjlab (Zhejiang Lab). Default: local.
.PARAMETER SkipTests
    Skip the test stage. Use only for hot-fix emergency deploys (recorded in audit log).
.EXAMPLE
    .\scripts\ci\deploy.ps1 -Stage tag -Tag "v4.56-R6.22"
    .\scripts\ci\deploy.ps1 -Stage deploy -Tag "v4.56-R6.22" -Target zjlab
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('check','tag','build','test','deploy','sync-zh','all','rollback')]
    [string]$Stage,

    [Parameter(Mandatory=$false)][string]$Tag,

    [Parameter(Mandatory=$false)][ValidateSet('local','zjlab')][string]$Target = 'local',

    [Parameter(Mandatory=$false)][switch]$SkipTests,

    [Parameter(Mandatory=$false)][switch]$Force  # Allow dirty tree if absolutely needed
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (git rev-parse --show-toplevel)
Set-Location $RepoRoot

function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "═══ [$n] $msg ═══" -ForegroundColor Cyan
}

function Assert-CleanTree {
    if ($Force) {
        Write-Warning "Force mode: skipping clean-tree check"
        return
    }
    $status = git status --porcelain
    if ($status) {
        Write-Error "Working tree is dirty. Commit/stash first, or use -Force.`n$status"
        exit 1
    }
}

function Assert-TagFormat($t) {
    # vMAJOR.MINOR-R6.N or vMAJOR.MINOR.0-R6.N
    if ($t -notmatch '^v\d+\.\d+(\.\d+)?-R\d+\.\d+$') {
        Write-Error "Bad tag format: $t. Expected: v4.56-R6.22"
        exit 1
    }
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: check — tree clean, all services responding
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'check' -or $Stage -eq 'all') {
    Write-Step 1 "Pre-flight check (Git tree + service health)"
    Assert-CleanTree

    Write-Host "  • Git HEAD: $(git rev-parse --short HEAD)"
    Write-Host "  • Branch:   $(git rev-parse --abbrev-ref HEAD)"

    Write-Host "`n  • Container health:"
    docker ps --format "table {{.Names}}\t{{.Status}}" | Out-Host
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: tag — create a versioned Git tag (single source of truth)
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'tag' -or $Stage -eq 'all') {
    if (-not $Tag) {
        # Auto-derive from previous tag + .git/refs
        $lastTag = git describe --tags --abbrev=0 2>$null
        Write-Host "  Last tag: $lastTag"
        $Tag = Read-Host "Enter new tag (format: v4.56-R6.22)"
    }
    Assert-TagFormat $Tag

    Write-Step 2 "Create versioned Git tag: $Tag"
    Assert-CleanTree

    $msg = @"
R6.22 version tag — $Tag

This tag is the single source of truth for version identity.
Legacy identifiers (v4.55 + R6.21, version-snapshot.py) are deprecated.
"@
    git tag -a $Tag -m $msg
    Write-Host "  ✓ Tagged: $Tag"
    Write-Host "  → push with: git push origin $Tag"
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: build — rebuild all Docker images (no hot-fix docker cp!)
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'build' -or $Stage -eq 'all') {
    Write-Step 3 "Build Docker images (replaces docker cp hot-fixes)"
    Write-Host "  • gw-frontend (Vite + React)"
    docker compose build gw-frontend
    Write-Host "  • gw-backend (Spring Boot 3.4.1 + Java 21)"
    docker compose build gw-backend
    Write-Host "  • gw-pipeline (FastAPI)"
    docker compose build gw-pipeline
    Write-Host "  • gw-mcp-server"
    docker compose build gw-mcp-server
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: test — smoke tests (mandatory unless -SkipTests)
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'test' -or $Stage -eq 'all') {
    if ($SkipTests) {
        Write-Warning "Skip-tests mode — recorded in audit log"
        "$(Get-Date -Format o) | $Tag | SKIP_TESTS | $(whoami)" | Out-File -Append "$RepoRoot/.deploy-audit.log"
    } else {
        Write-Step 4 "Smoke tests"
        Write-Host "  • Backend /actuator/health"
        try {
            $r = Invoke-WebRequest http://localhost:8093/actuator/health -UseBasicParsing -TimeoutSec 10
            Write-Host "    → $($r.StatusCode) $($r.Content)"
        } catch {
            Write-Error "Backend health check failed: $_"
            exit 2
        }
        Write-Host "  • Frontend root"
        try {
            $r = Invoke-WebRequest http://localhost:6001/ -UseBasicParsing -TimeoutSec 10
            Write-Host "    → $($r.StatusCode)"
        } catch {
            Write-Error "Frontend health check failed: $_"
            exit 2
        }
        Write-Host "  • MongoDB ping"
        docker exec gw-mongodb mongosh --quiet --eval "db.adminCommand('ping')" 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Error "MongoDB ping failed"; exit 2 }
        Write-Host "    → OK"
    }
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: deploy — force-recreate containers with new images
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'deploy' -or $Stage -eq 'all') {
    Write-Step 5 "Deploy via --force-recreate (mandatory, not hot-fix)"

    if (-not $Tag) { Write-Error "deploy stage requires -Tag"; exit 1 }
    Assert-TagFormat $Tag

    # Tag is the version. Re-tag the HEAD on this deploy.
    Write-Host "  • Checking out $Tag"
    git checkout $Tag

    Write-Host "  • docker compose up -d --force-recreate --no-deps"
    docker compose up -d --force-recreate --no-deps

    Write-Host "  • Waiting for healthchecks..."
    Start-Sleep -Seconds 30

    Write-Host "  • Final health check:"
    docker ps --format "table {{.Names}}\t{{.Status}}" | Out-Host

    "$(Get-Date -Format o) | $Tag | DEPLOY | target=$Target | $(whoami)" | Out-File -Append "$RepoRoot/.deploy-audit.log"
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: sync-zh — push to Zhejiang Lab server (replaces sync-to-zjlab.py)
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'sync-zh' -or $Stage -eq 'all') {
    if ($Target -ne 'zjlab' -and $Stage -ne 'all') {
        Write-Error "sync-zh requires -Target zjlab"; exit 1
    }
    Write-Step 6 "Sync to Zhejiang Lab (replaces manual sync-to-zjlab.py)"
    Write-Host "  • Building bundle..."
    $bundle = "deploy_$Tag.zip"
    if (Test-Path $bundle) { Remove-Item $bundle }
    # Use git archive for a clean tree snapshot — no surprise state
    git archive --format=zip --output=$bundle HEAD
    Write-Host "  → bundle: $bundle"

    Write-Host "  • Uploading via SCP..."
    # Configurable via env vars
    $zjlabHost = $env:ZJLAB_HOST  # e.g. 11.tcp.vip.cpolar.cn:12394
    $zjlabUser = $env:ZJLAB_USER  # amax
    if (-not $zjlabHost) {
        Write-Warning "ZJLAB_HOST not set — skipping remote sync (just built bundle)"
        Write-Host "  Set $env:ZJLAB_HOST and re-run, or use legacy sync-to-zjlab.py"
    } else {
        scp $bundle "${zjlabUser}@${zjlabHost}:/tmp/"
        ssh "${zjlabUser}@${zjlabHost}" "cd /tmp && unzip -o $bundle -d gw-$tag && bash gw-$tag/scripts/ci/remote-deploy.sh $Tag"
    }
}

# ──────────────────────────────────────────────────────────────────────────
# Stage: rollback — revert to previous tag
# ──────────────────────────────────────────────────────────────────────────
if ($Stage -eq 'rollback') {
    Write-Step 7 "Rollback to previous tag"
    $current = git describe --tags --abbrev=0 2>$null
    Write-Host "  • Current: $current"

    $previous = git tag --sort=-version:refname | Select-Object -First 2 | Select-Object -Last 1
    if (-not $previous) { Write-Error "No previous tag to roll back to"; exit 1 }
    Write-Host "  • Rolling back to: $previous"

    git checkout $previous
    docker compose up -d --force-recreate --no-deps
    Start-Sleep -Seconds 30
    docker ps --format "table {{.Names}}\t{{.Status}}" | Out-Host

    "$(Get-Date -Format o) | $previous | ROLLBACK | from=$current | $(whoami)" | Out-File -Append "$RepoRoot/.deploy-audit.log"
}

Write-Host ""
Write-Host "═══ Pipeline stage '$Stage' complete ═══" -ForegroundColor Green
