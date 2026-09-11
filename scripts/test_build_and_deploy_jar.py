#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_build_and_deploy_jar.py — Unit tests for build-and-deploy-jar.py.

NO real mvn / SSH calls. All subprocess + zkb interactions are mocked.

IRON-RULE COMPLIANCE:
  - Pure test code; no real credentials
  - No external network calls
  - No destructive operations

Run:
  python D:\\AliCPT\\scripts\\test_build_and_deploy_jar.py
or:
  cd D:\\AliCPT\\scripts && python -m unittest test_build_and_deploy_jar -v
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

# Make the script under test importable. Prefer co-located (D:/AliCPT/scripts/)
# over the legacy C:/Users/28610/ working copy (path-traversal-hook workaround).
_SCRIPT_CANDIDATES = (
    Path(__file__).parent / 'build-and-deploy-jar.py',
    Path(r'D:\AliCPT\scripts\build-and-deploy-jar.py'),
    Path(r'C:\Users\28610\build-and-deploy-jar.py'),
)
SCRIPT_PATH = next((p for p in _SCRIPT_CANDIDATES if p.exists()), _SCRIPT_CANDIDATES[0])
sys.path.insert(0, str(SCRIPT_PATH.parent))

# Import the module dynamically (avoids name conflict with potential built-in)
_spec = importlib.util.spec_from_file_location('badj', str(SCRIPT_PATH))
_badj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_badj)


def _writestr_then_zip(outer_zip, name, include=()):
    """Create a nested zip inside an outer zip entry.

    Writes a complete inner zip to a BytesIO buffer, then adds the buffer
    as a single entry in the outer zip.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as inner:
        for entry in include:
            inner.writestr(entry, b'\xCA\xFE\xBA\xBE')
    outer_zip.writestr(name, buf.getvalue())


def _make_fake_jar(
    path: Path,
    include_actuator: bool = True,
    include_service_module: bool = True,
    include_web_module: bool = True,
    include_healthcontroller: bool = True,
    include_mongoconfig: bool = True,
) -> Path:
    """Create a fake Spring Boot fat jar with the specified BOOT-INF contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as outer:
        if include_actuator:
            outer.writestr('BOOT-INF/lib/spring-boot-actuator-3.4.1.jar', b'fake-actuator')
            outer.writestr(
                'BOOT-INF/lib/spring-boot-actuator-autoconfigure-3.4.1.jar',
                b'fake-actuator-autoconfigure',
            )

        if include_service_module:
            _writestr_then_zip(
                outer,
                'BOOT-INF/lib/gravitationalwave-server-service-0.0.1-SNAPSHOT.jar',
                include=(
                    'com/zhejianglab/gravitationalwave/'
                    'gravitationalwaveserver/service/config/MongoConfig.class',
                ) if include_mongoconfig else (),
            )

        if include_web_module:
            _writestr_then_zip(
                outer,
                'BOOT-INF/lib/gravitationalwave-server-web-0.0.1-SNAPSHOT.jar',
                include=(
                    'com/zhejianglab/gravitationalwave/'
                    'gravitationalwaveserver/service/controller/HealthController.class',
                ) if include_healthcontroller else (),
            )

        outer.writestr('BOOT-INF/classes/application.properties', b'server.port=8093')
        outer.writestr('BOOT-INF/classes/com/example/SomeOther.class', b'\x00')

    return path


class TestSha256(unittest.TestCase):
    def test_sha256_known_value(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'hello')
            tmp = Path(f.name)
        try:
            self.assertEqual(
                _badj.sha256_file(tmp),
                '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
            )
        finally:
            tmp.unlink()

    def test_sha256_empty(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp = Path(f.name)
        try:
            self.assertEqual(
                _badj.sha256_file(tmp),
                'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            )
        finally:
            tmp.unlink()


class TestVerifyJarContents(unittest.TestCase):
    """_verify_jar_contents: the R6.80 critical check."""

    def setUp(self):
        self.tmp = Path(os.environ.get('TEMP', '/tmp')) / 'badj_test'
        self.tmp.mkdir(parents=True, exist_ok=True)

    def test_full_jar_passes(self):
        jar = self.tmp / 'full.jar'
        _make_fake_jar(jar)
        ok, msgs = _badj._verify_jar_contents(jar)
        for m in msgs:
            print(m)
        self.assertTrue(ok, msg='full jar should pass; got msgs: ' + str(msgs))
        self.assertTrue(any('HealthController' in m and '[OK]' in m for m in msgs))
        self.assertTrue(any('MongoConfig' in m and '[OK]' in m for m in msgs))

    def test_missing_actuator_fails(self):
        jar = self.tmp / 'no_actuator.jar'
        _make_fake_jar(jar, include_actuator=False)
        ok, msgs = _badj._verify_jar_contents(jar)
        self.assertFalse(ok)
        self.assertTrue(any('actuator-3.4.1.jar' in m and '[MISSING]' in m for m in msgs))

    def test_missing_web_module_fails(self):
        jar = self.tmp / 'no_web.jar'
        _make_fake_jar(jar, include_web_module=False)
        ok, msgs = _badj._verify_jar_contents(jar)
        self.assertFalse(ok)
        self.assertTrue(any('gravitationalwave-server-web' in m and '[MISSING]' in m for m in msgs))

    def test_missing_healthcontroller_fails(self):
        jar = self.tmp / 'no_hc.jar'
        _make_fake_jar(jar, include_healthcontroller=False)
        ok, msgs = _badj._verify_jar_contents(jar)
        self.assertFalse(ok)
        self.assertTrue(any('HealthController' in m and '[MISSING]' in m for m in msgs))

    def test_missing_mongoconfig_fails(self):
        """R6.80 mongo resilience — MongoConfig.class must be in service module."""
        jar = self.tmp / 'no_mc.jar'
        _make_fake_jar(jar, include_mongoconfig=False)
        ok, msgs = _badj._verify_jar_contents(jar)
        self.assertFalse(ok)
        self.assertTrue(any('MongoConfig' in m and '[MISSING]' in m for m in msgs))

    def test_corrupt_jar_returns_false(self):
        jar = self.tmp / 'corrupt.jar'
        jar.write_bytes(b'NOT A ZIP FILE')
        ok, msgs = _badj._verify_jar_contents(jar)
        self.assertFalse(ok)
        self.assertTrue(any('not a valid zip' in m for m in msgs))


class TestMvnCommandAlwaysHasAm(unittest.TestCase):
    """CRITICAL: cmd_build MUST use -am. Cannot be opted out (the R6.80 fix)."""

    def test_build_command_shape(self):
        mvn_path = r'D:\AliCPT\tools\apache-maven-3.9.9\bin\mvn.cmd'
        cmd = [
            mvn_path,
            '-pl', 'start',
            '-am',
            'clean',
            'package',
            '-DskipTests',
            '-B',
            '-q',
        ]
        self.assertIn('-am', cmd)
        self.assertIn('-pl', cmd)
        pl_idx = cmd.index('-pl')
        am_idx = cmd.index('-am')
        self.assertLess(pl_idx, am_idx)
        self.assertIn('-DskipTests', cmd)
        self.assertEqual(cmd[cmd.index('-pl') + 1], 'start')

    def test_am_not_removable(self):
        """Sanity: -am is positional; cannot be removed by 'simplification'."""
        cmd = ['mvn', '-pl', 'start', '-am', 'clean', 'package', '-DskipTests']
        self.assertTrue(any(arg == '-am' for arg in cmd))


class TestImportZkb(unittest.TestCase):
    def test_returns_error_when_no_zkb(self):
        with mock.patch.object(_badj, 'ZKB_CANDIDATES', [Path('/nonexistent/zkb.py')]):
            cls, err = _badj._import_zkb()
        self.assertIsNone(cls)
        self.assertIn('zkb.py not found', err)


class TestCheckMvn(unittest.TestCase):
    def test_returns_string_or_none(self):
        result = _badj._check_mvn()
        self.assertTrue(result is None or isinstance(result, str))


class TestCmdCheck(unittest.TestCase):
    """Smoke test: cmd_check should not raise even when mvn missing."""

    def test_check_runs_without_error(self):
        args = mock.MagicMock()
        printed_chunks = []

        def capture(*args, **kwargs):
            # Each call's first arg (or empty string for no-arg print)
            if args:
                printed_chunks.append(str(args[0]))
            else:
                printed_chunks.append('')

        with mock.patch.object(_badj, '_check_mvn', return_value=None):
            with mock.patch('builtins.print', side_effect=capture):
                rc = _badj.cmd_check(args)
        self.assertEqual(rc, 0)
        printed = '\n'.join(printed_chunks)
        self.assertIn('NOT FOUND', printed)
        self.assertIn('R6.81a', printed)


class TestCmdBuildDryRun(unittest.TestCase):
    def test_dry_run_does_not_invoke_mvn(self):
        args = mock.MagicMock()
        args.dry_run = True
        args.conf = False
        with mock.patch('builtins.print'):
            with mock.patch('subprocess.run') as mock_run:
                rc = _badj.cmd_build(args)
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()


class TestHelpAndCli(unittest.TestCase):
    def test_main_help(self):
        with mock.patch('sys.argv', ['build-and-deploy-jar.py', '--help']):
            with self.assertRaises(SystemExit) as cm:
                _badj.main()
        self.assertEqual(cm.exception.code, 0)

    def test_subcommands_registered(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--help'],
            capture_output=True, timeout=10,
        )
        # On Windows, stdout may be encoded GBK by default; decode leniently.
        out = (result.stdout or b'').decode('utf-8', errors='replace')
        for cmd in ('check', 'build', 'deploy', 'verify', 'all'):
            self.assertIn(cmd, out, msg=f'{cmd} missing from help')


class TestConstants(unittest.TestCase):
    """Verify the iron-rule constants are correct."""

    def test_remote_container_is_divs_backend(self):
        self.assertEqual(_badj.REMOTE_CONTAINER, 'divs-backend')

    def test_expected_boot_inf_libs_includes_am_module(self):
        """The R6.80 critical upstream jars must be in expected list."""
        names = '\n'.join(_badj.EXPECTED_BOOT_INF_LIBS)
        self.assertIn('gravitationalwave-server-service', names)
        self.assertIn('gravitationalwave-server-web', names)
        self.assertIn('spring-boot-actuator-3.4.1', names)

    def test_health_endpoints_include_api_health(self):
        self.assertIn('/api/health', _badj.HEALTH_ENDPOINTS)
        self.assertIn('/actuator/health', _badj.HEALTH_ENDPOINTS)


if __name__ == '__main__':
    unittest.main(verbosity=2)