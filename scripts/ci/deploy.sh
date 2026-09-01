#!/usr/bin/env bash
# R6.22 — Unified CI/CD pipeline (Bash version, used on Linux servers and GitHub Actions)
# Usage:  bash scripts/ci/deploy.sh <stage> [tag] [target]
#   stage:  check | tag | build | test | deploy | sync-zh | all | rollback
#   target: local | zjlab   (default: local)
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

stage="${1:-check}"
tag="${2:-}"
target="${3:-local}"
skip_tests="${SKIP_TESTS:-0}"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
cyan()   { printf "\033[36m═══ %s ═══\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

assert_clean_tree() {
    if [ -n "$(git status --porcelain)" ] && [ "${FORCE:-0}" != "1" ]; then
        red "Working tree is dirty. Commit/stash first, or set FORCE=1."
        exit 1
    fi
}

assert_tag_format() {
    if ! [[ "$1" =~ ^v[0-9]+\.[0-9]+(\.[0-9]+)?-R[0-9]+\.[0-9]+$ ]]; then
        red "Bad tag format: $1. Expected: v4.56-R6.22"
        exit 1
    fi
}

# ── Stage: check ─────────────────────────────────────────────────────
if [ "$stage" = "check" ] || [ "$stage" = "all" ]; then
    cyan "[1/7] Pre-flight check"
    assert_clean_tree
    echo "  HEAD:   $(git rev-parse --short HEAD)"
    echo "  Branch: $(git rev-parse --abbrev-ref HEAD)"
    echo ""
    echo "  Containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}"
fi

# ── Stage: tag ───────────────────────────────────────────────────────
if [ "$stage" = "tag" ] || [ "$stage" = "all" ]; then
    if [ -z "$tag" ]; then
        last="$(git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0-R0.0')"
        echo "Last tag: $last"
        read -rp "Enter new tag (v4.56-R6.22): " tag
    fi
    assert_tag_format "$tag"

    cyan "[2/7] Create versioned Git tag: $tag"
    assert_clean_tree

    msg="R6.22 version tag — $tag

Single source of truth for version identity.
Legacy identifiers deprecated."
    git tag -a "$tag" -m "$msg"
    echo "  ✓ Tagged: $tag"
fi

# ── Stage: build ─────────────────────────────────────────────────────
if [ "$stage" = "build" ] || [ "$stage" = "all" ]; then
    cyan "[3/7] Build Docker images"
    docker compose build gw-frontend gw-backend gw-pipeline gw-mcp-server
fi

# ── Stage: test ──────────────────────────────────────────────────────
if [ "$stage" = "test" ] || [ "$stage" = "all" ]; then
    if [ "$skip_tests" = "1" ]; then
        yellow "Skip-tests mode — recorded in audit log"
        printf "%s | %s | SKIP_TESTS | %s\n" "$(date -Iseconds)" "$tag" "$(whoami)" >> "$REPO_ROOT/.deploy-audit.log"
    else
        cyan "[4/7] Smoke tests"
        curl -sf http://localhost:8093/actuator/health >/dev/null || { red "Backend health failed"; exit 2; }
        curl -sf http://localhost:6001/ >/dev/null || { red "Frontend health failed"; exit 2; }
        docker exec gw-mongodb mongosh --quiet --eval "db.adminCommand('ping')" || { red "MongoDB ping failed"; exit 2; }
        echo "  ✓ All services healthy"
    fi
fi

# ── Stage: deploy ────────────────────────────────────────────────────
if [ "$stage" = "deploy" ] || [ "$stage" = "all" ]; then
    cyan "[5/7] Deploy (force-recreate, no hot-fix docker cp)"
    if [ -z "$tag" ]; then red "deploy stage requires tag"; exit 1; fi
    assert_tag_format "$tag"

    git checkout "$tag"
    docker compose up -d --force-recreate --no-deps
    sleep 30
    docker ps --format "table {{.Names}}\t{{.Status}}"
    printf "%s | %s | DEPLOY | target=%s | %s\n" "$(date -Iseconds)" "$tag" "$target" "$(whoami)" >> "$REPO_ROOT/.deploy-audit.log"
fi

# ── Stage: sync-zh ──────────────────────────────────────────────────
if [ "$stage" = "sync-zh" ] || [ "$stage" = "all" ]; then
    cyan "[6/7] Sync to Zhejiang Lab"
    if [ -z "${ZJLAB_HOST:-}" ]; then
        yellow "ZJLAB_HOST not set — building bundle only"
        git archive --format=zip --output="deploy_${tag}.zip" HEAD
        echo "  Bundle: deploy_${tag}.zip"
    else
        git archive --format=zip --output="/tmp/deploy_${tag}.zip" HEAD
        scp "/tmp/deploy_${tag}.zip" "${ZJLAB_USER:-amax}@${ZJLAB_HOST}:/tmp/"
        ssh "${ZJLAB_USER:-amax}@${ZJLAB_HOST}" "cd /tmp && unzip -o deploy_${tag}.zip -d gw-${tag} && bash gw-${tag}/scripts/ci/remote-deploy.sh $tag"
    fi
fi

# ── Stage: rollback ──────────────────────────────────────────────────
if [ "$stage" = "rollback" ]; then
    cyan "[7/7] Rollback to previous tag"
    current="$(git describe --tags --abbrev=0 2>/dev/null || echo none)"
    previous="$(git tag --sort=-version:refname | sed -n 2p)"
    if [ -z "$previous" ]; then red "No previous tag"; exit 1; fi

    echo "  Current: $current → Rolling back to: $previous"
    git checkout "$previous"
    docker compose up -d --force-recreate --no-deps
    sleep 30
    docker ps --format "table {{.Names}}\t{{.Status}}"
    printf "%s | %s | ROLLBACK | from=%s | %s\n" "$(date -Iseconds)" "$previous" "$current" "$(whoami)" >> "$REPO_ROOT/.deploy-audit.log"
fi

green "Stage '$stage' complete"
