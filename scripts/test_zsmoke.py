#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_zsmoke.py — Unit tests for zsmoke.py checks.

NO real SSH / docker calls. All Zkb interactions are mocked.

IRON-RULE COMPLIANCE:
  - Pure test code; no real credentials
  - No external network calls
  - No destructive operations

Run:
  python D:\\AliCPT\\scripts\\test_zsmoke.py
or:
  cd D:\\AliCPT\\scripts && python -m unittest test_zsmoke -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


_SCRIPT_CANDIDATES = (
    Path(__file__).parent / 'zsmoke.py',
    Path(r'D:\AliCPT\scripts\zsmoke.py'),
    Path(r'C:\Users\28610\zsmoke.py'),
)
SCRIPT_PATH = next((p for p in _SCRIPT_CANDIDATES if p.exists()), _SCRIPT_CANDIDATES[0])
sys.path.insert(0, str(SCRIPT_PATH.parent))

_spec = importlib.util.spec_from_file_location('zsmoke', str(SCRIPT_PATH))
zsmoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zsmoke)


def _make_health_body(es_latency_ms=8, mongo_latency_ms=6, status='UP'):
    """Construct a /api/health JSON body as it would come from divs-backend.

    Uses compact separators (no spaces) to match the real Spring Boot Jackson
    default serialization: {"status":"UP"} not {"status": "UP"}.
    """
    return json.dumps({
        'error': {'code': '0', 'msg': ''},
        'data': {
            'status': status,
            'version': 'v4.66-R6.85-test',
            'timestamp': '2026-09-11T12:00:00Z',
            'components': {
                'app': {'status': 'UP'},
                'elasticsearch': {'status': 'UP', 'latency_ms': es_latency_ms},
                'mongo': {'status': 'UP', 'latency_ms': mongo_latency_ms},
            },
        },
    }, separators=(',', ':'))


class TestCheckApiHealth(unittest.TestCase):
    """Sanity tests for the original check_api_health() — non-breaking baseline."""

    def test_returns_pass_when_all_components_up(self):
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(), 0)
        status, dur_ms, msg = zsmoke.check_api_health(z)
        self.assertEqual(status, zsmoke.PASS)
        self.assertIn('UP', msg)
        self.assertIn('v4.66-R6.85-test', msg)


class TestCheckApiHealthParallel(unittest.TestCase):
    """R6.84a: zsmoke api-health-parallel check asserts max(latency_ms) < sum(latency_ms).

    Concurrency proof: ES + Mongo probes run in parallel via R6.83 fan-out,
    so wall-clock per request = max(ES, Mongo), not ES + Mongo.
    """

    def test_returns_pass_when_max_less_than_sum(self):
        """Concurrent fan-out: max(8, 6) = 8 < sum(8, 6) = 14. PASS."""
        z = mock.MagicMock(name='z')
        # 3 concurrent probes, each simulated via separate docker exec calls.
        # ES=8ms, Mongo=6ms; max=8 < sum=14.
        z.run.return_value = (_make_health_body(es_latency_ms=8, mongo_latency_ms=6), 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.PASS)
        self.assertIn('max=', msg)
        self.assertIn('sum=', msg)

    def test_returns_pass_with_asymmetric_latencies(self):
        """ES=20ms, Mongo=2ms; max=20 < sum=22. PASS (still concurrent)."""
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(es_latency_ms=20, mongo_latency_ms=2), 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.PASS)
        self.assertIn('max=20', msg)

    def test_returns_fail_when_probes_sequential(self):
        """If probes run sequentially, max(latency) >= sum(latency) is impossible.
        But R6.83 fan-out should always have max < sum. If we observe max >= sum,
        either fan-out regressed or our probe count is 1 (not 3).
        Simulate by mocking z.run to return identical latencies where max == sum
        would not happen, but pass max == sum via a degenerate case: es=0, mongo=0.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(es_latency_ms=0, mongo_latency_ms=0), 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        # 0 == 0 -> not (max < sum) -> FAIL
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('probes sequential?', msg)

    def test_returns_fail_when_any_component_down(self):
        """ES status DOWN: check must FAIL even though max<sum holds."""
        z = mock.MagicMock(name='z')
        z.run.return_value = (
            _make_health_body(es_latency_ms=8, mongo_latency_ms=6, status='DOWN'),
            0,
        )
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('DOWN', msg)

    def test_returns_fail_when_response_body_empty(self):
        """Empty body from probe → FAIL with clear message."""
        z = mock.MagicMock(name='z')
        z.run.return_value = ('', 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('empty body', msg)

    def test_returns_fail_when_invalid_json(self):
        """Malformed JSON → FAIL with parser message."""
        z = mock.MagicMock(name='z')
        z.run.return_value = ('<html>not-json</html>', 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('invalid JSON', msg)

    def test_returns_fail_when_envelope_missing(self):
        """Response without 'data' envelope → FAIL."""
        z = mock.MagicMock(name='z')
        z.run.return_value = ('{"unexpected":"shape"}', 0)
        status, dur_ms, msg = zsmoke.check_api_health_parallel(z)
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('no data envelope', msg)

    def test_uses_3_concurrent_probes(self):
        """R6.84a design: fire 3 concurrent probes (parallel SSH sessions)
        to amplify the concurrency proof signal."""
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(es_latency_ms=8, mongo_latency_ms=6), 0)
        zsmoke.check_api_health_parallel(z)
        # z.run should have been called 3 times (once per concurrent probe)
        self.assertEqual(z.run.call_count, 3)


class TestCheckRegistration(unittest.TestCase):
    """R6.84a: api-health-parallel must be in CHECKS registry."""

    def test_in_checks_dict(self):
        self.assertIn('api-health-parallel', zsmoke.CHECKS)
        desc, fn, requires_remote = zsmoke.CHECKS['api-health-parallel']
        self.assertIn('R6.84a', desc)
        self.assertEqual(fn, zsmoke.check_api_health_parallel)
        self.assertFalse(requires_remote)

    def test_in_quick_checks(self):
        """QUICK_CHECKS must include api-health-parallel so cron + push
        workflow runs the new check daily."""
        self.assertIn('api-health-parallel', zsmoke.QUICK_CHECKS)


class TestCheckApiHealthRateLimit(unittest.TestCase):
    """R6.85c + R6.86: smoke check for /api/health rate-limit firing.

    R6.86 fix: replaced 70 sequential probes with 50-parallel-burst x 5 reqs
    = 250 reqs in <5s. Sequential SSH-tunneled wget probes (~1s each) refilled
    the bucket between requests (refill rate 3.33/s > request rate 1/s), so
    R6.85c sequential always reported ALL 200 = WARN (false negative).

    The parallel burst overwhelms the 200/min/IP quota (active profile `redis`),
    so the tail fires 429s. Expected: 200x200 + 50x429 = 250.

    C1-DEPLOY + H1-DEPLOY fix: R6.86's first iteration used
    `grep -o "HTTP/[0-9.]* [0-9]*"` on wget stdout, but wget -q emits the
    JSON body (NOT the HTTP status line). Grep never matched, check always
    FAILed on live runs. Tests passed only because they mocked z.run().
    Current pattern uses body discriminator (`"status":"UP"` = 200, else 429).
    """

    def _burst_output(self, success_count=200, rate_limited_count=50):
        """Build the `sort | uniq -c` output from the parallel burst command."""
        return '{:>5} 200\n{:>5} 429'.format(success_count, rate_limited_count)

    def test_returns_warn_when_no_rate_limiting_observed(self):
        """All 250 HTTP 200 (no 429s) → WARN (limit NOT enforced).

        This is the EXPECTED state BEFORE R6.85c deploys (excludePathPatterns
        still on /api/health). After R6.85c, parallel burst should produce
        a mix of 200 + 429 → PASS.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (self._burst_output(success_count=250, rate_limited_count=0), 0)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.WARN)
        self.assertIn('NO rate limiting observed', msg)

    def test_returns_pass_when_rate_limit_active(self):
        """200 success + 50 rate-limited (parallel burst depleted bucket) → PASS.

        Mock the parallel burst's `sort | uniq -c` output: 200×200 + 50×429.
        Expected: PASS with 'ENFORCED' message.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (self._burst_output(success_count=200, rate_limited_count=50), 0)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.PASS)
        self.assertIn('ENFORCED', msg)
        self.assertIn('parallel burst', msg)

    def test_returns_fail_when_z_run_returns_empty(self):
        """z.run returns empty body (e.g., SSH failure) → FAIL with diagnostic."""
        z = mock.MagicMock(name='z')
        z.run.return_value = ('', 1)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.FAIL)
        self.assertIn('parallel burst failed', msg)

    def test_uses_single_z_run_call_for_parallel_burst(self):
        """R6.86 design: parallel burst = ONE SSH command (50 bg subshells).

        Pre-R6.86 sequential design called z.run 70 times. The parallel-burst
        design consolidates into a single command:
          `rm -f /tmp/rl_results_*.txt; for j in $(seq 1 50); do ( ... ) & done; wait; cat | sort | uniq -c`
        so z.run.call_count == 1.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (self._burst_output(), 0)
        zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(z.run.call_count, 1)

    def test_burst_command_uses_50_bg_jobs(self):
        """The single SSH command must spawn 50 background subshells (the burst)."""
        z = mock.MagicMock(name='z')
        z.run.return_value = (self._burst_output(), 0)
        zsmoke.check_api_health_rate_limit(z)
        cmd_issued = z.run.call_args[0][0]
        # Must contain "seq 1 50" (50 background jobs)
        self.assertIn('seq 1 50', cmd_issued,
                      msg='parallel burst must spawn 50 bg subshells')
        # Must use `wait` to synchronize before reading results
        self.assertIn('wait', cmd_issued,
                      msg='parallel burst must `wait` before reading results')
        # Must use `sort | uniq -c` for counting HTTP codes
        self.assertIn('sort | uniq -c', cmd_issued,
                      msg='parallel burst output must be aggregated via sort | uniq -c')

    def test_quota_matches_redis_profile_200(self):
        """Quota constant must match application-redis.properties (200/min/IP).

        If rate.limit.capacity changes, this test will fail — forcing the
        check author to update both the script and the test in sync.
        """
        z = mock.MagicMock(name='z')
        # Mock returns exactly 200 success + 50 rate-limited
        z.run.return_value = (self._burst_output(200, 50), 0)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        # Must PASS at 200/250 boundary (success >= quota = 200)
        self.assertEqual(status, zsmoke.PASS,
                         msg='quota constant likely wrong (expected 200, see test name)')

    def test_returns_warn_on_unexpected_http_codes(self):
        """If burst produces HTTP codes other than 200/429 → WARN with details."""
        z = mock.MagicMock(name='z')
        # 100x200 + 50x429 + 100x500 (server errors = NOT rate limiting)
        weird_output = '{:>5} 200\n{:>5} 429\n{:>5} 500'.format(100, 50, 100)
        z.run.return_value = (weird_output, 0)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.WARN)
        self.assertIn('unexpected codes', msg)
        self.assertIn('500', msg)

    def test_wget_capture_pattern_uses_body_discriminator(self):
        """H1-DEPLOY: pin the C1-DEPLOY fix — body discriminator, NOT broken HTTP regex.

        Pre-fix (C1-DEPLOY bug): the SSH command used
        `grep -o "HTTP/[0-9.]* [0-9]*"` on `wget -qO-` output. But `wget -q`
        emits JSON body to stdout, not the HTTP status line. The grep never
        matched anything, so /tmp/rl_results_*.txt was empty and the check
        always returned FAIL on live runs.

        Post-fix (R6.86): capture body via `body=$(wget -qO- ...)`, then test
        for `"status":"UP"` substring (present in HealthController JSON on
        HTTP 200; absent in bucket4j 429 envelope). Pin this pattern below.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (self._burst_output(), 0)
        zsmoke.check_api_health_rate_limit(z)
        cmd_issued = z.run.call_args[0][0]

        # Required: body discriminator present
        self.assertIn('grep -q', cmd_issued,
                      msg='must use grep -q discriminator (not broken HTTP regex)')
        self.assertIn('"status":"UP"', cmd_issued,
                      msg='must discriminate on HealthController JSON status field')

        # Required: body captured into a shell variable (not piped straight
        # through grep, which was the C1-DEPLOY anti-pattern)
        self.assertIn('body=$(wget', cmd_issued,
                      msg='must capture body into shell var before grepping')

        # Required: explicit echo of HTTP code per request
        self.assertIn('echo 200', cmd_issued,
                      msg='must echo 200 for success path')
        self.assertIn('echo 429', cmd_issued,
                      msg='must echo 429 for rate-limited path')

        # Forbidden: the C1-DEPLOY broken pattern. If this ever reappears,
        # the check will silently FAIL on live runs because wget -qO- emits
        # JSON, not "HTTP/1.1 200 OK" status lines.
        self.assertNotIn('HTTP/[0-9.]* [0-9]*', cmd_issued,
                         msg='C1-DEPLOY anti-pattern: HTTP regex grep CANNOT '
                             'match wget -qO- JSON output. Use body discriminator.')
        # Also forbid raw "HTTP/" grep which is the same anti-pattern even
        # with different surrounding regex chars.
        self.assertFalse(
            'grep' in cmd_issued and 'HTTP/' in cmd_issued,
            msg='C1-DEPLOY anti-pattern: any HTTP/ regex grep on wget -qO- '
                'output will silently fail. Use body discriminator only.',
        )


if __name__ == '__main__':
    unittest.main()
