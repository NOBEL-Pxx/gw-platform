#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_zkb_env_creds.py - R6.101: verify zkb.py parse_creds() env-var path.

WHY THIS EXISTS:
  zkb.py:74 originally hardcoded a Windows-only path for creds parsing,
  making zsmoke.yml CI workflow un-runnable on Linux runners. R6.101
  refactor adds env-var path (ZJLAB_*) with file fallback for Windows dev.

IRON RULES TESTED:
  - r678-classifier-boundary: these tests verify READ-ONLY behavior, no SSH.
  - Backwards compatibility: existing zkb.py users must still get creds
    when no env vars set.

DESIGN NOTE (R6.101 review):
  Test fixture is a SYNTHETIC sync-to-zjlab-style file with placeholder
  values, NOT the real one. The real file is intentionally excluded to
  avoid embedding production creds in this test source.

RUN:
  cd D:\AliCPT\scripts\tests
  python test_zkb_env_creds.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

if 'zkb' in sys.modules:
    del sys.modules['zkb']
from zkb import parse_creds

TEST_ENV = {
    'ZJLAB_BASTION_HOST':     'bastion.test.example.com',
    'ZJLAB_BASTION_PORT':     '60022',
    'ZJLAB_BASTION_USER':     'bastion_user_test',
    'ZJLAB_BASTION_PASSWORD': 'bastion_pass_TEST_ONLY',
    'ZJLAB_SERVER_HOST':      'server.test.example.com',
    'ZJLAB_SERVER_PORT':      '22',
    'ZJLAB_SERVER_USER':      'zjlab_user_test',
    'ZJLAB_SERVER_PASSWORD':  'srv_pass_TEST_ONLY',
    'ZJLAB_REMOTE_ROOT':      '/srv/root_test',
}

FIXTURE_LINES = [
    "#!/usr/bin/env python3",
    "# Synthetic fixture - placeholder values only",
    "BASTION = ('fixture.bastion.example.com', 11111, 'fixture_b_user', 'fixture_b_pass')",
    "SERVER  = ('fixture.server.example.com', 2222, 'fixture_s_user', 'fixture_s_pass')",
    "REMOTE_ROOT = '/fixture/remote_root'",
    "MODE = 'full'",
]
FIXTURE_CONTENT = "\n".join(FIXTURE_LINES) + "\n"

FIXTURE_EXPECTED_BASTION = ('fixture.bastion.example.com', 11111, 'fixture_b_user', 'fixture_b_pass')
FIXTURE_EXPECTED_SERVER  = ('fixture.server.example.com', 2222, 'fixture_s_user', 'fixture_s_pass')
FIXTURE_EXPECTED_ROOT    = '/fixture/remote_root'


class _FixtureTestCase(unittest.TestCase):
    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in TEST_ENV}
        for k in TEST_ENV:
            os.environ.pop(k, None)
        fd, path = tempfile.mkstemp(suffix='.py', prefix='sync_fixture_')
        os.close(fd)
        self.fixture_path = Path(path)
        self.fixture_path.write_text(FIXTURE_CONTENT, encoding='utf-8')

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            self.fixture_path.unlink()
        except OSError:
            pass


class TestParseCredsEnvVarPath(_FixtureTestCase):
    def test_env_vars_all_set_returns_env_tuples(self):
        for k, v in TEST_ENV.items():
            os.environ[k] = v
        bad_path = Path(r'C:\does\not\exist\sync-to-zjlab.py')
        bastion, server, remote_root = parse_creds(bad_path)
        self.assertEqual(bastion, (
            'bastion.test.example.com', 60022, 'bastion_user_test', 'bastion_pass_TEST_ONLY',
        ))
        self.assertEqual(server, (
            'server.test.example.com', 22, 'zjlab_user_test', 'srv_pass_TEST_ONLY',
        ))
        self.assertEqual(remote_root, '/srv/root_test')

    def test_env_vars_bastion_only_raises(self):
        os.environ['ZJLAB_BASTION_HOST'] = 'partial.test.example.com'
        os.environ['ZJLAB_BASTION_PORT'] = '12345'
        os.environ['ZJLAB_BASTION_USER'] = 'partial_user'
        os.environ['ZJLAB_BASTION_PASSWORD'] = 'partial_pass'
        with self.assertRaises(RuntimeError) as ctx:
            parse_creds(self.fixture_path)
        self.assertIn('Partial ZJLAB_', str(ctx.exception))

    def test_env_vars_server_only_raises(self):
        os.environ['ZJLAB_SERVER_HOST'] = 'srv.test.example.com'
        os.environ['ZJLAB_SERVER_PORT'] = '2222'
        os.environ['ZJLAB_SERVER_USER'] = 'srv_user'
        os.environ['ZJLAB_SERVER_PASSWORD'] = 'srv_pass'
        os.environ['ZJLAB_REMOTE_ROOT'] = '/srv/root'
        with self.assertRaises(RuntimeError) as ctx:
            parse_creds(self.fixture_path)
        self.assertIn('Partial ZJLAB_', str(ctx.exception))

    def test_no_env_vars_falls_back_to_file(self):
        for k in TEST_ENV:
            os.environ.pop(k, None)
        bastion, server, remote_root = parse_creds(self.fixture_path)
        self.assertEqual(bastion, FIXTURE_EXPECTED_BASTION)
        self.assertEqual(server, FIXTURE_EXPECTED_SERVER)
        self.assertEqual(remote_root, FIXTURE_EXPECTED_ROOT)

    def test_env_path_works_with_nonexistent_file(self):
        for k, v in TEST_ENV.items():
            os.environ[k] = v
        bad_path = Path(r'C:\nonexistent\path\sync-to-zjlab.py')
        bastion, server, remote_root = parse_creds(bad_path)
        self.assertEqual(bastion[0], 'bastion.test.example.com')


class TestEnvPathPortType(_FixtureTestCase):
    def test_env_port_cast_to_int(self):
        for k, v in TEST_ENV.items():
            os.environ[k] = v
        bastion, server, _ = parse_creds(Path(r'C:\nonexistent'))
        self.assertIsInstance(bastion[1], int)
        self.assertIsInstance(server[1], int)
        self.assertEqual(bastion[1], 60022)
        self.assertEqual(server[1], 22)


class TestEmptyStringRejection(_FixtureTestCase):
    """R6.101 review fix (SECURITY MEDIUM): empty-string env vars must be rejected."""

    def test_empty_string_bastion_host_raises(self):
        # Set 8 vars + ZJLAB_BASTION_HOST='' (empty)
        os.environ['ZJLAB_BASTION_HOST'] = ''   # <-- the bypass
        os.environ['ZJLAB_BASTION_PORT'] = '60022'
        os.environ['ZJLAB_BASTION_USER'] = 'u'
        os.environ['ZJLAB_BASTION_PASSWORD'] = 'p'
        os.environ['ZJLAB_SERVER_HOST'] = 'srv'
        os.environ['ZJLAB_SERVER_PORT'] = '22'
        os.environ['ZJLAB_SERVER_USER'] = 'su'
        os.environ['ZJLAB_SERVER_PASSWORD'] = 'sp'
        os.environ['ZJLAB_REMOTE_ROOT'] = '/r'
        with self.assertRaises(RuntimeError) as ctx:
            parse_creds(self.fixture_path)
        self.assertIn('Partial ZJLAB_', str(ctx.exception))

    def test_empty_string_remote_root_raises(self):
        for k, v in TEST_ENV.items():
            os.environ[k] = v
        os.environ['ZJLAB_REMOTE_ROOT'] = ''  # <-- the bypass
        with self.assertRaises(RuntimeError) as ctx:
            parse_creds(self.fixture_path)
        self.assertIn('Partial ZJLAB_', str(ctx.exception))


class TestMalformedFile(_FixtureTestCase):
    def test_file_without_bastion_raises(self):
        self.fixture_path.write_text(
            "#!/usr/bin/env python3\nSERVER = ('x', 22, 'u', 'p')\nREMOTE_ROOT = '/r'\n",
            encoding='utf-8',
        )
        with self.assertRaises(RuntimeError) as ctx:
            parse_creds(self.fixture_path)
        self.assertIn('Failed to parse creds', str(ctx.exception))


if __name__ == '__main__':
    unittest.main(verbosity=2)
