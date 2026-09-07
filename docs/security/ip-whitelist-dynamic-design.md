# R6.76 IP Whitelist Dynamic CIDR Loading — Design Doc

**Status**: R6.76 design only. R6.77+ implementation requires zjlab metadata API deployment.

## Problem

R6.73 #2 hard-coded Docker bridge subnets (172.16.0.0/12 + 10.0.0.0/8) into
`gw-pipeline/src/pipeline/middleware/ip_whitelist.py`. When zjlab adds a new
subnet (e.g., a new gw-inference service in 10.20.0.0/16), the whitelist
must be updated + gw-pipeline container restarted.

## Solution

Add a dynamic CIDR loader that polls a zjlab metadata API at startup and
periodically (every 5 min). Falls back to hard-coded defaults if API is
unreachable.

## zjlab Metadata API Contract

**Endpoint**: `GET http://zjlab-metadata.ops.local:8080/v1/network/cidrs`
**Auth**: Bearer token (shared secret in `GW_METADATA_API_TOKEN` env)
**Response**:
```json
{
  "version": 7,
  "updated_at": "2026-09-08T01:50:00Z",
  "default_cidrs": ["172.16.0.0/12", "10.0.0.0/8"],
  "admin_cidrs": ["10.0.0.5/32"],
  "service_cidrs": {
    "gw-pipeline": ["172.18.0.0/16"],
    "gw-backend": ["172.18.0.0/16"],
    "gw-frontend": ["172.18.0.0/16"],
    "gw-inference": ["10.20.0.0/16"]
  }
}
```

**Error handling**:
- 200 OK → use response, update local cache
- 4xx → log warning, use cached version (TTL 1h, then revert to defaults)
- 5xx → log error, retry with exponential backoff (max 3 attempts, then use defaults)
- timeout (5s) → use defaults
- network unreachable → use defaults + emit metric `ip_whitelist_api_unreachable_total`

## Implementation Plan (R6.77+)

### Step 1: middleware refactor
`gw-pipeline/src/pipeline/middleware/ip_whitelist.py`:
- Add `DynamicCIDRLoader` class with `httpx.AsyncClient` (already in deps)
- `__init__` accepts `api_url`, `api_token`, `refresh_interval_seconds=300`
- Background task `asyncio.create_task(_refresh_loop())` runs on startup
- `is_allowed(ip)` reads from in-memory `self._cidrs` (atomic ref swap on refresh)

### Step 2: env vars
`.env` on zjlab:
```
GW_IP_WHITELIST_DYNAMIC_URL=http://zjlab-metadata.ops.local:8080/v1/network/cidrs
GW_IP_WHITELIST_DYNAMIC_TOKEN=<shared-secret-from-zjlab-vault>
GW_IP_WHITELIST_DYNAMIC_REFRESH_SECONDS=300
```

### Step 3: backward compat
- If `GW_IP_WHITELIST_DYNAMIC_URL` is empty (default), use hard-coded defaults (R6.73 behavior)
- No breaking change for local dev or non-zjlab deployments

### Step 4: tests
- Unit test: mock httpx response, verify CIDR list updates
- Integration test: spin up zjlab-metadata mock, verify refresh loop polls
- Failure test: simulate 5xx, verify fallback to defaults

## Why this design
- **Backward compat**: existing R6.73 deployments continue to work
- **Failure resilient**: API outage → defaults, no whitelist bypass
- **Per-service CIDRs**: future-proof for per-service whitelist policies
- **No new dep**: httpx already in gw-pipeline requirements

## Open questions (for zjlab team)
1. Where does `zjlab-metadata` API live? (existing service or new?)
2. Token rotation strategy? (vault-based or static?)
3. API uptime SLA? (impacts our 5-min refresh interval)
4. Should we add admin CIDR list separately or merge into single response?

## Estimated effort
- Step 1 (refactor): 2-3 hours
- Step 2 (env vars): 15 minutes
- Step 3 (backward compat): 30 minutes
- Step 4 (tests): 2-3 hours
- **Total: 5-7 hours = 1 day sprint**

## Status

R6.76: Design doc only (this file). Awaiting zjlab team API availability.
