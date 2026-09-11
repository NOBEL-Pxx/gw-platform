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
    """R6.85c: smoke check for /api/health rate-limit firing."""

    def test_returns_warn_when_no_rate_limiting_observed(self):
        """70 successful + 0 rate-limited → WARN (limit NOT enforced).

        This is the EXPECTED state on zjlab BEFORE R6.85c deploys.
        After R6.85c, the same scenario should produce PASS or a different WARN.
        """
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(), 0)
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.WARN)
        self.assertIn('NO rate limiting observed', msg)

    def test_returns_pass_when_rate_limit_active(self):
        """First 60 succeed + last 10 rate-limited → PASS (limit enforced).

        Mock 70 sequential calls: first 60 return success body, last 10 return
        non-UP (rate-limited). Expected: success=60, rate_limited=10 → PASS.
        """
        z = mock.MagicMock(name='z')
        health_body = _make_health_body()
        rate_limited_body = '429 Too Many Requests'
        responses = [(health_body, 0)] * 60 + [(rate_limited_body, 1)] * 10
        z.run.side_effect = responses
        status, dur_ms, msg = zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(status, zsmoke.PASS)
        self.assertIn('ENFORCED', msg)

    def test_sends_70_total_requests(self):
        """R6.85c design: 70 sequential probes (quota=60 + buffer=10)."""
        z = mock.MagicMock(name='z')
        z.run.return_value = (_make_health_body(), 0)
        zsmoke.check_api_health_rate_limit(z)
        self.assertEqual(z.run.call_count, 70)


if __name__ == '__main__':
    unittest.main()
