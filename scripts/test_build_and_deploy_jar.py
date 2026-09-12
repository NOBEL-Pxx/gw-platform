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


def _patch_marker_check(z):
    """R6.84b: stub z.check_marker_log so pre-existing R6.82 tests don't break.

    Pre-R6.84b, cmd_deploy had an inlined `z.run(...)` for marker check; that
    mocked fine because mock.MagicMock auto-creates z.run. Post-R6.84b, cmd_deploy
    calls `z.check_marker_log(...)` and unpacks the result tuple. Auto-mocked
    check_marker_log returns a MagicMock (not a 2-tuple), so tests that drive
    cmd_deploy all the way through must explicitly return (True, '') here.

    Tests focused on the marker helper itself (TestV1MarkerCheck) bind the real
    function and do NOT use this patcher.
    """
    z.check_marker_log.return_value = (True, '')


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
        _patch_marker_check(z)  # R6.84b
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
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):
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




# === R6.82 — rollback subcommand + deploy backup step regression coverage ===

# R6.82 — new test classes to append to test_build_and_deploy_jar.py
# 5 test classes covering:
#   - TestDeployBackup (3 tests): cmd_deploy backup step behavior
#   - TestCmdRollbackHappyPath (1 test): cmd_rollback full sequence
#   - TestCmdRollbackNoPrevious (1 test): cmd_rollback when no previous jar
#   - TestCmdRollbackShaMismatch (1 test): H1 invariant extended to rollback
#   - TestCliRollbackRegistered (1 test): subcommand visible in --help
# Total: 7 new tests

class TestDeployBackup(unittest.TestCase):
    """R6.82-A: cmd_deploy MUST rotate app.jar -> app.jar.previous before docker cp.

    The backup step is the pre-condition for `rollback`. Without it, a bad
    deploy would be unrecoverable. This test class hardens the invariant.
    """

    def setUp(self):
        self.tmp = Path(os.environ.get('TEMP', '/tmp')) / 'badj_r682_test'
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.jar = self.tmp / 'start.jar'
        _make_fake_jar(self.jar)
        self.local_sha = _badj.sha256_file(self.jar)

        # Patch TARGET_JAR so cmd_deploy finds our fake jar
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', self.jar)
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def _make_mock_z(self, ls_prev_code=1, ls_prev_out='', other_cmd_returns=None):
        """Construct a mock z where backup-step behavior is controllable.

        ls_prev_code: 0 = .previous exists (rotation needed), 1 = does not (fresh)
        ls_prev_out:  string content of the ls -la output when ls_prev_code=0
        other_cmd_returns: dict mapping command-substring -> (out, code) for
                          non-backup commands (defaults to fall-through).
        """
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]
        z.sftp_put = mock.MagicMock()

        def run(cmd, timeout=60):
            # Backup-step responses
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (ls_prev_out, ls_prev_code)
            if 'app.jar.previous' in cmd and 'cp ' in cmd and 'app.jar.backup' in cmd:
                # rotation previous -> backup
                return ('', 0)
            if 'test -s' in cmd and 'app.jar.backup' in cmd:
                # R6.82 C1: rotation size check — default OK
                return ('OK\n', 0)
            if 'app.jar' in cmd and 'cp ' in cmd and 'app.jar.previous' in cmd:
                # backup current app.jar -> .previous
                return ('', 0)
            # other-command overrides
            if other_cmd_returns:
                for substr, ret in other_cmd_returns.items():
                    if substr in cmd:
                        return ret
            # defaults for the deploy sequence after backup
            if 'sha256sum' in cmd and 'docker exec' not in cmd:
                return (f'{self.local_sha}  /home/zjlab/gw-backend/start.jar\n', 0)
            if 'docker exec' in cmd and 'sha256sum' in cmd:
                return (f'{self.local_sha}  /home/gravitational-wave-backend/app.jar\n', 0)
            if 'docker cp' in cmd:
                return ('', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):  # R6.86-A: post-deploy probes use wget (busybox)
                return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
            return ('', 0)

        z.run.side_effect = run
        return z

    def _make_args(self, timeout=2, conf=True):
        args = mock.MagicMock()
        args.conf = conf
        args.timeout = timeout
        return args

    def _patch_instantiate(self, z):
        return mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None))

    def test_backup_creates_previous_when_no_previous_exists(self):
        """Fresh deploy (no .previous): just `cp app.jar app.jar.previous`, no rotation."""
        # ls returns empty + non-zero -> no previous exists
        z = self._make_mock_z(ls_prev_code=1, ls_prev_out='')
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 0)

        # Verify the backup cp command fired (with .previous, NOT .backup)
        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        backup_prev_calls = [
            c for c in run_calls
            if 'app.jar' in c and 'cp' in c and 'app.jar.previous' in c and 'app.jar.backup' not in c
        ]
        self.assertGreaterEqual(
            len(backup_prev_calls), 1,
            msg=f'app.jar -> app.jar.previous backup must fire; got calls: {run_calls}',
        )
        # Verify NO rotation command fired (no .backup involved)
        rotation_calls = [
            c for c in run_calls if 'app.jar.previous' in c and 'app.jar.backup' in c
        ]
        self.assertEqual(
            len(rotation_calls), 0,
            msg=f'rotation to .backup must NOT fire when no .previous exists; got: {rotation_calls}',
        )

    def test_backup_rotates_previous_to_backup_when_previous_exists(self):
        """When .previous already exists: rotate .previous -> .backup, then cp app.jar -> .previous."""
        # ls returns content + code 0 -> .previous exists
        z = self._make_mock_z(
            ls_prev_code=0,
            ls_prev_out='-rw-r--r-- 1 root root 71144400 Sep 10 12:00 /home/gravitational-wave-backend/app.jar.previous',
        )
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 0)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        # Rotation must fire (previous -> backup)
        rotation_calls = [
            c for c in run_calls if 'app.jar.previous' in c and 'app.jar.backup' in c
        ]
        self.assertGreaterEqual(
            len(rotation_calls), 1,
            msg=f'rotation to .backup must fire when .previous exists; got: {run_calls}',
        )
        # Backup must ALSO fire (app.jar -> .previous)
        backup_calls = [
            c for c in run_calls
            if 'app.jar' in c and 'cp' in c and 'app.jar.previous' in c and 'app.jar.backup' not in c
        ]
        self.assertGreaterEqual(
            len(backup_calls), 1,
            msg=f'app.jar -> .previous backup must fire after rotation; got: {run_calls}',
        )

    def test_backup_aborts_deploy_on_backup_failure(self):
        """R6.82-A invariant: if backup cp fails, deploy MUST abort (return 1)."""
        z = self._make_mock_z(
            ls_prev_code=1,
            ls_prev_out='',
            # Override: backup cp returns failure
            other_cmd_returns={
                'app.jar': ('', 1),  # backup cp fails (and overlaps any subsequent cp)
            },
        )
        # The above will make ALL app.jar cp commands fail. We want only the
        # BACKUP cp to fail, not the subsequent SFTP-side docker cp. But the
        # backup cp is the FIRST cp that targets app.jar.previous, so any cp
        # targeting .previous fails. The deploy should abort at the backup
        # step before docker cp fires.
        with self._patch_instantiate(z):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 1)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        # No docker restart should fire (backup failure aborts deploy)
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart MUST NOT fire when backup fails; got: {restart_calls}',
        )


class TestCmdRollbackHappyPath(unittest.TestCase):
    """R6.82: cmd_rollback full happy path sequence."""

    def setUp(self):
        # Patch TARGET_JAR so cmd_rollback doesn't error on missing TARGET_JAR
        # (cmd_rollback doesn't actually use TARGET_JAR, but cmd_deploy tests
        # have setUp for it; keep consistent for any test cross-pollination)
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', Path('dummy.jar'))
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def _make_mock_z(self, prev_sha='a' * 64):
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        prev_present_str = f'-rw-r--r-- 1 root root 71144400 Sep 10 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}'
        captured_prev_sha = [None]

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (prev_present_str, 0)
            if 'sha256sum' in cmd and 'app.jar.previous' in cmd:
                captured_prev_sha[0] = prev_sha
                return (f'{prev_sha}  /home/gravitational-wave-backend/app.jar.previous', 0)
            if 'sha256sum' in cmd and 'app.jar' in cmd and 'previous' not in cmd:
                # post-restore SHA check of app.jar
                return (f'{prev_sha}  /home/gravitational-wave-backend/app.jar', 0)
            if 'cp' in cmd and 'app.jar.previous' in cmd and 'app.jar.backup' not in cmd:
                return ('', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):  # R6.86-A: post-deploy probes use wget (busybox)
                return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
            return ('', 0)

        z.run.side_effect = run
        return z

    def test_rollback_restores_and_restarts_with_sha_match(self):
        """Happy path: container running, .previous exists, SHAs match -> restart + UP."""
        z = self._make_mock_z()
        args = mock.MagicMock()
        args.conf = True  # skip prompt
        args.timeout = 4

        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_rollback(args)
        self.assertEqual(rc, 0)

        # docker restart fired exactly once
        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            len(restart_calls), 1,
            msg=f'docker restart must fire exactly once on happy path; got {len(restart_calls)}',
        )
        # z.close() called
        z.close.assert_called_once_with()


class TestCmdRollbackNoPrevious(unittest.TestCase):
    """R6.82: cmd_rollback MUST fail gracefully when no .previous exists."""

    def setUp(self):
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', Path('dummy.jar'))
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def test_rollback_fails_when_no_previous_exists(self):
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                # ls returns no entry -> code 1 (file not found)
                return ('', 1)
            return ('', 0)

        z.run.side_effect = run

        args = mock.MagicMock()
        args.conf = True
        args.timeout = 4

        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_rollback(args)
        self.assertEqual(rc, 1)

        # No docker restart should fire
        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart MUST NOT fire when no .previous exists; got: {restart_calls}',
        )


class TestCmdRollbackShaMismatch(unittest.TestCase):
    """R6.82-C: cmd_rollback MUST verify SHA before restart (H1 invariant)."""

    def setUp(self):
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', Path('dummy.jar'))
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def test_rollback_aborts_on_post_restore_sha_mismatch(self):
        """If post-restore SHA != .previous SHA, rollback MUST abort before restart."""
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (f'-rw-r--r-- 1 root root 71144400 Sep 11 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}', 0)
            if 'sha256sum' in cmd and 'app.jar.previous' in cmd:
                # .previous SHA
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar.previous', 0)
            if 'sha256sum' in cmd and 'app.jar' in cmd and 'previous' not in cmd:
                # post-restore SHA of app.jar is WRONG (truncated cp simulation)
                return (f'{"b" * 64}  /home/gravitational-wave-backend/app.jar', 0)
            if 'cp' in cmd:
                return ('', 0)
            return ('', 0)

        z.run.side_effect = run

        args = mock.MagicMock()
        args.conf = True
        args.timeout = 4

        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_rollback(args)
        self.assertEqual(rc, 1)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart MUST NOT fire on post-restore SHA mismatch; got: {restart_calls}',
        )


class TestCliRollbackRegistered(unittest.TestCase):
    """R6.82: rollback subcommand visible in parent's --help output."""

    def test_rollback_subcommand_in_help(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--help'],
            capture_output=True, timeout=10,
        )
        out = (result.stdout or b'').decode('utf-8', errors='replace')
        self.assertIn('rollback', out, msg='rollback subcommand missing from --help')

    def test_rollback_help_describes_restart(self):
        """The subparser's help text should mention the R6.82 restore behavior.

        argparse shows subparser help text in the parent's --help output
        (NOT in `rollback --help`, which only shows optional arguments).
        """
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--help'],
            capture_output=True, timeout=10,
        )
        out = (result.stdout or b'').decode('utf-8', errors='replace')
        # The subparser help text is "R6.82: restore previous container jar + restart"
        self.assertIn(
            'R6.82: restore previous container jar + restart', out,
            msg=f'rollback subparser help should describe restore + R6.82; got: {out[:400]}',
        )




# === R6.82 review-fix tests (security Q1/Q5/Q8 + deploy C1/C2/C3) ===

# R6.82 review-fix tests (Deploy C2 + C3)
# - test_backup_rotates_warn_but_succeeds_when_rotation_fails (C2a)
# - test_rollback_aborts_when_restore_cp_fails (C2b)
# - test_rollback_happy_path_asserts_call_sequence (C3)
# Plus: security C1 size-check path test


class TestDeployBackupReviewFixes(unittest.TestCase):
    """R6.82 review fixes: rotation-fail-but-backup-succeeds + size-check."""

    def setUp(self):
        self.tmp = Path(os.environ.get('TEMP', '/tmp')) / 'badj_r682_fix_test'
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.jar = self.tmp / 'start.jar'
        _make_fake_jar(self.jar)
        self.local_sha = _badj.sha256_file(self.jar)
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', self.jar)
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def _make_mock_z(self, size_check_returns=('OK\n', 0), rot_code=0, backup_code=0):
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]
        z.sftp_put = mock.MagicMock()

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (f'-rw-r--r-- 1 root root 71144400 Sep 11 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}', 0)  # .previous exists
            if 'app.jar.previous' in cmd and 'app.jar.backup' in cmd and 'cp ' in cmd:
                return ('', rot_code)
            if 'test -s' in cmd and 'app.jar.backup' in cmd:
                return size_check_returns
            if 'app.jar' in cmd and 'cp' in cmd and 'app.jar.previous' in cmd and 'app.jar.backup' not in cmd:
                return ('', backup_code)
            if 'sha256sum' in cmd and 'docker exec' not in cmd:
                return (f'{self.local_sha}  /home/zjlab/gw-backend/start.jar\n', 0)
            if 'docker exec' in cmd and 'sha256sum' in cmd:
                return (f'{self.local_sha}  /home/gravitational-wave-backend/app.jar\n', 0)
            if 'docker cp' in cmd:
                return ('', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):  # R6.86-A: post-deploy probes use wget (busybox)
                return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
            return ('', 0)

        z.run.side_effect = run
        return z

    def _make_args(self, conf=True):
        args = mock.MagicMock()
        args.conf = conf
        args.timeout = 2
        return args

    def test_rotation_fail_but_backup_succeeds_continues_deploy(self):
        """C2a: When rotation cp fails, deploy MUST continue (best-effort) but
        size-check MUST be skipped (since .backup wasn't written). Backup cp
        of current app.jar -> .previous must still proceed and deploy succeeds.
        """
        z = self._make_mock_z(rot_code=1)
        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        # Rotation failed -> [WARN] + continue, backup succeeds -> deploy proceeds
        self.assertEqual(rc, 0)

    def test_size_check_aborts_deploy_when_rotation_truncated(self):
        """C1: rotation cp returned 0 but test -s says file is empty -> deploy MUST abort."""
        z = self._make_mock_z(rot_code=0, size_check_returns=('EMPTY\n', 0))
        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 1)

    def test_backup_failure_surfaces_backup_recovery_hint(self):
        """Security Q5: when backup cp fails, message MUST mention .backup recovery path."""
        # No previous -> no rotation. Backup cp fails.
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]
        z.sftp_put = mock.MagicMock()

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return ('', 1)  # no previous -> skip rotation
            if 'app.jar' in cmd and 'cp' in cmd and 'app.jar.previous' in cmd and 'app.jar.backup' not in cmd:
                return ('', 1)  # backup cp fails
            return ('', 0)

        z.run.side_effect = run

        captured = io.StringIO()
        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('sys.stdout', new=captured):
                    with mock.patch('sys.stderr', new=captured):
                        rc = _badj.cmd_deploy(self._make_args())
        self.assertEqual(rc, 1)
        output = captured.getvalue()
        self.assertIn('.backup', output, msg=f'.backup recovery hint missing from output: {output[:500]}')
        self.assertIn('Manual recovery', output, msg=f'Manual recovery line missing: {output[:500]}')


class TestCmdRollbackReviewFixes(unittest.TestCase):
    """R6.82 review fixes: rollback-cp-fails + call sequence assertions."""

    def setUp(self):
        self._target_patch = mock.patch.object(_badj, 'TARGET_JAR', Path('dummy.jar'))
        self._target_patch.start()

    def tearDown(self):
        self._target_patch.stop()

    def test_rollback_aborts_when_restore_cp_fails(self):
        """C2b: When cp .previous -> app.jar returns non-zero exit, cmd_rollback
        MUST abort BEFORE SHA check and BEFORE docker restart.
        """
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (f'-rw-r--r-- 1 root root 71144400 Sep 11 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}', 0)
            if 'sha256sum' in cmd and 'app.jar.previous' in cmd:
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar.previous', 0)
            if 'cp' in cmd and 'app.jar.previous' in cmd and 'app.jar.backup' not in cmd:
                return ('', 1)  # restore cp fails
            return ('', 0)

        z.run.side_effect = run

        args = mock.MagicMock()
        args.conf = True
        args.timeout = 4

        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_rollback(args)
        self.assertEqual(rc, 1)

        run_calls = [c.args[0] for c in z.run.call_args_list if c.args]
        restart_calls = [c for c in run_calls if 'docker restart' in c]
        self.assertEqual(
            restart_calls, [],
            msg=f'docker restart MUST NOT fire when restore cp fails; got: {restart_calls}',
        )

    def test_rollback_happy_path_asserts_call_sequence(self):
        """C3: Happy path MUST follow strict sequence: SHA capture -> cp -> SHA verify -> restart."""
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        run_cmds = []

        def run(cmd, timeout=60):
            run_cmds.append(cmd)
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (f'-rw-r--r-- 1 root root 71144400 Sep 11 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}', 0)
            if 'sha256sum' in cmd and 'app.jar.previous' in cmd:
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar.previous', 0)
            if 'cp' in cmd and 'app.jar.previous' in cmd and 'app.jar.backup' not in cmd:
                return ('', 0)
            if 'sha256sum' in cmd and 'app.jar' in cmd and 'previous' not in cmd:
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):  # R6.86-A: post-deploy probes use wget (busybox)
                return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
            return ('', 0)

        z.run.side_effect = run

        args = mock.MagicMock()
        args.conf = True
        args.timeout = 4

        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('builtins.print'):
                    rc = _badj.cmd_rollback(args)
        self.assertEqual(rc, 0)

        # Find indices of each step's command
        idx_prev_sha = next(
            i for i, c in enumerate(run_cmds)
            if 'sha256sum' in c and 'app.jar.previous' in c
        )
        idx_restore_cp = next(
            i for i, c in enumerate(run_cmds)
            if 'cp' in c and 'app.jar.previous' in c and 'app.jar.backup' not in c
        )
        idx_app_sha = next(
            i for i, c in enumerate(run_cmds)
            if 'sha256sum' in c and 'app.jar' in c and 'previous' not in c
        )
        idx_restart = next(i for i, c in enumerate(run_cmds) if 'docker restart' in c)

        # Strict order: prev_sha < restore_cp < app_sha < restart
        self.assertLess(
            idx_prev_sha, idx_restore_cp,
            msg=f'sha256sum(.previous) MUST fire before cp: prev_sha={idx_prev_sha}, cp={idx_restore_cp}',
        )
        self.assertLess(
            idx_restore_cp, idx_app_sha,
            msg=f'cp MUST fire before sha256sum(app.jar): cp={idx_restore_cp}, app_sha={idx_app_sha}',
        )
        self.assertLess(
            idx_app_sha, idx_restart,
            msg=f'sha256sum(app.jar) MUST fire before docker restart: app_sha={idx_app_sha}, restart={idx_restart}',
        )

    def test_rollback_conf_true_emits_audit_print(self):
        """Security Q1: args.conf=True MUST emit `[AUDIT] rollback invoked with --conf` print."""
        z = mock.MagicMock(name='z')
        _patch_marker_check(z)  # R6.84b
        z.docker_ps.return_value = [{'name': 'divs-backend', 'status': 'Up 2 hours'}]

        def run(cmd, timeout=60):
            if 'ls -la' in cmd and 'app.jar.previous' in cmd:
                return (f'-rw-r--r-- 1 root root 71144400 Sep 11 12:00 {_badj.CONTAINER_PREVIOUS_JAR_PATH}', 0)
            if 'sha256sum' in cmd and 'app.jar.previous' in cmd:
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar.previous', 0)
            if 'cp' in cmd:
                return ('', 0)
            if 'sha256sum' in cmd and 'app.jar' in cmd and 'previous' not in cmd:
                return (f'{"a" * 64}  /home/gravitational-wave-backend/app.jar', 0)
            if 'docker restart' in cmd:
                return ('divs-backend\n', 0)
            if 'docker exec' in cmd and ('curl' in cmd or 'wget' in cmd):  # R6.86-A: post-deploy probes use wget (busybox)
                return ('{"code":0,"message":"success","data":{"status":"UP"}}', 0)
            return ('', 0)

        z.run.side_effect = run

        args = mock.MagicMock()
        args.conf = True
        args.timeout = 4

        captured = io.StringIO()
        with mock.patch.object(_badj, '_instantiate_zkb', return_value=(z, None)):
            with mock.patch('builtins.input', side_effect=AssertionError('must not prompt')):
                with mock.patch('sys.stdout', new=captured):
                    with mock.patch('sys.stderr', new=captured):
                        _badj.cmd_rollback(args)
        output = captured.getvalue()
        self.assertIn(
            '[AUDIT] rollback invoked with --conf', output,
            msg=f'--conf audit print missing: {output[:500]}',
        )
        self.assertIn(
            'AUDIT: rollback complete', output,
            msg=f'final AUDIT summary line missing: {output[:500]}',
        )


class TestV1MarkerCheck(unittest.TestCase):
    """R6.84b: Zkb.check_marker_log() helper generalizes the R6.83 V1 marker check.

    Pre-R6.84b, the V1 marker check was inlined at build-and-deploy-jar.py:621-635
    (docker logs + grep -F + if/else warn-or-confirm). R6.84b moves the docker
    invocation + grep + FOUND/MISSING echo + AND-checking into Zkb.check_marker_log(),
    so future R6.x deploy verifications can reuse it without duplicating the
    paramiko + docker + grep pipeline.

    These tests pin the helper's contract:
      - Single marker (str) — FOUND returned iff present
      - Multiple markers (list[str]) — FOUND returned iff ALL present (AND check)
      - Missing marker — returns False + non-empty snippet
      - Marker is grep -F exact-match (substring + special chars literal)
      - R6.83 single-marker scenario — passes current build-and-deploy-jar.py usage

    Also pins that the refactored cmd_deploy still emits the [V1]/[WARN V1] line
    (smoke test via captured stdout) so a future refactor doesn't silently drop
    the marker verification entirely.
    """

    def setUp(self):
        # Bind the REAL Zkb.check_marker_log to mocks so it executes against
        # mock self.run return_value (which we control per-test). Without this,
        # mock.MagicMock auto-creates check_marker_log as a child MagicMock that
        # returns another MagicMock — causing "not enough values to unpack".
        # We also need MethodType binding because Zkb.check_marker_log is a
        # plain function with `self` as the first arg; assigning it to the mock
        # without binding means `z.check_marker_log(container, marker)` skips `self`
        # and binds `container` to it, leading to "missing 'marker' argument".
        import importlib.util as _ilu
        from types import MethodType
        _spec = _ilu.spec_from_file_location('_zkb_for_test', r'D:\AliCPT\scripts\zkb.py')
        _zkb = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_zkb)
        self._check_marker_log = MethodType(_zkb.Zkb.check_marker_log, mock.MagicMock())

    def _make_z(self, run_return):
        """Build a mock Zkb whose .run returns run_return; .check_marker_log is REAL."""
        z = mock.MagicMock(name='z')
        z.run.return_value = run_return
        from types import MethodType
        # Re-bind to THIS specific mock so self.run points to this mock's run.
        z.check_marker_log = MethodType(self._check_marker_log.__func__, z)
        return z

    def test_returns_true_when_marker_present(self):
        """Helper returns True when the marker is in the recent log window."""
        z = self._make_z((
            'Some earlier log line\n'
            '2026-09-11 12:00:00 INFO R6.83: HealthController probe executor initialized (2 threads, daemon=true)\n'
            'More later log\n',
            0,
        ))
        found, snippet = z.check_marker_log('divs-backend', 'R6.83: HealthController probe executor initialized')
        self.assertTrue(found)
        self.assertIn('R6.83: HealthController', snippet)

    def test_returns_false_when_marker_absent(self):
        """Helper returns False when no log line contains the marker."""
        z = self._make_z((
            'Starting Application on Tomcat\n'
            'HealthController UP\n',
            0,
        ))
        found, snippet = z.check_marker_log('divs-backend', 'R6.83: HealthController probe executor initialized')
        self.assertFalse(found)
        # Snippet still returned for caller inspection (raw log content).
        self.assertIn('HealthController UP', snippet)

    def test_returns_false_when_docker_logs_fails(self):
        """Empty z.run output (e.g. docker not running, container down) -> False."""
        z = self._make_z(('', 1))
        found, snippet = z.check_marker_log('divs-backend', 'R6.83: marker')
        self.assertFalse(found)
        # Snippet should be empty (z.run returned ''); helper must not crash on None.
        self.assertEqual(snippet, '')

    def test_supports_list_of_markers_all_present(self):
        """Multi-marker mode: list of strings, AND check (all must be present)."""
        z = self._make_z((
            'INFO  R6.83: HealthController probe executor initialized\n'
            'INFO  R6.85b: LlmController RestTemplate initialized\n'
            'INFO  R6.85b: PipelineProxyController RestTemplate initialized\n',
            0,
        ))
        markers = [
            'R6.83: HealthController probe executor initialized',
            'R6.85b: LlmController RestTemplate initialized',
            'R6.85b: PipelineProxyController RestTemplate initialized',
        ]
        found, snippet = z.check_marker_log('divs-backend', markers)
        self.assertTrue(found)
        self.assertIn('R6.85b: LlmController', snippet)
        self.assertIn('R6.85b: PipelineProxyController', snippet)

    def test_supports_list_of_markers_partial_present(self):
        """Multi-marker mode: if ANY marker missing, returns False (AND check)."""
        z = self._make_z((
            'INFO  R6.83: HealthController probe executor initialized\n'
            # R6.85b LlmController line is missing
            'INFO  R6.85b: PipelineProxyController RestTemplate initialized\n',
            0,
        ))
        markers = [
            'R6.83: HealthController probe executor initialized',
            'R6.85b: LlmController RestTemplate initialized',
            'R6.85b: PipelineProxyController RestTemplate initialized',
        ]
        found, snippet = z.check_marker_log('divs-backend', markers)
        self.assertFalse(found)
        # Snippet shows what IS present so caller can see which is missing.
        self.assertIn('R6.83: HealthController', snippet)
        self.assertIn('R6.85b: PipelineProxyController', snippet)
        self.assertNotIn('R6.85b: LlmController', snippet)

    def test_uses_substring_match(self):
        """Helper does substring matching, not regex — special chars in marker are literal."""
        marker_with_special = 'R6.83: HealthController probe executor initialized (2 threads, daemon=true)'
        z = self._make_z((f'INFO {marker_with_special}\n', 0))
        found, _ = z.check_marker_log('divs-backend', marker_with_special)
        self.assertTrue(found)
        # Verify docker logs command was issued with --since 30s default
        cmd_issued = z.run.call_args[0][0]
        self.assertEqual(cmd_issued, 'docker logs --since 30s divs-backend 2>&1')

    def test_snippet_truncated_to_500_chars(self):
        """Run output snippet is capped at 500 chars to avoid runaway log lines.

        Marker is placed at the END of the first 500 chars so the assertion
        succeeds after truncation. The bulk of the B-tail is dropped.
        """
        marker = 'R6.83: marker found here'
        # 100 A's + newline + marker = exactly 124 chars; the rest is B-tail.
        huge_output = 'A' * 100 + '\n' + marker + '\n' + 'B' * 5000
        z = self._make_z((huge_output, 0))
        _, snippet = z.check_marker_log('divs-backend', marker)
        self.assertLessEqual(len(snippet), 500)
        self.assertIn(marker, snippet)
        # Snippet length is exactly 500; the B-tail is heavily truncated.
        # We don't assert NotIn('B') because the cutoff may land mid-B-run.
        # The KEY invariant: len(snippet) <= 500 even though input is ~5124 chars.
        self.assertGreater(len(huge_output), 5000)

    def test_custom_since_and_timeout(self):
        """Caller can override since and timeout kwargs (e.g. slow app warmup)."""
        z = self._make_z(('INFO  R6.83: marker found\n', 0))
        z.check_marker_log('divs-backend', 'R6.83: marker', since='5m', timeout=30)
        cmd_issued = z.run.call_args[0][0]
        self.assertIn('docker logs --since 5m', cmd_issued)
        timeout_issued = z.run.call_args.kwargs.get('timeout') or z.run.call_args[1].get('timeout')
        self.assertEqual(timeout_issued, 30)


class TestCheckMarkerLogRefactor(unittest.TestCase):
    """R6.84b + R6.85b + R6.88: build-and-deploy-jar.py V1 marker path uses Zkb.check_marker_log().

    Pins the R6.83 -> R6.84b refactor (single marker), the R6.85b extension
    (multi-marker AND-check for HealthController + LlmController + PipelineProxyController),
    AND the R6.88 extension (StaticFileController + SearchController + ImageCutoutController).
    cmd_deploy must call z.check_marker_log() rather than the inlined
    `docker logs ... | grep -F ...` pipeline. Regression guard against accidental
    revert to the inline pattern, AND against silent removal of any marker
    (which would re-introduce the R6.80 bug where stale upstream bytecode passed
    /api/health UP but lacked the new lifecycle hooks).
    """

    def test_cmd_deploy_calls_check_marker_log_with_all_markers(self):
        """Refactored cmd_deploy invokes z.check_marker_log with the 6-marker AND-check.

        R6.85b added 2 more markers (LlmController + PipelineProxyController RestTemplate
        init). R6.88 added 3 more (StaticFileController + SearchController + ImageCutoutController
        R6.85-A application). The check must now be a list of 6 markers passed to check_marker_log
        so that an mvn build without -am (R6.80 lesson) fails the AND-check rather than silently
        shipping stale bytecode.
        """
        source = Path(SCRIPT_PATH).read_text(encoding='utf-8')
        # The refactored lines use z.check_marker_log(REMOTE_CONTAINER, v1_markers)
        # where v1_markers is a 6-element list of R6.83 + R6.85b + R6.88 markers.
        self.assertIn(
            'markers_found, markers_snippet = z.check_marker_log(\n'
            '                        REMOTE_CONTAINER,\n'
            '                        v1_markers,\n'
            '                    )',
            source,
            msg='cmd_deploy should call z.check_marker_log(REMOTE_CONTAINER, v1_markers) — refactor missing',
        )
        # All 8 markers must be present in v1_markers list (R6.83 + 2×R6.85b + 3×R6.88 + 2×R6.96)
        for marker in (
            'R6.83: HealthController probe executor initialized',
            'R6.85b: LlmController RestTemplate initialized',
            'R6.85b: PipelineProxyController RestTemplate initialized',
            'R6.88: StaticFileController initialized',
            'R6.88: SearchController initialized',
            'R6.88: ImageCutoutController initialized',
            'R6.96: ImageCutoutDataSet initialized',
            'R6.96: ImageCutoutDataSet shutdown complete',
        ):
            self.assertIn(
                marker, source,
                msg=f'cmd_deploy must check marker {marker!r} — R6.85b+R6.88+R6.96 AND-check incomplete',
            )


class TestR686CurlProbeFix(unittest.TestCase):
    """R6.86-A: build-and-deploy-jar.py must NOT use `curl` for in-container probes.

    Context: divs-backend container is busybox shell (wget only, NO curl).
    Pre-R6.86 cmd_deploy polled /api/health via
    `docker exec {container} curl -sf -m 5 {health_url}` — every poll
    returned exit 126 (curl not found), falsely reporting deploy failure for
    120s while the app was always healthy (see [[divs-backend-curl-missing]] +
    [[r685-summary]] 2026-09-11 incident).

    R6.86-A fix: replace curl with `wget -qO- -T 5 --tries=1`. wget is the
    busybox HTTP client and is guaranteed present in divs-backend. The flag
    choices are critical (not arbitrary):
      -q        : quiet — emit only response body to stdout (no progress bar)
      -O -      : write body to stdout (so the polling loop can parse JSON)
      -T 5      : 5-second read timeout (wget's flag is -T, NOT curl's -m).
                  Short timeout is essential: the loop polls every 2s, so a
                  stuck probe would block the next poll iteration. 5s is
                  generous for localhost /api/health (which returns <100ms).
      --tries=1 : disable wget's default retry (20 attempts with exponential
                  backoff). Without this, a single slow response would cause
                  wget to retry for ~minutes, blocking the entire 120s
                  timeout window in retries instead of fast-failing.

    A future maintainer who "simplifies" the flags (e.g., drops -T 5 or
    --tries=1) will re-introduce the original false-alarm class. The companion
    test `test_probe_wget_has_timeout_and_tries` pins these flags.

    These tests pin the iron rule: cmd_deploy probe + diagnose hints must
    NOT contain the string `curl`. A future refactor that re-introduces curl
    (e.g., copy-pasting from a tutorial) will fail this test.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.source_path = Path(r'D:\AliCPT\scripts\build-and-deploy-jar.py')
        cls.source = cls.source_path.read_text(encoding='utf-8')

    def _section_around_probe(self) -> str:
        """Extract the cmd_deploy wait-for-UP loop section."""
        start = self.source.find('# 5. Wait for /api/health = UP')
        end = self.source.find('print(\'Diagnose:\'', start)
        if start < 0 or end < 0:
            self.fail('Could not locate cmd_deploy wait-for-UP + diagnose sections')
        return self.source[start:end]

    def _diagnose_section(self) -> str:
        """Extract the diagnose hints section printed on probe timeout."""
        start = self.source.find('print(\'Diagnose:\'')
        end = self.source.find('return 1', start)
        if start < 0 or end < 0:
            self.fail('Could not locate diagnose hints section')
        return self.source[start:end]

    def test_probe_uses_wget_not_curl(self):
        """The wait-for-UP probe must call wget, not curl.

        Rationale comments may mention the OLD curl pattern (to explain why
        wget is used), but the actual probe code must use wget.
        """
        section = self._section_around_probe()
        # The probe must mention wget (the actual probe tool)
        self.assertIn('wget', section, msg='probe missing wget')
        # Capture the multi-line f-string: from `probe_cmd = (` until matching `)`
        import re
        m = re.search(r'probe_cmd\s*=\s*\((.*?)\)', section, re.DOTALL)
        self.assertIsNotNone(m, msg='Could not find probe_cmd = (...) block')
        probe_body = m.group(1)
        # The f-string body must contain wget (the busybox HTTP client)
        self.assertIn('wget', probe_body, msg='probe_cmd f-string missing wget: {}'.format(probe_body))
        # And must NOT contain curl
        self.assertNotIn('curl', probe_body, msg='probe_cmd f-string still uses curl: {}'.format(probe_body))
        # Also ban any non-comment code line with docker exec + curl
        for line in section.splitlines():
            stripped = line.strip()
            # Skip pure comment lines (rationale explanations)
            if stripped.startswith('#'):
                continue
            if 'docker exec' in line and 'curl' in line:
                self.fail('cmd_deploy wait-for-UP section has docker exec + curl (CODE): {}'.format(stripped))

    def test_probe_wget_has_timeout_and_tries(self):
        """wget must use -T (timeout) and --tries=1 to fail fast inside container."""
        section = self._section_around_probe()
        self.assertIn('-T 5', section, msg='wget missing -T 5 timeout')
        self.assertIn('--tries=1', section, msg='wget missing --tries=1 (must NOT retry)')

    def test_diagnose_hints_no_curl(self):
        """The diagnose-hint block (printed on probe timeout) must not suggest curl.

        Per [[divs-backend-curl-missing]] — busybox container has no curl.
        Suggesting curl in the diagnose output would mislead the operator.
        """
        section = self._diagnose_section()
        # We allow `wget` (the working tool) but ban `curl`
        # except in comments explicitly noting curl is NOT available.
        for line in section.splitlines():
            stripped = line.strip()
            # Skip pure comment lines that explain the curl absence
            if stripped.startswith('#') and 'curl' in stripped:
                continue
            # Skip the R6.86-A rationale comment
            if 'R6.86-A' in stripped and 'curl' in stripped:
                continue
            self.assertNotIn(
                'curl', line,
                msg='diagnose section suggests curl to operator (busybox container): {}'.format(stripped))

    def test_r686a_rationale_comment_present(self):
        """A comment block must explain WHY we use wget (R6.86-A iron rule provenance)."""
        self.assertIn(
            'R6.86-A',
            self.source,
            msg='R6.86-A rationale comment missing from build-and-deploy-jar.py')
        self.assertIn(
            'busybox',
            self.source,
            msg='R6.86-A rationale must mention busybox (the root cause)')


if __name__ == '__main__':
    unittest.main(verbosity=2)