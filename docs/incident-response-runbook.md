# GravitationalWave Platform — Security Incident Response Runbook v4.37

## Incident Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| **P0** | Service completely unavailable | 15 min | All containers down, DB corruption |
| **P1** | Major feature broken | 30 min | AI agent not responding, auth broken |
| **P2** | Minor degradation | 2 hours | Slow responses, partial tool failures |
| **P3** | Non-critical issue | 24 hours | Deprecation warnings, cosemetic issues |

## P0 — Critical Incident Response

### Step 1: Assess (5 min)
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
curl -s http://localhost:8200/health
curl -s http://localhost:8093/actuator/health
bash scripts/monitor.sh status
```

### Step 2: Contain (10 min)
```bash
# If under active attack:
bash scripts/incident-response.sh emergency-stop

# If specific service crash:
bash scripts/incident-response.sh isolate <service>
bash scripts/incident-response.sh snapshot-logs <service>
```

### Step 3: Restore
```bash
# Option A: Restart affected service
docker compose -f docker-compose.yml restart <service>

# Option B: Full restart
docker compose -f docker-compose.yml down
docker compose -f docker-compose.yml up -d

# Option C: Rollback to last known good version
bash scripts/rollback.sh <last-good-tag>
```

### Step 4: Verify
```bash
# Check all services healthy
bash scripts/monitor.sh status

# Run recovery drill
bash scripts/recovery-drill.sh

# Verify AI is functional
curl -X POST http://localhost:8200/pipeline/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"ping"}], "max_tool_rounds":0}'
```

## P1 — Major Feature Failure

### AI Agent Not Responding
1. Check DeepSeek API status: `curl -s http://localhost:8200/pipeline/agent/status`
2. Check quota: look for `gw_quota_exhaustions_total` in `/pipeline/metrics`
3. Check tool cache health: `curl -s http://localhost:8200/pipeline/tool/cache-stats`
4. Restart pipeline if needed: `docker compose restart gw-pipeline`

### Authentication Broken
1. Check backend health: `curl -s http://localhost:8093/actuator/health`
2. Check MongoDB connectivity: `docker exec gw-backend nc -z mongodb 27017`
3. Verify JWT secret: `bash scripts/rotate_jwt_secret.py --dry-run`

## P2 — Partial Degradation

### Tool Failures
1. Check tool metrics: `curl -s http://localhost:8200/pipeline/metrics | grep gw_tool`
2. Check backend connectivity from pipeline
3. Review recent audit logs: `curl -s http://localhost:8200/pipeline/admin/audit/logs?limit=50`

### Slow Responses
1. Check LLM latency: `curl -s http://localhost:8200/pipeline/metrics | grep latency`
2. Check cache hit rate: `curl -s http://localhost:8200/pipeline/metrics | grep cache_hit`
3. Check resource usage: `docker stats --no-stream`

## P3 — Non-critical Issues

- Review error metrics weekly: `curl -s http://localhost:8200/pipeline/metrics | grep gw_errors`
- Run dependency scan weekly: `bash scripts/scan-deps.sh`
- Rotate credentials monthly: `bash scripts/rotate_jwt_secret.py`

## Contacts & Escalation

| Role | Contact | When to Escalate |
|------|---------|-----------------|
| Platform Operator | ZJWB260819 | P0/P1 incidents |
| ZhiJiang Lab Admin | Instructor | Infrastructure issues |
| DeepSeek Support | api@deepseek.com | Persistent API failures |

## Post-Incident Review

After any P0/P1 incident:
1. Document timeline in `docker-data/incidents/postmortem-YYYYMMDD.md`
2. Identify root cause
3. Update this runbook if procedures changed
4. Add automated check if incident could have been detected earlier
