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


# === Check registry ===
CHECKS = {
    'r692-smoketest':   ('R6.92b smoketest endpoint on :6001',          check_r692_smoketest, False),
    'backend-health':   ('R6.96c gw-backend health via :6002 canary',   check_backend_health, False),
    'gw-frontend':      ('gw-frontend container (nginx) is Up',         check_gw_frontend,    False),
    'gw-pipeline':      ('gw-pipeline container is Up',                 check_gw_pipeline,    False),
    'gw-backend':       ('divs-backend container (Spring Boot) is Up',  check_gw_backend,     False),
    'nginx-config':     ('R6.92a nginx -t syntax check',                check_nginx_config,   False),
    'disk-space':       ('disk usage on /home/zjlab',                   check_disk_space,     False),
    'last-deploy':      ('R6.99 #5 remote last-deploy.json vs git HEAD',check_last_deploy,    True),  # True = requires --read-remote
    'api-health':       ('R6.80 /api/health from divs-backend',         check_api_health,     False),
}


QUICK_CHECKS = ['r692-smoketest', 'backend-health', 'gw-frontend', 'gw-backend', 'api-health']


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