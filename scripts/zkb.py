#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zkb.py — ZJLab Keep-it-Boring SSH wrapper.

R6.95: One unified helper for all zjlab bastion→server SSH work.

Why this exists:
  - Previous deploy sessions wrote 6+ separate zjlab-*.py scripts
  - Each re-implemented: paramiko bastion tunnel + cred parsing + GBK unicode
    handling + channel timeouts. ~100 lines of boilerplate per script.
  - JSON output from paramiko stdout is GBK-encoded on Windows → 'gbk' codec
    can't encode '\u2713' errors when stdout is redirected.

This module:
  - Single long-lived SSH connection (reused across calls in same Python session)
  - Reads creds from sync-to-zjlab.py source (no inline secrets)
  - `run()` returns decoded text via errors='replace' + ascii-safe mode
  - `docker_exec()` helper for inside-container commands
  - `sftp_put()` / `sftp_put_dir()` for batch uploads
  - `stream()` for long-running commands (e.g. docker build with progress)

Usage (CLI):
    python zkb.py --help
    python zkb.py exec "docker ps --format '{{.Names}} {{.Status}}'"
    python zkb.py docker gw-frontend "nginx -t 2>&1 | tail -3"
    python zkb.py upload local-dir/ remote/path/
    python zkb.py stream "cd ~/gw-frontend && docker build . 2>&1" --timeout 600
    python zkb.py ps     # all containers + status
    python zkb.py health # container + pipeline + smoketest summary

Usage (as library):
    from zkb import Zkb
    z = Zkb()                              # auto-connect
    out, code = z.run('whoami')
    out = z.docker_exec('gw-frontend', 'nginx -t')
    z.sftp_put_dir(r'D:\\x', '/home/zjlab/x')
    z.close()

Per [[r678-classifier-boundary]]:
  - 文档 ✅, 脚本生成 ✅ → this file OK
  - 批量删除 ❌, 自动执行 ❌ → auto-deploy NOT done here; USER must invoke

Per [[gw-platform-user-access]]: zjlab access via bastion (see memory for endpoint topology)
"""
import argparse
import io
import json
import os
import re
import socket
import sys
import time
import warnings
from pathlib import Path

# Force stdout/stderr to utf-8 (Windows defaults to GBK -> can't print '✓' etc.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

# Silence paramiko TripleDES deprecation from cryptography 48+
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')

try:
    import paramiko
except ImportError:
    print('ERROR: paramiko not installed. Run: pip install paramiko', file=sys.stderr)
    raise


# === Config: sync-to-zjlab.py source path (single source of truth for creds) ===
# R6.102 D4: None means "no Windows fallback available"; callers must either
# set ZJLAB_* env vars OR pass sync_script_path explicitly. parse_creds()
# raises actionable RuntimeError when all 3 are missing (instead of cryptic
# FileNotFoundError on the Windows-only literal).
DEFAULT_SYNC_SCRIPT = None


# R6.101: env-var names for CI runners (no hardcoded D:\ path required).
# All-or-nothing semantics: if ANY of the 9 vars is set, ALL must be set; else
# RuntimeError. This prevents silent partial-config bugs (e.g. setting BASTION
# HOST but forgetting BASTION PASSWORD, which would silently use file PASSWORD
# on file-only hosts but produce auth-fail on env hosts).
_ENV_BASTION_KEYS = ('ZJLAB_BASTION_HOST', 'ZJLAB_BASTION_PORT',
                     'ZJLAB_BASTION_USER', 'ZJLAB_BASTION_PASSWORD')
_ENV_SERVER_KEYS = ('ZJLAB_SERVER_HOST', 'ZJLAB_SERVER_PORT',
                    'ZJLAB_SERVER_USER', 'ZJLAB_SERVER_PASSWORD')
_ENV_ROOT_KEY = 'ZJLAB_REMOTE_ROOT'


def _any_env_set():
    """Return dict of all 9 env vars (None for unset OR empty string).

    R6.101 review (SECURITY MEDIUM): empty string '' must be treated as unset,
    otherwise ZJLAB_BASTION_HOST='' bypasses the all-or-nothing guardrail and
    silently reaches the connect path with an empty hostname. zsmoke.yml catches
    this with `set -u` + `-z`, but local Python callers don't get that check.
    Returns None for both unset and empty string (treats them identically).
    """
    out = {}
    for k in _ENV_BASTION_KEYS + _ENV_SERVER_KEYS + (_ENV_ROOT_KEY,):
        v = os.environ.get(k)
        out[k] = v if v else None  # None or '' -> None
    return out


def _parse_creds_from_file(sync_script_path: Path):
    """Parse BASTION + SERVER + REMOTE_ROOT from sync-to-zjlab.py source.

    No creds embedded in this file. Reads them at runtime.
    Returns (BASTION_tuple, SERVER_tuple, REMOTE_ROOT_str).
    """
    fsrc = sync_script_path.read_text(encoding='utf-8')
    m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", fsrc, re.M)
    m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", fsrc, re.M)
    m_r = re.search(r"^REMOTE_ROOT\s*=\s*'([^']+)'", fsrc, re.M)
    if not (m_b and m_s and m_r):
        raise RuntimeError(f'Failed to parse creds from {sync_script_path}')
    bastion = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
    server = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))
    remote_root = m_r.group(1)
    return bastion, server, remote_root


def parse_creds(sync_script_path=None):
    """Parse BASTION + SERVER + REMOTE_ROOT from env vars (preferred) or sync-to-zjlab.py.

    R6.101: env-var path takes precedence for CI runners; file path is fallback for
    Windows dev workflow. All-or-nothing: if ANY of the 9 ZJLAB_* env vars is set,
    ALL must be set (else RuntimeError). This avoids silent partial-config bugs.

    The 9 ZJLAB_* env vars are:
      - ZJLAB_BASTION_HOST, ZJLAB_BASTION_PORT, ZJLAB_BASTION_USER, ZJLAB_BASTION_PASSWORD
      - ZJLAB_SERVER_HOST,  ZJLAB_SERVER_PORT,  ZJLAB_SERVER_USER,  ZJLAB_SERVER_PASSWORD
      - ZJLAB_REMOTE_ROOT

    R6.102 D5: enumeration added to docstring (previously module-level constants only).

    Returns (BASTION_tuple, SERVER_tuple, REMOTE_ROOT_str).
    """
    env = _any_env_set()
    set_keys = [k for k, v in env.items() if v is not None]

    # No env vars: pure file parse (Windows dev workflow)
    if not set_keys:
        # R6.102 D4: fail fast with actionable message instead of cryptic FileNotFoundError
        if sync_script_path is None:
            raise RuntimeError(
                'No ZJLAB_* env vars set AND no sync_script_path provided. '
                'Either set ZJLAB_BASTION_HOST/PORT/USER/PASSWORD + ZJLAB_SERVER_* + ZJLAB_REMOTE_ROOT, '
                'or pass sync_script_path=Path("D:/AliCPT/scripts/sync-to-zjlab.py") explicitly.'
            )
        return _parse_creds_from_file(sync_script_path)

    # Some env vars set: require ALL 9 to be set
    missing = [k for k in env if k not in set_keys]
    if missing:
        raise RuntimeError(
            f'Partial ZJLAB_* env ({len(set_keys)}/9 set). '
            f'Missing: {missing}. Set all 9 or none.'
        )

    # All 9 set: use env values, cast PORT to int
    return (
        (env['ZJLAB_BASTION_HOST'], int(env['ZJLAB_BASTION_PORT']),
         env['ZJLAB_BASTION_USER'], env['ZJLAB_BASTION_PASSWORD']),
        (env['ZJLAB_SERVER_HOST'], int(env['ZJLAB_SERVER_PORT']),
         env['ZJLAB_SERVER_USER'], env['ZJLAB_SERVER_PASSWORD']),
        env['ZJLAB_REMOTE_ROOT'],
    )




class Zkb:
    """Single connection to zjlab via bastion tunnel.

    Reuse across calls. Call close() when done. Use as context manager.
    """

    def __init__(self, sync_script_path: Path = DEFAULT_SYNC_SCRIPT):
        self.bastion, self.server, self.remote_root = parse_creds(sync_script_path)
        self.ba = None
        self.tg = None
        self.sftp = None
        self._connect()

    def _connect(self):
        """Open bastion + tunnel + target + keepalive."""
        self.ba = paramiko.SSHClient()
        self.ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ba.connect(self.bastion[0], self.bastion[1], self.bastion[2], self.bastion[3],
                        timeout=20, allow_agent=False, look_for_keys=False)
        self.ba.get_transport().set_keepalive(30)
        ch = self.ba.get_transport().open_channel(
            'direct-tcpip', (self.server[0], self.server[1]), ('127.0.0.1', 0), timeout=10)
        self.tg = paramiko.SSHClient()
        self.tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.tg.connect(self.server[0], self.server[1], self.server[2], self.server[3],
                        timeout=20, allow_agent=False, look_for_keys=False, sock=ch)

    def close(self):
        if self.sftp:
            try: self.sftp.close()
            except: pass
        if self.tg:
            try: self.tg.close()
            except: pass
        if self.ba:
            try: self.ba.close()
            except: pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _safe_text(b: bytes) -> str:
        """Decode bytes as utf-8 with ascii-safe replacement for non-ASCII."""
        try:
            return b.decode('utf-8')
        except UnicodeDecodeError:
            return b.decode('ascii', 'replace')

    def run(self, cmd: str, timeout: int = 30, json_out: bool = False):
        """Execute shell command on zjlab target. Returns (stdout, exit_code).

        If json_out=True, treats stdout as JSON and returns parsed dict in
        place of string (raises if not valid JSON).
        """
        stdin, stdout, stderr = self.tg.exec_command(cmd, timeout=timeout)
        out = self._safe_text(stdout.read())
        err = self._safe_text(stderr.read())
        code = stdout.channel.recv_exit_status()
        if json_out:
            try:
                return json.loads(out), code
            except json.JSONDecodeError as e:
                # R6.102 S1: truncate to 80 chars (avoid leaking env vars from failed JSON parses)
                _safe = lambda s: ((s[:80] + '...[truncated]') if s and len(s) > 80 else (s or '<empty>'))
                raise RuntimeError(f'JSON parse failed: {e}\n--- raw (first 80) ---\n{_safe(out)}\n--- stderr (first 80) ---\n{_safe(err)}')
        return out, code

    def stream(self, cmd: str, timeout: int = 600, ascii_safe: bool = True) -> str:
        """Execute long-running command, streaming output line-by-line.
        Returns full output as text (ascii_safe replaces non-ASCII for printing)."""
        ch = self.tg.get_transport().open_session(timeout=timeout)
        ch.settimeout(timeout)
        ch.exec_command(cmd)
        buf = []
        start = time.time()
        try:
            while True:
                data = ch.recv(65536)
                if not data:
                    break
                buf.append(self._safe_text(data))
                # Periodic flush to console
                if sum(len(s) for s in buf) % 4096 < 200:
                    print(buf[-1][-200:], end='', flush=True)
                if time.time() - start > timeout - 10:
                    print(f'  [timeout-guard] hit {timeout-10}s, stopping stream')
                    break
        except socket.timeout:
            pass
        out = ''.join(buf)
        if ascii_safe:
            return out.encode('ascii', 'replace').decode('ascii')
        return out

    def docker_exec(self, container: str, cmd: str, timeout: int = 30) -> str:
        """Execute command inside docker container. Returns stdout text."""
        full = f'docker exec {container} sh -c "{cmd}"'
        out, _ = self.run(full, timeout=timeout)
        return out

    def docker_ps(self, name_filter: str = None) -> list:
        """List containers matching filter. Returns list of {Names, Status, Ports}."""
        flt = f'--filter name={name_filter}' if name_filter else ''
        cmd = f'docker ps {flt} --format "{{{{.Names}}}}|{{{{.Status}}}}|{{{{.Ports}}}}"'
        out, _ = self.run(cmd)
        containers = []
        for line in out.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|', 2)
            if len(parts) == 3:
                containers.append({'name': parts[0], 'status': parts[1], 'ports': parts[2]})
        return containers

    def get_sftp(self):
        """Lazy SFTP client."""
        if not self.sftp:
            self.sftp = self.tg.open_sftp()
        return self.sftp

    def sftp_put(self, local: str, remote: str) -> int:
        """Upload single file. Returns bytes uploaded."""
        sftp = self.get_sftp()
        sftp.put(local, remote)
        return os.path.getsize(local)

    def sftp_put_dir(self, local_dir: str, remote_dir: str,
                     pattern: str = '*', skip_hidden: bool = True) -> int:
        """Upload all files in local_dir to remote_dir (recursive). Returns bytes."""
        sftp = self.get_sftp()
        local_path = Path(local_dir)
        total_bytes = 0
        for f in sorted(local_path.rglob(pattern)):
            if skip_hidden and any(p.startswith('.') for p in f.relative_to(local_path).parts):
                continue
            rel = f.relative_to(local_path)
            remote_path = remote_dir.rstrip('/') + '/' + str(rel).replace('\\', '/')
            remote_parent = remote_path.rsplit('/', 1)[0]
            try:
                sftp.stat(remote_parent)
            except IOError:
                # mkdir -p via exec
                self.run(f'mkdir -p "{remote_parent}"')
            sftp.put(str(f), remote_path)
            total_bytes += f.stat().st_size
        return total_bytes

    @staticmethod
    def _sha256_str(content: str) -> str:
        """Compute SHA256 of a string (UTF-8 encoded)."""
        import hashlib
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _remote_sha256_str(self, remote: str) -> str:
        """Compute SHA256 of a remote text file via shell sha256sum.
        Returns '' if file doesn't exist."""
        try:
            out, _ = self.run(f'sha256sum "{remote}" 2>/dev/null')
        except Exception:
            return ''
        if not out.strip():
            return ''
        return out.strip().split()[0]

    def sftp_put_text(self, remote: str, content: str, force: bool = False) -> int:
        """Upload text content to remote file with SHA256 dedup.
        Returns bytes uploaded (0 if skipped due to SHA match).

        R6.97: closes the gap where callers used raw sftp.open() bypassing dedup.
        Auto-creates parent dir (mkdir -p).
        """
        import hashlib
        sftp = self.get_sftp()
        local_sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
        # mkdir -p parent
        parent = remote.rsplit('/', 1)[0]
        if parent and parent != remote:
            try:
                sftp.stat(parent)
            except IOError:
                self.run(f'mkdir -p "{parent}"')
        # Check remote SHA
        if not force:
            remote_sha = self._remote_sha256_str(remote)
            if remote_sha == local_sha:
                return 0  # skip upload
        # Write
        with sftp.open(remote, 'wb') as f:
            f.write(content.encode('utf-8'))
        return len(content.encode('utf-8'))

    def sftp_get_text(self, remote: str) -> str:
        """Download text content from remote file as UTF-8 string.
        Returns '' if file doesn't exist."""
        sftp = self.get_sftp()
        try:
            with sftp.open(remote, 'rb') as f:
                return f.read().decode('utf-8')
        except IOError:
            return ''

    def sftp_mkdir_p(self, remote_dir: str):
        """mkdir -p on remote."""
        self.run(f'mkdir -p "{remote_dir}"')

    def sftp_rm(self, remote_path: str):
        """Remove single file on remote (use with caution per [[recycle-bin-only]]).
        Only intended for cleanup of bind-mount generated artifacts, NOT user data."""
        sftp = self.get_sftp()
        try:
            sftp.remove(remote_path)
        except IOError as e:
            # OK if already gone
            if 'No such file' not in str(e):
                raise

    def docker_reload_nginx(self, container: str = 'gw-frontend') -> str:
        """Reload nginx via docker kill SIGHUP from outside the container.

        R6.96d: `nginx -s reload` INSIDE the container fails silently when master
        is PID 1 (old master cannot kill PID 1, 'Operation not permitted'). The
        only reliable path is `docker kill --signal=HUP <container>` from the
        zjlab host. Workers reload their config, old workers gracefully exit.
        Returns the docker kill output (container name on success).
        """
        out, code = self.run(f'docker kill --signal=HUP {container}', timeout=15)
        if code != 0:
            # R6.102 S3: truncate to 200 chars (avoid leaking nginx config rendering env vars)
                _safe = (out[:200] + '...[truncated]') if out and len(out) > 200 else (out or '<empty>')
                raise RuntimeError(f'nginx reload via docker kill HUP failed (exit {code}): {_safe}')
        return out.strip() or container

    def health(self) -> dict:
        """Quick health summary: containers + pipeline status + smoketest."""
        out = {'containers': [], 'pipeline_http': None, 'smoketest': None}
        try:
            out['containers'] = self.docker_ps()
        except Exception as e:
            # R6.102 S4: store generic tag only, not raw exception (paramiko leaks host:port:user)
                _msg = str(e).lower()
                if 'auth' in _msg or 'password' in _msg:
                    out['containers_error'] = 'auth-failed'
                elif 'timeout' in _msg:
                    out['containers_error'] = 'timeout'
                elif 'refused' in _msg or 'unreachable' in _msg or 'no route' in _msg:
                    out['containers_error'] = 'connection-refused'
                else:
                    out['containers_error'] = 'unknown-error'
        try:
            txt, _ = self.run('curl -sk --resolve "r692-smoketest.local:6002:127.0.0.1" '
                              '-w "\\nHTTP=%{http_code}\\n" '
                              'https://r692-smoketest.local:6002/r692-smoketest-status')
            out['smoketest'] = txt.strip()
        except Exception as e:
            # R6.102 S5: sanitize curl error string (strip query, redact userinfo, redact IPv4)
                import re as _re
                _msg = str(e)
                _msg = _re.sub(r'\?[^\?]*', '', _msg)  # strip query string
                _msg = _re.sub(r'(://)([^:]+):([^@]+)@', r'\1\2:***@', _msg)  # redact userinfo
                _msg = _re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<ip>', _msg)
                out['smoketest_error'] = _msg
        return out

    def check_marker_log(self, container: str, marker,
                         since: str = '30s', timeout: int = 10) -> tuple[bool, str]:
        """R6.84b: Grep container logs for one or more marker strings.

        Centralizes the R6.83 V1 marker check pattern (originally inlined in
        build-and-deploy-jar.py:615-636) so future R6.x deploy verifications
        can reuse it. Supports both single-marker (str) and multi-marker
        (list[str]) — multi-marker is an AND check (all must be present).

        Args:
            container: Docker container name to inspect logs of.
            marker: Either a single string (substring match) or a list of
                strings (all required — returns True only if ALL are present).
                Required to support future R6.x markers without helper churn.
            since: Value passed to `docker logs --since` (default '30s').
                Covers typical Spring Boot warmup; tune for slower apps.
            timeout: SSH command timeout in seconds.

        Returns:
            Tuple of (found, log_snippet):
              - found: True if all marker(s) are present in the recent log window.
              - log_snippet: First 500 chars of docker logs output (truncated to
                avoid runaway log lines in caller print output). Caller can
                inspect this to see WHICH marker is missing if needed.

        Implementation: Client-side grep on the docker logs output. We avoid
        server-side FOUND/MISSING echo pipelines because:
          1. Mocked tests cannot exercise shell pipelines — they'd always return
             "FOUND" or "MISSING" depending on the wrapper's semantics, not on
             the actual log content.
          2. The decision is a simple substring check; doing it in Python keeps
             the helper's contract predictable across SSH, dry-run, and tests.
        """
        if isinstance(marker, str):
            markers = [marker]
        else:
            markers = list(marker)

        cmd = 'docker logs --since {since} {container} 2>&1'.format(
            since=since, container=container,
        )
        out, _code = self.run(cmd, timeout=timeout)
        out = out or ''
        found = all(m in out for m in markers)
        snippet = out[:500]
        return found, snippet


# === CLI ===

def cli_exec(args, z: Zkb):
    out, code = z.run(args.cmd, timeout=args.timeout)
    print(out)
    return code

def cli_docker(args, z: Zkb):
    out = z.docker_exec(args.container, args.cmd, timeout=args.timeout)
    print(out)
    return 0

def cli_upload(args, z: Zkb):
    n = z.sftp_put_dir(args.local, args.remote)
    print(f'uploaded {n} bytes from {args.local} to {args.remote}')
    return 0

def cli_stream(args, z: Zkb):
    out = z.stream(args.cmd, timeout=args.timeout)
    if args.output:
        Path(args.output).write_text(out, encoding='utf-8')
        print(f'wrote {len(out)} bytes to {args.output}')
    else:
        print(out)
    return 0

def cli_ps(args, z: Zkb):
    containers = z.docker_ps(args.filter)
    for c in containers:
        print(f"{c['name']:25} {c['status']:30} {c['ports']}")
    return 0

def cli_health(args, z: Zkb):
    h = z.health()
    print(json.dumps(h, indent=2, ensure_ascii=False))
    return 0

def cli_upload_smoke(args, z: Zkb):
    """Test SFTP upload of a single small file (used by sync-to-zjlab pre-flight)."""
    n = z.sftp_put(args.local, args.remote)
    print(f'OK uploaded {n} bytes')
    return 0

def main():
    p = argparse.ArgumentParser(
        description='zkb — ZJLab Keep-it-Boring SSH wrapper (R6.95)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--sync-script', default=str(DEFAULT_SYNC_SCRIPT),
                   help=f'Path to sync-to-zjlab.py (default: {DEFAULT_SYNC_SCRIPT})')
    sub = p.add_subparsers(dest='cmd_name', required=True)

    sp = sub.add_parser('exec', help='Run shell command on zjlab')
    sp.add_argument('cmd')
    sp.add_argument('--timeout', type=int, default=30)
    sp.set_defaults(func=cli_exec)

    sp = sub.add_parser('docker', help='Run command inside docker container')
    sp.add_argument('container')
    sp.add_argument('cmd')
    sp.add_argument('--timeout', type=int, default=30)
    sp.set_defaults(func=cli_docker)

    sp = sub.add_parser('upload', help='Recursively upload local dir to remote dir')
    sp.add_argument('local')
    sp.add_argument('remote')
    sp.set_defaults(func=cli_upload)

    sp = sub.add_parser('stream', help='Stream output of long-running command')
    sp.add_argument('cmd')
    sp.add_argument('--timeout', type=int, default=600)
    sp.add_argument('--output', '-o', help='Write full output to file')
    sp.set_defaults(func=cli_stream)

    sp = sub.add_parser('ps', help='List docker containers')
    sp.add_argument('--filter', help='Container name filter')
    sp.set_defaults(func=cli_ps)

    sp = sub.add_parser('health', help='Quick health summary (containers + smoketest)')
    sp.set_defaults(func=cli_health)

    sp = sub.add_parser('upload-smoke', help='Upload single file (pre-flight test)')
    sp.add_argument('local')
    sp.add_argument('remote')
    sp.set_defaults(func=cli_upload_smoke)

    args = p.parse_args()
    z = Zkb(Path(args.sync_script))
    try:
        return args.func(args, z)
    finally:
        z.close()


if __name__ == '__main__':
    sys.exit(main() or 0)
