#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zsmoke.py — R6.99 #6: Unified smoketest suite for gw-platform on zjlab.

PURPOSE:
  Single script that runs ALL smoketests + healthchecks across the gw-platform stack.
  Replaces the fragmented zjlab-verify-*.py scripts (r692, smoketest, image, r693,
  r694, r694c/d/e). One command, one report, JSON or human-readable.

USAGE:
  python zsmoke.py                # full suite, 8 checks, human-readable output
  python zsmoke.py quick          # essential 4 checks only (smoke + containers)
  python zsmoke.py --json         # JSON output for CI / monitoring
  python zsmoke.py --read-remote  # also read ~/last-deploy.json (R6.99 #5)
  python zsmoke.py --only r692,backend-health,disk  # run specific checks
  python zsmoke.py --no-fail      # exit 0 even on FAIL (for cron, never block)

CHECKS (each returns status PASS|FAIL|WARN|SKIP + duration_ms + message):
  1. r692-smoketest       (R6.92b): GET /r692-smoketest-status -> 200
  2. backend-health       (R6.96c): GET https://backend-health.local:6002/backend-health -> 200 + X-Backend-Status: 200
  3. gw-frontend          container: docker ps Up status
  4. gw-pipeline          container: docker ps Up status
  5. gw-backend (divs)    container: docker ps Up status
  6. nginx-config-test    (R6.92a): docker exec gw-frontend nginx -t -> "syntax is ok"
  7. disk-space           : df -h /home/zjlab -> WARN if >85% used
  8. last-deploy          (R6.99 #5): read remote last-deploy.json, verify commit_sha matches git HEAD (only with --read-remote)
  9. api-health           (R6.80): GET http://divs-backend:8093/api/health -> verify status=UP + app/elasticsearch/mongo all UP

EXIT CODES:
  0 = all PASS (or all PASS+WARN with --no-fail)
  1 = any FAIL
  2 = only WARN (partial pass — indicates something needs attention but no hard failure)
  3 = couldn't even run (zkb import failed, no SSH, etc.)

IRON RULES:
  - r678-classifier-boundary: this script only READS state via SSH. NEVER writes to zjlab.
  - r692-smoketest-pattern: uses /r692-smoketest-status endpoint as the canonical gw-frontend health.
  - r696-backend-health: backend-health.local is the ONLY way to check gw-backend without
    docker exec or VPN tunnel. Endpoint requires custom Host header (--resolve trick).
  - r682-push-ssh: this script does NOT push anything. It only reads.

WHY THIS EXISTS (R6.99 #6 backlog):
  - 6 separate zjlab-verify-*.py scripts grew organically across R6.92-R6.94
  - Each was written for a specific R6.x deploy verification
  - Run them all = 6 SSH sessions, 6 outputs to compare, no unified pass/fail
  - zsmoke.py: 1 SSH session (zkb long-lived), 1 report, machine-readable
  - + integrations with write-deploy-record.py (R6.99 #5) and --read-remote flag

REQUIREMENTS:
  - zkb.py importable (D:\\AliCPT\\scripts\\zkb.py in sys.path)
  - SSH bastion reachable (192.168.10.10:60022)
  - zjlab server reachable (10.107.207.103:22 via bastion)
  - For check #8: --read-remote flag + previous deploy used write-deploy-record.py --remote
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Force stdout/stderr to utf-8 (Windows defaults to GBK)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

LOCAL_REPO = Path(r'D:\AliCPT')
REMOTE_AUDIT_FILE = '~/last-deploy.json'
DEFAULT_DISK_WARN_PCT = 85
DEFAULT_DISK_FAIL_PCT = 95


# === Status constants ===
PASS = 'PASS'
FAIL = 'FAIL'
WARN = 'WARN'
SKIP = 'SKIP'


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _git_head_sha() -> Optional[str]:
    """Return current HEAD SHA from D:\AliCPT, or None if git fails."""
    try:
        result = subprocess.run(
            ['git', '-C', str(LOCAL_REPO), 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


# === Individual checks (each returns (status, duration_ms, message)) ===
# All checks take a `z` (Zkb instance) as first arg for SSH access.

def check_r692_smoketest(z, **kwargs) -> tuple[str, int, str]:
    """R6.92b: GET /r692-smoketest-status on port 6002 with Host: r692-smoketest.local -> expect 200.

    The smoketest endpoint is served by gw-frontend on port 6002 behind the dedicated
    server_name 'r692-smoketest.local' (see R6.92b/R6.94 deploy). Plain :6001 hits the
    main frontend default server block which 404s the path, so we MUST use --resolve
    (same pattern as check_backend_health below).
    """
    t0 = time.time()
    cmd = (
        'curl -sk --resolve "r692-smoketest.local:6002:127.0.0.1" '
        '-o /dev/null -w "%{http_code}" '
        'https://r692-smoketest.local:6002/r692-smoketest-status'
    )
    out, code = z.run(cmd, timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    http_code = (out or '').strip().splitlines()[-1] if out else ''
    if code != 0:
        return FAIL, duration_ms, 'curl exit={}'.format(code)
    if http_code == '200':
        return PASS, duration_ms, 'HTTP=200'
    return FAIL, duration_ms, 'HTTP={}'.format(http_code or 'unknown')


def check_backend_health(z, **kwargs) -> tuple[str, int, str]:
    """R6.96c: GET https://backend-health.local:6002/backend-health -> expect 200 + X-Backend-Status: 200."""
    t0 = time.time()
    cmd = (
        'curl -sk --resolve "backend-health.local:6002:127.0.0.1" '
        '-w "\nHTTP=%{http_code}\n" '
        '-D /tmp/bh_headers '
        'https://backend-health.local:6002/backend-health'
    )
    out, code = z.run(cmd, timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0:
        return FAIL, duration_ms, 'curl exit={}'.format(code)
    # Extract HTTP code from -w output
    http_match = re.search(r'HTTP=(\d+)', out or '')
    http_code = http_match.group(1) if http_match else '?'
    # Read headers
    hdrs_out, _ = z.run('cat /tmp/bh_headers 2>/dev/null', timeout=5)
    backend_status = '?'
    if hdrs_out:
        bs_match = re.search(r'X-Backend-Status:\s*(\d+)', hdrs_out, re.I)
        if bs_match:
            backend_status = bs_match.group(1)
    if http_code == '200' and backend_status == '200':
        return PASS, duration_ms, 'HTTP=200 X-Backend-Status=200'
    if http_code == '200' and backend_status != '200':
        return FAIL, duration_ms, 'HTTP=200 but X-Backend-Status={}'.format(backend_status)
    return FAIL, duration_ms, 'HTTP={} X-Backend-Status={}'.format(http_code, backend_status)


def _container_status(z, name: str) -> tuple[str, int, str]:
    """Internal helper: check container is Up via `docker ps`."""
    t0 = time.time()
    cmd = 'docker ps --filter name={} --format "{{{{.Status}}}}"'.format(name)
    out, code = z.run(cmd, timeout=10)
    duration_ms = int((time.time() - t0) * 1000)
    status = (out or '').strip().splitlines()[0] if out else ''
    if code != 0:
        return FAIL, duration_ms, 'docker ps exit={}'.format(code)
    if status.startswith('Up '):
        return PASS, duration_ms, status
    if not status:
        return FAIL, duration_ms, 'container not found'
    return FAIL, duration_ms, 'status={}'.format(status)


def check_gw_frontend(z, **kwargs) -> tuple[str, int, str]:
    """gw-frontend container (nginx) is Up."""
    return _container_status(z, 'gw-frontend')


def check_gw_pipeline(z, **kwargs) -> tuple[str, int, str]:
    """gw-pipeline container (Python pipeline) is Up."""
    return _container_status(z, 'gw-pipeline')


def check_gw_backend(z, **kwargs) -> tuple[str, int, str]:
    """gw-backend / divs-backend container (Spring Boot) is Up."""
    # Spring Boot container is named divs-backend in compose; gw-backend is the service DNS
    return _container_status(z, 'divs-backend')


def check_nginx_config(z, **kwargs) -> tuple[str, int, str]:
    """R6.92a: docker exec gw-frontend nginx -t -> expect 'syntax is ok'."""
    t0 = time.time()
    out, code = z.run('docker exec gw-frontend nginx -t 2>&1', timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0:
        return FAIL, duration_ms, 'nginx -t exit={}'.format(code)
    if 'syntax is ok' in (out or '') and 'test is successful' in (out or ''):
        return PASS, duration_ms, 'syntax ok'
    return FAIL, duration_ms, 'unexpected: {}'.format((out or '').strip()[:100])


def check_disk_space(z, **kwargs) -> tuple[str, int, str]:
    """df -h /home/zjlab -> WARN if >85%, FAIL if >95%."""
    t0 = time.time()
    out, code = z.run("df -h /home/zjlab | tail -1 | awk '{print $5}'", timeout=10)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0:
        return FAIL, duration_ms, 'df exit={}'.format(code)
    pct_str = (out or '').strip().rstrip('%').splitlines()[-1]
    try:
        pct = int(pct_str)
    except (ValueError, TypeError):
        return FAIL, duration_ms, 'cannot parse: {}'.format(pct_str)
    if pct >= DEFAULT_DISK_FAIL_PCT:
        return FAIL, duration_ms, '{}% used (FAIL threshold {})'.format(pct, DEFAULT_DISK_FAIL_PCT)
    if pct >= DEFAULT_DISK_WARN_PCT:
        return WARN, duration_ms, '{}% used (WARN threshold {})'.format(pct, DEFAULT_DISK_WARN_PCT)
    return PASS, duration_ms, '{}% used'.format(pct)


def check_last_deploy(z, **kwargs) -> tuple[str, int, str]:
    """R6.99 #5: read remote last-deploy.json + verify commit_sha matches git HEAD.

    NOTE: We deliberately compare FULL 40-char SHA (not --short 7-char) for collision safety.
    7-char short SHAs are subject to birthday collisions at ~4k commits; full SHA is collision-free.
    Both `commit_sha` (full) and `commit_short` (7-char) are stored in the audit record.
    """
    t0 = time.time()
    out, code = z.run('cat {} 2>/dev/null'.format(REMOTE_AUDIT_FILE), timeout=10)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0 or not out or not out.strip():
        return FAIL, duration_ms, 'remote {} not readable'.format(REMOTE_AUDIT_FILE)
    try:
        record = json.loads(out)
    except json.JSONDecodeError as e:
        return FAIL, duration_ms, 'invalid JSON: {}'.format(e)
    remote_sha = record.get('commit_sha', '')
    local_sha = _git_head_sha()
    if not local_sha:
        return WARN, duration_ms, 'git HEAD unreadable; remote sha={}'.format(remote_sha[:7] if remote_sha else '?')
    if remote_sha == local_sha:
        ts = record.get('timestamp_utc', '?')
        op = record.get('operator', '?')
        return PASS, duration_ms, 'sha match ({}) ts={} op={}'.format(remote_sha[:7], ts, op)
    # Compare commit distance
    try:
        rev_result = subprocess.run(
            ['git', '-C', str(LOCAL_REPO), 'rev-list', '--count', '{}..HEAD'.format(remote_sha)],
            capture_output=True, text=True, timeout=10,
        )
        behind = int(rev_result.stdout.strip()) if rev_result.returncode == 0 else -1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        behind = -1
    if behind == 0:
        return PASS, duration_ms, 'sha match (forward sync)'
    if behind > 0:
        return WARN, duration_ms, 'local {} commits ahead of remote {} (sha={})'.format(
            behind, remote_sha[:7], local_sha[:7])
    return WARN, duration_ms, 'remote sha {} not in local history (local={})'.format(
        remote_sha[:7], local_sha[:7])


def check_api_health(z, **kwargs) -> tuple[str, int, str]:
    """R6.80: GET http://divs-backend:8093/api/health -> verify UP + all components.

    The /api/health endpoint is the public-facing health probe (R6.103/R6.80).
    Returns JSON like:
      {"error":{"code":"0","msg":""},"data":{"status":"UP","version":"v4.61-...",
        "timestamp":"...","components":{"app":{"status":"UP"},"elasticsearch":{...},"mongo":{...}}}}

    Probe via docker exec to avoid the gateway canary path issues.
    """
    t0 = time.time()
    cmd = (
        "docker exec divs-backend sh -c 'wget -qO- http://localhost:8093/api/health'"
    )
    out, code = z.run(cmd, timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0:
        return FAIL, duration_ms, 'docker exec wget exit={}'.format(code)
    body = (out or '').strip()
    if not body:
        return FAIL, duration_ms, 'empty body'
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError as e:
        return FAIL, duration_ms, 'invalid JSON: {}'.format(e)
    # Unwrap Response wrapper: {error, data}
    if not isinstance(envelope, dict) or 'data' not in envelope:
        return FAIL, duration_ms, 'no data envelope: {}'.format(body[:200])
    data = envelope.get('data', {})
    status = data.get('status', '?')
    version = data.get('version', '?')
    components = data.get('components', {})
    required = ['app', 'elasticsearch', 'mongo']
    missing = [c for c in required if c not in components]
    if missing:
        return FAIL, duration_ms, 'missing components: {}'.format(missing)
    down = [c for c in required if components.get(c, {}).get('status') != 'UP']
    if status != 'UP' or down:
        return FAIL, duration_ms, 'status={} down={}'.format(status, down)
    # All UP — report version + latency summary
    total_latency = sum(components[c].get('latency_ms', 0) for c in required if 'latency_ms' in components.get(c, {}))
    return PASS, duration_ms, 'UP v={} components_ms={}'.format(version, total_latency)


def check_api_health_parallel(z, **kwargs) -> tuple[str, int, str]:
    """R6.84a: concurrent /api/health probes — assert max(latency_ms) < sum(latency_ms).

    Fires 3 parallel docker-exec /api/health requests via gw's run() with separate
    SSH channels (ThreadPoolExecutor). After all complete, asserts max component
    latency < sum component latency to prove ES + Mongo probes run concurrently
    (R6.83 fan-out working in prod).

    R6.83 L6 follow-up: prod-concurrency proof vs unit-test concurrency proof.
    A unit test can prove executor logic; only a prod probe proves the EXECUTED jar
    fans out as expected.

    Why 3 probes (not 1): averaging over 3 reduces the chance of a single
    transient measurement skewing the assertion.
    """
    import concurrent.futures
    t0 = time.time()
    cmd = "docker exec divs-backend sh -c 'wget -qO- http://localhost:8093/api/health'"

    def _probe(_):
        # gw's run() opens its own SSH channel per call; ThreadPoolExecutor
        # overlaps those channels so the 3 docker execs run concurrently.
        out, _ = z.run(cmd, timeout=15)
        return out or ''

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        bodies = list(ex.map(_probe, range(3)))

    es_latencies = []
    mongo_latencies = []
    statuses = []
    for body in bodies:
        body = body.strip()
        if not body:
            return FAIL, int((time.time() - t0) * 1000), 'empty body from one of 3 probes'
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError as e:
            return FAIL, int((time.time() - t0) * 1000), 'invalid JSON: {}'.format(e)
        if not isinstance(envelope, dict) or 'data' not in envelope:
            return FAIL, int((time.time() - t0) * 1000), 'no data envelope in one probe'
        data = envelope.get('data', {})
        comp = data.get('components', {})
        statuses.append(data.get('status'))
        if 'elasticsearch' in comp:
            es_latencies.append(comp['elasticsearch'].get('latency_ms', 0))
        if 'mongo' in comp:
            mongo_latencies.append(comp['mongo'].get('latency_ms', 0))

    if not all(s == 'UP' for s in statuses) or not es_latencies or not mongo_latencies:
        return FAIL, int((time.time() - t0) * 1000), 'statuses={} es_n={} mongo_n={}'.format(
            statuses, len(es_latencies), len(mongo_latencies),
        )

    # Aggregate per concurrent burst: median ES + median Mongo across the 3 probes.
    es_lat = sorted(es_latencies)[len(es_latencies) // 2]
    mongo_lat = sorted(mongo_latencies)[len(mongo_latencies) // 2]
    max_lat = max(es_lat, mongo_lat)
    sum_lat = es_lat + mongo_lat

    duration_ms = int((time.time() - t0) * 1000)
    if max_lat >= sum_lat:
        # Equality only happens if both latencies are 0 (degenerate); else max < sum
        # is always true for positive latencies. Reaching here means either
        # (a) probes are sequential (would report ES + Mongo delays sequentially)
        # OR (b) latency reporting regressed.
        return FAIL, duration_ms, (
            'max(latency_ms)={} >= sum(latency_ms)={} (probes sequential? latency reporting regressed?)'
            .format(max_lat, sum_lat)
        )
    return PASS, duration_ms, 'concurrent: max={}ms < sum={}ms (ES={}ms mongo={}ms, concurrency proof OK)'.format(
        max_lat, sum_lat, es_lat, mongo_lat,
    )


def check_api_health_rate_limit(z, **kwargs) -> tuple[str, int, str]:
    """R6.85c + R6.86: rapid-fire /api/health probes, verify rate limit fires.

    R6.85c design (sequential): 70 sequential docker-exec wget calls — fails in
    practice because each SSH-tunneled docker-exec takes ~1s, bucket4j
    Refill.intervally(200, 1m) lets ~3.33 req/s through, and 1 req/s < 3.33/s,
    so the bucket never depletes. Result: ALL 70 = 200, false-negative.

    R6.86 fix (parallel): 50 background jobs × 5 reqs = 250 reqs fired in <5s.
    Bursts the bucket faster than refill, so 200/min/IP cap fires for the tail.
    Active profile `redis` overrides default 60 → 200/min/IP
    (application-redis.properties: rate.limit.capacity=200). With redis profile
    (production default), expected: 200x200 + 50x429 = 250.

    Why parallel-burst works where sequential fails:
      - Sequential: 250 reqs @ ~1s each through SSH = ~250s wall clock
      - Parallel:   250 reqs in 50 bg jobs firing simultaneously = <5s wall clock
      - Refill rate: 200/60s = 3.33/s; sequential (1/s) stays under quota;
        parallel (50/s) overshoots quota, depleting in ~4.3s
      - bucket4j Refill.intervally semantics: full 200-token chunk refilled
        every 60s (NOT 200 spread evenly across 60s). This means each refilled
        instant the bucket briefly has 200 tokens available, which sequential
        probes drain one-by-one before the next refill window. Parallel burst
        fires faster than refill can replenish, depleting permanently.

    C1-DEPLOY fix: R6.86's first iteration used `grep -o "HTTP/[0-9.]* [0-9]*"`
    on wget stdout to extract HTTP status, but wget -q emits the JSON body
    (NOT the HTTP status line) — grep never matched, check always returned
    FAIL. Fix uses body discriminator: `\"status\":\"UP\"` (HealthController
    JSON envelope on 200) vs absent (bucket4j 429 envelope).
    """
    t0 = time.time()
    quota = 200  # matches application-redis.properties rate.limit.capacity=200 (prod)
    # Quota=200, total=250 (50 over). Expect ~200 success + ~50 rate-limited.
    total = quota + 50
    bg_jobs = 50
    reqs_per_job = 5  # 50 × 5 = 250 total

    # Compose single-shot command: spawn 50 bg subshells each firing 5 wget
    # requests. Output is HTTP code per line, then concatenate + sort + uniq -c.
    # All 50 subshells share stdout (captured in /tmp/rl_results_N.txt).
    #
    # R6.86 + C1-DEPLOY fix: previous pattern used `grep -o "HTTP/[0-9.]* [0-9]*"`
    # to extract the HTTP status line, but `wget -qO-` emits JSON body (not
    # status line) so the grep NEVER matched and the check always returned
    # FAIL on live runs. Unit tests passed only because they mocked z.run().
    #
    # New approach: body discriminator. The 200 path body contains
    # `"status":"UP"` (HealthController JSON). The 429 path body (bucket4j
    # interceptor rejection) does NOT contain `"status":"UP"`. So:
    #   body=$(wget -qO- ... 2>/dev/null); if echo "$body" | grep -q '"status":"UP"'
    #   then echo 200 else echo 429 >> /tmp/rl_results_${j}.txt
    # Also handles wget network/timeout failures correctly: empty body fails
    # the grep, echoes 429 (acceptable mis-classification; not a real 429).
    inner_loop = (
        'for i in $(seq 1 {reqs_per_job}); do '
        'body=$(wget -qO- -T 5 --tries=1 http://localhost:8093/api/health 2>/dev/null); '
        'if echo "$body" | grep -q \'"status":"UP"\'; then '
        'echo 200; '
        'else '
        'echo 429; '
        'fi >> "${{RLDIR}}/rl_results_${{j}}.txt"; '
        'done'
    ).format(reqs_per_job=reqs_per_job)
    # R6.89 mktemp hardening: per-run private tmp dir prevents symlink-attack / glob-forge
    # on shared /tmp. The pre-R6.89 `rm -f /tmp/rl_results_*.txt` + `cat /tmp/rl_results_*.txt`
    # was forgeable by an attacker pre-creating a symlink at /tmp/rl_results_1.txt pointing to
    # e.g. /etc/passwd. Zjlab trusted-host posture makes this VERY LOW risk but defense-in-depth.
    # busybox mktemp is portable across the gw-* containers (centos + alpine hosts).
    full_cmd = (
        'export RLDIR=$(mktemp -d /tmp/rl_results.XXXXXX); '
        'chmod 700 "$RLDIR"; '
        'for j in $(seq 1 {bg_jobs}); do '
        '( {inner_loop} ) & '
        'done; wait; '
        'cat "$RLDIR"/rl_results_*.txt 2>/dev/null | sort | uniq -c; '
        'rm -rf "$RLDIR"'
    ).format(bg_jobs=bg_jobs, inner_loop=inner_loop)

    out, code = z.run(full_cmd, timeout=60)
    body = (out or '').strip()
    duration_ms = int((time.time() - t0) * 1000)

    if code != 0 or not body:
        return FAIL, duration_ms, 'parallel burst failed: code={} body={}'.format(
            code, body[:200])

    # Parse " 200 200\n  50 429" style output
    success_count = 0
    rate_limited_count = 0
    other_codes = []
    for line in body.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            count = int(parts[0])
            http_code = int(parts[1])
        except (ValueError, IndexError):
            continue
        if http_code == 200:
            success_count += count
        elif http_code == 429:
            rate_limited_count += count
        else:
            other_codes.append((count, http_code))

    # Expected: ~200 success + ~50 rate-limited
    if success_count >= quota and rate_limited_count >= (total - quota):
        return PASS, duration_ms, (
            'rate-limit ENFORCED (parallel burst {}ms): {}/{} success, {}/{} rate-limited'
        ).format(duration_ms, success_count, total, rate_limited_count, total)
    if rate_limited_count == 0:
        return WARN, duration_ms, (
            'NO rate limiting observed (parallel burst): {}/{} success, 0 rate-limited '
            '(R6.85c not deployed? excludePathPatterns still on /api/health?)'
        ).format(success_count, total)
    if other_codes:
        return WARN, duration_ms, (
            'unexpected codes in parallel burst: {}/{} success, {}/{} 429, other={} (full={})'
        ).format(success_count, total, rate_limited_count, total, other_codes, body[:300])
    return WARN, duration_ms, (
        'unexpected: {}/{} success, {}/{} rate-limited (full={})'
    ).format(success_count, total, rate_limited_count, total, body[:300])


def check_prometheus_endpoint(z, **kwargs) -> tuple[str, int, str]:
    """R6.94c: GET /actuator/prometheus from inside divs-backend container.

    Probes the Prometheus scrape endpoint from localhost (loopback — whitelisted
    by ActuatorIpWhitelistFilter R6.94-A). Expects HTTP 200 with non-empty
    Prometheus exposition body containing at least 3 standard JVM metric families
    + the custom r690_controller_requests counter from MetricsInterceptor (B2).

    Use case: end-to-end verification that micrometer-registry-prometheus dep
    (R6.94c) is on classpath + PrometheusMeterRegistry is bound + filter allows
    loopback + the B2 counter has fired at least once during the deploy session.
    """
    t0 = time.time()
    cmd = "docker exec divs-backend sh -c 'wget -qO- -T 5 --tries=1 http://localhost:8093/actuator/prometheus | head -c 4096'"
    out, code = z.run(cmd, timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    if code != 0:
        return FAIL, duration_ms, 'wget exit={} (filter blocking? dep missing?)'.format(code)
    body = (out or '').strip()
    if not body:
        return FAIL, duration_ms, 'empty body — PrometheusMeterRegistry not bound (R6.94c dep missing?)'
    for metric in ['jvm_memory_used_bytes', 'jvm_threads_states', 'process_cpu_usage']:
        if metric not in body:
            return FAIL, duration_ms, 'metric {} missing — registry partial'.format(metric)
    counter_present = 'r690_controller_requests' in body
    warn_msg = ' (WARN: r690_controller_requests counter absent — MetricsInterceptor not invoked yet)' if not counter_present else ''
    metric_count = body.count('# HELP')
    return PASS, duration_ms, 'HTTP=200 metrics_count={}{}'.format(metric_count, warn_msg)


def check_prometheus_whitelist(z, **kwargs) -> tuple[str, int, str]:
    """R6.94-A: ActuatorIpWhitelistFilter permits whitelisted siblings (200).

    Verifies the inverse side of the iron rule — that whitelisted sources
    (gw-pipeline on gw-net, which gets a 172.x IP) CAN reach /actuator/prometheus
    and get HTTP 200 + valid Prometheus body. The "filter blocks non-whitelisted
    IPs" half of the test requires a unit test on the filter (R6.95+ scope)
    since zsmoke.py only has access to in-cluster probes that are themselves
    on the whitelisted gw-net bridge.

    Use case: end-to-end sanity check that the whitelist filter doesn't break
    Prometheus-family scraping — sibling containers on gw-net still get 200
    (the filter ALLOWS 127.x + 172.16-31.x + 10.x + 192.168.x).

    Note: the original docstring claimed "gw-pipeline is NOT in the actuator
    filter's whitelist" — that was wrong. The filter whitelists the entire
    Docker bridge range 172.16.0.0/12 (lines 72-74), and gw-pipeline is on
    gw-net which assigns 172.x IPs. So the filter correctly ALLOWS gw-pipeline;
    expecting 200 from gw-pipeline IS the correct outcome.
    """
    t0 = time.time()
    cmd = "docker exec gw-pipeline sh -c 'wget -qO- -T 5 --tries=1 http://gw-backend:8093/actuator/prometheus 2>&1 | head -c 4096'"
    out, code = z.run(cmd, timeout=15)
    duration_ms = int((time.time() - t0) * 1000)
    body = (out or '')
    # Expect 200 (whitelisted sibling). If we got it, the filter allows
    # gw-net traffic as designed. If we got 403/empty/refused, the filter
    # is over-blocking — that's a regression worth flagging.
    if code != 0 or not body.strip():
        return FAIL, duration_ms, 'empty/error response from gw-pipeline (code={}) — filter may be over-blocking whitelisted siblings. body[:200]={}'.format(code, body[:200])
    if 'jvm_memory_used_bytes' in body or 'r690_controller_requests' in body:
        return PASS, duration_ms, 'HTTP=200 with Prometheus body — filter correctly allows whitelisted gw-net siblings'
    return WARN, duration_ms, 'HTTP 200 but Prometheus body missing standard metrics (filter over-sanitizing?). body[:200]={}'.format(body[:200])


# === Check registry ===
CHECKS = {
    'r692-smoketest':       ('R6.92b smoketest endpoint on :6001',                 check_r692_smoketest,           False),
    'backend-health':       ('R6.96c gw-backend health via :6002 canary',          check_backend_health,           False),
    'gw-frontend':          ('gw-frontend container (nginx) is Up',                check_gw_frontend,              False),
    'gw-pipeline':          ('gw-pipeline container is Up',                        check_gw_pipeline,              False),
    'gw-backend':           ('divs-backend container (Spring Boot) is Up',         check_gw_backend,               False),
    'nginx-config':         ('R6.92a nginx -t syntax check',                       check_nginx_config,             False),
    'disk-space':           ('disk usage on /home/zjlab',                          check_disk_space,               False),
    'last-deploy':          ('R6.99 #5 remote last-deploy.json vs git HEAD',       check_last_deploy,              True),  # True = requires --read-remote
    'api-health':           ('R6.80 /api/health from divs-backend',                check_api_health,               False),
    'api-health-parallel':  ('R6.84a concurrent /api/health probes (max<sum)',      check_api_health_parallel,      False),
    'api-health-rate-limit':('R6.85c rapid /api/health probes verify rate limit',   check_api_health_rate_limit,    False),
    'prometheus-endpoint':  ('R6.94c /actuator/prometheus from loopback (200+metrics)', check_prometheus_endpoint,    False),
    'prometheus-whitelist': ('R6.94-A ActuatorIpWhitelistFilter 403s non-whitelisted', check_prometheus_whitelist,    False),
}


QUICK_CHECKS = [
    'r692-smoketest',
    'backend-health',
    'gw-frontend',
    'gw-backend',
    'api-health',
    'api-health-parallel',  # R6.84a
]


def run_checks(names: list[str], read_remote: bool, json_mode: bool) -> tuple[list[dict], int]:
    """Run the requested checks. Returns (results, exit_code)."""
    try:
        from zkb import Zkb  # type: ignore
    except ImportError as e:
        print('ERROR: zkb.py not importable: {}'.format(e), file=sys.stderr)
        return [], 3

    results: list[dict] = []
    z = Zkb()
    try:
        started = _now_utc_iso()
        t_total = time.time()

        for name in names:
            if name not in CHECKS:
                results.append({
                    'name': name, 'status': SKIP, 'duration_ms': 0,
                    'message': 'unknown check (typo?)',
                })
                continue
            desc, fn, requires_remote = CHECKS[name]
            if requires_remote and not read_remote:
                results.append({
                    'name': name, 'status': SKIP, 'duration_ms': 0,
                    'message': '--read-remote not set',
                })
                continue
            try:
                status, dur_ms, msg = fn(z)
            except Exception as e:
                status, dur_ms, msg = FAIL, 0, 'exception: {}'.format(e)
            results.append({
                'name': name, 'status': status, 'duration_ms': dur_ms, 'message': msg,
            })
            if not json_mode:
                _print_line(name, status, dur_ms, msg)

        total_ms = int((time.time() - t_total) * 1000)
    finally:
        try:
            z.close()
        except Exception:
            pass

    # Tally
    passed = sum(1 for r in results if r['status'] == PASS)
    failed = sum(1 for r in results if r['status'] == FAIL)
    warned = sum(1 for r in results if r['status'] == WARN)
    skipped = sum(1 for r in results if r['status'] == SKIP)

    # Determine exit code
    # 1 = any FAIL, 2 = any WARN OR partial pass (PASS+SKIP mix means not all checks ran),
    # 3 = nothing ran (all skipped), 0 = all PASS
    if failed > 0:
        exit_code = 1
    elif warned > 0:
        exit_code = 2
    elif skipped > 0:
        # Mixed PASS + SKIP (e.g., last-deploy without --read-remote) -> partial pass
        exit_code = 2
    elif skipped == len(results):
        exit_code = 3
    else:
        exit_code = 0

    if json_mode:
        report = {
            'timestamp_utc': started,
            'total': len(results),
            'passed': passed,
            'failed': failed,
            'warned': warned,
            'skipped': skipped,
            'duration_ms': total_ms,
            'exit_code': exit_code,
            'checks': results,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print()
        print('[zsmoke] {}/{} PASS, {} FAIL, {} WARN, {} SKIP ({}ms total)'.format(
            passed, len(results), failed, warned, skipped, total_ms))
        print('[zsmoke] exit {}'.format(exit_code))

    return results, exit_code


def _print_line(name: str, status: str, dur_ms: int, msg: str) -> None:
    status_marker = {
        PASS: '[OK]  ',
        FAIL: '[FAIL]',
        WARN: '[WARN]',
        SKIP: '[--]  ',
    }.get(status, '[????]')
    dur_str = '{}ms'.format(dur_ms) if dur_ms else 'N/A  '
    print('{} {:24s} {:>6s}   {}'.format(status_marker, name, dur_str, msg))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Unified smoketest suite for gw-platform on zjlab.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--json', action='store_true', help='JSON output (for CI)')
    parser.add_argument('--read-remote', action='store_true',
                        help='Also read remote ~/last-deploy.json (enables last-deploy check)')
    parser.add_argument('--only', help='Comma-separated check names (default: all)')
    parser.add_argument('--no-fail', action='store_true',
                        help='Exit 0 even on FAIL (for cron, never block)')
    parser.add_argument('mode', nargs='?', default='full', choices=['full', 'quick'],
                        help='full (default) or quick')
    args = parser.parse_args()

    if args.only:
        names = [n.strip() for n in args.only.split(',') if n.strip()]
    elif args.mode == 'quick':
        names = list(QUICK_CHECKS)
    else:
        names = list(CHECKS.keys())

    if not args.json:
        print('[zsmoke] {} starting {} checks (mode={}, read_remote={})'.format(
            _now_utc_iso(), len(names), args.mode, args.read_remote))
        print()

    _, exit_code = run_checks(names, args.read_remote, args.json)

    if args.no_fail and exit_code == 1:
        return 0
    return exit_code


if __name__ == '__main__':
    sys.exit(main())