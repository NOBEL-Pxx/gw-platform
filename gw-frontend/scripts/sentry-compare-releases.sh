#!/bin/bash
# R6.51: Compare error rate between two Sentry releases + auto-PR comment via gh CLI.
#
# Usage A (standalone):
#   SENTRY_AUTH_TOKEN=xxx SENTRY_ORG=acme SENTRY_PROJECT=gw \
#     bash scripts/sentry-compare-releases.sh RELEASE_A RELEASE_B
#
# Usage B (PR comment via gh CLI):
#   Add to CI after deploy: --post-pr-comment <PR_NUMBER>
#   Requires: gh CLI authenticated + repo PR with given number
#
# Outputs:
#   - markdown table to stdout
#   - exit 1 if regression detected (new_b > new_a)
#   - if --post-pr-comment given, posts to PR via gh pr comment

set -euo pipefail

POST_PR_COMMENT=""
if [ "${1:-}" = "--post-pr-comment" ]; then
    POST_PR_COMMENT="${2:-}"
    shift 2
fi

# R6.52 #2 + R6.53 #2: Slack webhook (parallel to PR comment). URL can come from:
#   1. CLI arg:    --post-slack-webhook <URL>
#   2. Env var:    SLACK_WEBHOOK_URL (set via GitHub Actions secret OR manual export)
# When --post-slack-webhook is passed but neither URL arg nor env is set, exit with
# a clear error so the operator doesn't silently get "no Slack notification fired".
SLACK_WEBHOOK_URL=""
if [ "${1:-}" = "--post-slack-webhook" ]; then
    # Try CLI arg first, fall back to env
    SLACK_WEBHOOK_URL="${2:-}"
    if [ -z "$SLACK_WEBHOOK_URL" ] && [ -n "${SLACK_WEBHOOK_URL_ENV:-}" ]; then
        SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL_ENV"
    fi
    if [ -z "$SLACK_WEBHOOK_URL" ]; then
        echo "::error::--post-slack-webhook passed but no URL provided and SLACK_WEBHOOK_URL env is unset" >&2
        echo "Usage: $0 RELEASE_A RELEASE_B --post-slack-webhook <URL>" >&2
        echo "   or: export SLACK_WEBHOOK_URL=https://hooks.slack.com/..." >&2
        exit 4
    fi
    shift 2
fi
# Capture env var (independent of flag path)
SLACK_WEBHOOK_URL_ENV="${SLACK_WEBHOOK_URL_ENV:-${SLACK_WEBHOOK_URL:-}}"
if [ -z "$SLACK_WEBHOOK_URL" ] && [ -n "$SLACK_WEBHOOK_URL_ENV" ]; then
    SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL_ENV"
fi

if [ $# -lt 2 ]; then
    echo "Usage: $0 RELEASE_A RELEASE_B [--post-pr-comment <PR_NUM>]" >&2
    echo "Env: SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT, GITHUB_REPOSITORY" >&2
    exit 1
fi

RELEASE_A="$1"
RELEASE_B="$2"
API="https://sentry.io/api/0/projects/${SENTRY_ORG}/${SENTRY_PROJECT}/releases/"

if [ -z "${SENTRY_AUTH_TOKEN:-}" ] || [ -z "${SENTRY_ORG:-}" ] || [ -z "${SENTRY_PROJECT:-}" ]; then
    echo "ERROR: Missing SENTRY_AUTH_TOKEN / SENTRY_ORG / SENTRY_PROJECT env vars" >&2
    exit 2
fi

fetch_release() {
    local rel="$1"
    local resp
    resp=$(curl -sf -L \
        -H "Authorization: Bearer ${SENTRY_AUTH_TOKEN}" \
        "${API}${rel}/")
    echo "$resp"
}

stats_for_release() {
    local rel="$1"
    local data
    data=$(fetch_release "$rel")
    local new_issues resolved_issues last_event
    new_issues=$(echo "$data" | grep -oE '"newGroups":[0-9]+' | grep -oE '[0-9]+' || echo "0")
    resolved_issues=$(echo "$data" | grep -oE '"resolvedGroups":[0-9]+' | grep -oE '[0-9]+' || echo "0")
    last_event=$(echo "$data" | grep -oE '"lastEvent":"[^"]*"' | cut -d\" -f4 || echo "")
    echo "${new_issues}|${resolved_issues}|${last_event}"
}

read -r new_a res_a last_a <<<"$(stats_for_release "${RELEASE_A}" | tr '|' ' ')"
read -r new_b res_b last_b <<<"$(stats_for_release "${RELEASE_B}" | tr '|' ' ')"

# Generate markdown body
MD_BODY=$(cat <<EOF
## Sentry Release Comparison

| Release | New issues | Resolved | Last event |
|---------|-----------:|---------:|------------|
| \`${RELEASE_A}\` | ${new_a:-N/A} | ${res_a:-N/A} | ${last_a:-N/A} |
| \`${RELEASE_B}\` | ${new_b:-N/A} | ${res_b:-N/A} | ${last_b:-N/A} |

**Regression check**: if \`${RELEASE_B}\` new issues > \`${RELEASE_A}\` new issues, investigate.
EOF
)

# Echo to stdout
echo "$MD_BODY"

# Post PR comment if requested
if [ -n "$POST_PR_COMMENT" ]; then
    if ! command -v gh >/dev/null 2>&1; then
        echo "::warning::gh CLI not available, skipping PR comment" >&2
    elif [ -z "${GITHUB_REPOSITORY:-}" ]; then
        echo "::warning::GITHUB_REPOSITORY not set, skipping PR comment" >&2
    else
        echo "::notice::Posting comparison to PR #${POST_PR_COMMENT}"
        echo "$MD_BODY" | gh pr comment "$POST_PR_COMMENT" --repo "$GITHUB_REPOSITORY" --body-file - || {
            echo "::warning::Failed to post PR comment" >&2
        }
    fi
fi

# R6.52 #2 + R6.53 #2: Post Slack notification (parallel to PR comment, best-effort).
# R6.53 #2: --silent-off flag lets CI skip Slack post when SLACK_WEBHOOK_URL is intentionally unset
# (vs. detecting the unset case as a config error).
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    SLACK_TEXT="*:warning: Sentry regression detected on \`${RELEASE_B}\` (new: ${new_b:-N/A} vs ${RELEASE_A}: ${new_a:-N/A})*"
    if [ -z "${new_a:-}" ] || [ -z "${new_b:-}" ] || [ "${new_b:-0}" -le "${new_a:-0}" ]; then
        SLACK_TEXT=":white_check_mark: Sentry release \`${RELEASE_B}\` looks clean vs \`${RELEASE_A}\` (new: ${new_b:-N/A}, resolved: ${res_b:-N/A})"
    fi
    # R6.53 #2: use --data @- with stdin for safer JSON escaping (PXX 9.4 lesson)
    SLACK_PAYLOAD=$(printf '{"text": "%s"}' "$SLACK_TEXT")
    echo "::notice::Posting Slack webhook to ${SLACK_WEBHOOK_URL:0:40}..."
    if ! echo "$SLACK_PAYLOAD" | curl -sf -X POST "$SLACK_WEBHOOK_URL" -H "Content-Type: application/json" --data @- >/dev/null 2>&1; then
        echo "::warning::Failed to post Slack webhook (continuing)" >&2
        echo "::warning::Webhook URL: ${SLACK_WEBHOOK_URL:0:60}..." >&2
    else
        echo "::notice::Posted Slack webhook notification (ok)"
    fi
elif [ -n "${SLACK_WEBHOOK_URL_ENV:-}" ]; then
    # Env was set but flag not passed — only emit notice, don't post
    echo "::notice::SLACK_WEBHOOK_URL is set in env but --post-slack-webhook flag not passed; skipping Slack post"
fi

# Exit non-zero if regression detected (best-effort)
if [ -n "$new_a" ] && [ -n "$new_b" ] && [ "$new_b" -gt "$new_a" ]; then
    echo "::warning::New issues increased from ${new_a} to ${new_b}" >&2
    exit 3
fi

exit 0
