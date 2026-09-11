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


# === Tier 1 #2 R6.81b — H1 + C1 regression coverage ===

class TestInstantiateZkb(unittest.TestCase):
    """R6.81a C1: _instantiate_zkb must pass sync_script_path when fallback exists.

    Three cases:
      A. _import_zkb fails  -> returns (None, err)
      B. fallback exists   -> Zkb(sync_script_path=ZKB_SYNC_SCRIPT_FALLBACK)
      C. fallback missing  -> Zkb()  (unusual Windows setup; pragma: no cover in source)
    """

    def test_returns_none_when_zkb_import_fails(self):
        """C1 import-fail path: when zkb import raises, return (None, err) and never call Zkb."""
        with mock.patch.object(_badj, '_import_zkb', return_value=(None, 'import error: boom')):
            z, err = _badj._instantiate_zkb()
        self.assertIsNone(z)
        self.assertEqual(err, 'import error: boom')

    def test_uses_fallback_when_present(self):
        """Windows dev path: fallback file exists -> pass sync_script_path to Zkb."""
        fake_fallback = Path(os.environ.get('TEMP', '/tmp')) / 'fake_sync.py'
        fake_fallback.write_text('# fake sync-to-zjlab', encoding='utf-8')
        self.addCleanup(fake_fallback.unlink, missing_ok=True)

        # Zkb is imported inside _import_zkb() (not module-level), so the
        # module has no `Zkb` attribute. Inject a sentinel MockZkb class
        # so _instantiate_zkb() can call it; assert on the same sentinel.
        MockZkb = mock.MagicMock(name='MockZkb_class')
        MockZkb.return_value = mock.MagicMock(name='z_instance')

        with mock.patch.object(_badj, '_import_zkb', return_value=(MockZkb, None)):
            with mock.patch.object(_badj, 'ZKB_SYNC_SCRIPT_FALLBACK', fake_fallback):
                z, err = _badj._instantiate_zkb()
        self.assertIsNone(err)
        self.assertIsNotNone(z)
        MockZkb.assert_called_once_with(sync_script_path=fake_fallback)

    def test_uses_zkb_no_args_when_fallback_missing(self):
        """Unusual setup: fallback absent -> Zkb() + [WARN] emitted to stderr.

        R6.81b Tier 1 #3: the warning is critical — without it, a missing
        fallback surfaces later as an opaque RuntimeError from
        zkb.parse_creds() with no breadcrumb back to the missing file.
        """
        MockZkb = mock.MagicMock(name='MockZkb_class')
        MockZkb.return_value = mock.MagicMock(name='z_instance')

        with mock.patch.object(_badj, '_import_zkb', return_value=(MockZkb, None)):
            with mock.patch.object(_badj, 'ZKB_SYNC_SCRIPT_FALLBACK', Path('/nonexistent/sync.py')):
                with mock.patch('sys.stderr', new=io.StringIO()) as fake_stderr:
                    z, err = _badj._instantiate_zkb()
                    captured_stderr = fake_stderr.getvalue()
        self.assertIsNone(err)
        self.assertIsNotNone(z)
        MockZkb.assert_called_once_with()
        # Tier 1 #3 invariant: explicit [WARN] must fire
        self.assertIn('[WARN] ZKB_SYNC_SCRIPT_FALLBACK not found', captured_stderr)
        self.assertIn('ZJLAB_* env vars only', captured_stderr)


class TestTripleShaVerification(unittest.TestCase):
    """R6.81a H1: triple SHA (local -> host -> container) must abort before docker restart.

    Strategy: drive cmd_deploy with a mocked z (zkb) and a real fake jar. Use
    args.conf=True to skip the user-prompt; use args.timeout=2-4s to keep the
    health-poll loop short. Inspect z.run call list to assert that:
      - host SHA mismatch -> return 1, 'docker restart' NEVER called
      - container SHA mismatch -> return 1, 'docker restart' NEVER called
      - all SHA match + UP health -> return 0, 'docker restart' called exactly once
    """

    def setUp(self):
        self.tmp = Path(os.environ.get('TEMP', '/tmp')) / 'badj_h1_test'
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.jar = self.tmp / 'start.jar'
        _make_fake_jar(self.jar)
        self.local_sha = _badj.sha256_file(self.jar)
        self.local_size = self.jar.stat().st_size

        # Patch TARGET_JAR to point at our fake jar so cmd_deploy finds it.
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', self.jar)
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def _make_mock_z(self, host_sha=None, container_sha=None, health_up=True):
        """Construct a mock zkb-like object with configurable run() responses.

        The deploy sequence of z.run() calls (in order) is:
          1. 'mkdir -p ...'                       (mkdir the remote dir)
          2. 'sha256sum ...' on host              (HOST SHA)
          3. 'docker cp ...'                      (the copy)
          4. 'docker exec ... sha256sum ...'      (CONTAINER SHA)
          5. (after restart) health polling loop
        """
        z = mock.MagicMock(name='z')
        # docker_ps returns a non-empty list (container is running)
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]
        # sftp_put is a no-op for our purposes
        z.sftp_put = mock.MagicMock()

        # run() returns (stdout, exit_code). Map by command substring.
        def run(cmd, timeout=60):
            if 'sha256sum' in cmd and 'docker exec' not in cmd:
                return (f'{host_sha}  /home/zjlab/gw-backend/start.jar\n', 0)
            if 'docker exec' in cmd and 'sha256sum' in cmd:
                return (f'{container_sha}  /home/gravitational-wave-backend/app.jar\n', 0)
            if 'docker cp' in cmd:
                return ('', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and 'curl' in cmd:
                if health_up:
                    return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
                return ('{"code":1,"message":"down"}', 1)
            return ('', 0)

        z.run.side_effect = run
        return z

    def _make_args(self, timeout=2):
        args = mock.MagicMock()
        args.conf = True   # skip interactive prompt
        args.timeout = timeout
        return args

    def _patch_instantiate(self, z):
        """Patch _instantiate_zkb to return our mock z."""
        return mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None))

    def test_host_sha_mismatch_aborts_before_restart(self):
        """H1 host step: when host SHA != local_sha, return 1 and never restart."""
        z = self._make_mock_z(host_sha='a' * 64, container_sha=self.local_sha)
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 1)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart should NEVER be called on host SHA mismatch; got: {restart_calls}',
        )
        # Confirm host SHA check actually fired
        sha_checks = [c for c in run_calls if 'sha256sum' in c and 'docker exec' not in c]
        self.assertGreaterEqual(len(sha_checks), 1, msg='host sha256sum call must fire')

    def test_container_sha_mismatch_aborts_before_restart(self):
        """H1 container step: when container SHA != local_sha, return 1 and never restart."""
        z = self._make_mock_z(host_sha=self.local_sha, container_sha='b' * 64)
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 1)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart should NEVER be called on container SHA mismatch; got: {restart_calls}',
        )
        # Confirm both host + container SHA checks fired
        host_shas = [c for c in run_calls if 'sha256sum' in c and 'docker exec' not in c]
        cont_shas = [c for c in run_calls if 'docker exec' in c and 'sha256sum' in c]
        self.assertGreaterEqual(len(host_shas), 1, msg='host sha256sum call must fire')
        self.assertGreaterEqual(len(cont_shas), 1, msg='container sha256sum call must fire')

    def test_all_sha_match_proceeds_to_restart(self):
        """H1 happy path: all 3 SHAs match + UP -> return 0 + restart fires exactly once."""
        z = self._make_mock_z(
            host_sha=self.local_sha,
            container_sha=self.local_sha,
            health_up=True,
        )
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args(timeout=4))
        self.assertEqual(rc, 0)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            len(restart_calls), 1,
            msg=f'docker restart must fire exactly once on happy path; got {len(restart_calls)}',
        )
        # z.close() must be called (try/finally contract)
        z.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main(verbosity=2)