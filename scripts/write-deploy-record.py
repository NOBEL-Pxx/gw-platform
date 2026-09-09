#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write-deploy-record.py — R6.99 #5: Deploy audit trail writer.

PURPOSE:
  Writes a JSON audit record to BOTH local and remote locations after every deploy.
  Provides a single source of truth for "what was deployed, when, by whom, with what result".

USAGE:
  # Local-only (default — always safe):
  python write-deploy-record.py --commit 2c53a5f --files "scripts/zkb.py,scripts/zjlab-verify-smoketest.py"

  # Local + remote (requires explicit --remote flag, per iron rules):
  python write-deploy-record.py --commit 2c53a5f --files "scripts/zkb.py" --remote

  # With full audit context:
  python write-deploy-record.py --commit 2c53a5f --files "..." --env-drift OK --smoketest PASS \\
                               --duration 47.9 --operator USER

  # Auto-detect commit from git (no --commit flag needed):
  python write-deploy-record.py --files "..." --remote

  # Display current record without writing:
  python write-deploy-record.py --show

PREREQUISITES:
  - For --remote: zkb.py importable (D:\\AliCPT\\scripts\\zkb.py)
  - Local git repo at D:\\AliCPT (for auto-detect commit_sha)
  - sync-to-zjlab.py at D:\\AliCPT\\scripts\\sync-to-zjlab.py (for version auto-detect)

OUTPUT LOCATIONS:
  Local:  D:\\AliCPT\\.deploy-audit\\last-deploy.json     (atomic write via .tmp + rename)
  Remote: ~/last-deploy.json on zjlab                     (via zkb.py sftp_put_text)

IRON RULES:
  - protect-user-config: local .deploy-audit/ is repo-local, NOT in home directory.
  - r677-amend-force-push: commit_sha must be VERIFIABLE (either user-provided or git-detected),
    NEVER auto-fabricated.
  - r678-classifier-boundary: scripts OK, auto-execute NO.
    Remote write requires explicit --remote flag — never silently upload to user zjlab home.
  - r682-push-ssh: this is for AFTER-push deploy records; the push itself happens elsewhere.

WHY THIS EXISTS (R6.99 #5 backlog):
  - 6 sync-gap iterations across R6.78-R6.95 produced a lot of moving parts but no audit trail.
  - When something breaks in prod, the first question is "what was the last deploy?".
  - Without an audit record, you grep git log + memory + Slack — slow and error-prone.
  - This script is the durable answer: one JSON file, written every deploy, with the data
    you'd want when debugging a 3am outage.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Force stdout/stderr to utf-8 (Windows defaults to GBK -> can't print '✓' etc.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass


# === Config ===
LOCAL_REPO = Path(r'D:\AliCPT')
LOCAL_AUDIT_DIR = LOCAL_REPO / '.deploy-audit'
LOCAL_AUDIT_FILE = LOCAL_AUDIT_DIR / 'last-deploy.json'
REMOTE_AUDIT_FILE = '~/last-deploy.json'  # in zjlab user's home dir
SYNC_SCRIPT = LOCAL_REPO / 'scripts' / 'sync-to-zjlab.py'


def _now_utc_iso() -> str:
    """Return current UTC time as ISO-8601 with Z suffix (e.g. 2026-09-09T13:50:00Z)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _git_head_sha() -> Optional[str]:
    """Return current HEAD SHA from D:\\AliCPT, or None if git fails.

    Uses subprocess.run (not shell=True) to avoid quoting issues on Windows.
    """
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


def _git_short_sha(sha: str) -> str:
    """Return first 7 chars of SHA (or full SHA if shorter)."""
    return sha[:7] if len(sha) >= 7 else sha


def _detect_sync_version() -> str:
    """Read VERSION from sync-to-zjlab.py docstring header.

    Pattern: "GravitationalWave Platform — Sync Script (vX.YY)"
    Returns 'unknown' if pattern not found.
    """
    if not SYNC_SCRIPT.exists():
        return 'unknown'
    try:
        text = SYNC_SCRIPT.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return 'unknown'
    m = re.search(r'Sync Script \(v(\d+\.\d+(?:\.\d+)?)\)', text)
    return 'v' + m.group(1) if m else 'unknown'


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to <path>.tmp, then rename to <path>.

    Protects against partial writes if process is killed mid-write.
    Windows: os.replace is atomic on the same volume.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp_path, path)
    except Exception:
        # Clean up tmp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_remote(json_text: str) -> tuple[bool, str]:
    """Write JSON text to REMOTE_AUDIT_FILE via zkb.py.

    Returns (success, message). Imports zkb lazily so this script works without SSH if --remote not used.
    """
    try:
        from zkb import Zkb  # type: ignore
    except ImportError as e:
        return False, 'zkb.py not importable: {}'.format(e)

    try:
        z = Zkb()
        try:
            z.sftp_put_text(json_text, REMOTE_AUDIT_FILE)
            return True, 'remote ok ({} bytes)'.format(len(json_text))
        finally:
            try:
                z.close()
            except Exception:
                pass
    except Exception as e:
        return False, 'remote write failed: {}'.format(e)


def _show_existing() -> int:
    """Print current local last-deploy.json (if any). Returns 0 if shown, 1 if not found."""
    if not LOCAL_AUDIT_FILE.exists():
        print('NO RECORD: {} does not exist'.format(LOCAL_AUDIT_FILE))
        return 1
    print('--- {} ---'.format(LOCAL_AUDIT_FILE))
    print(LOCAL_AUDIT_FILE.read_text(encoding='utf-8'))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Write deploy audit record to local + optional remote location.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--commit', help='Git commit SHA (auto-detected from HEAD if omitted)')
    parser.add_argument('--files', help='Comma-separated list of files changed (e.g. "scripts/zkb.py,docs/foo.md")')
    parser.add_argument('--env-drift', choices=['OK', 'NOTE', 'WARNING'], default='OK',
                        help='Env drift severity (default: OK)')
    parser.add_argument('--smoketest', choices=['PASS', 'FAIL', 'SKIP'], default='SKIP',
                        help='Smoketest result (default: SKIP if not run)')
    parser.add_argument('--duration', type=float, default=0.0,
                        help='Deploy duration in seconds (default: 0)')
    parser.add_argument('--operator', default='USER',
                        help='Operator name (default: USER)')
    parser.add_argument('--remote', action='store_true',
                        help='Also write to zjlab ~/last-deploy.json (per protect-user-config iron rule)')
    parser.add_argument('--show', action='store_true',
                        help='Display current last-deploy.json and exit')
    args = parser.parse_args()

    if args.show:
        return _show_existing()

    # === Resolve commit SHA ===
    commit_sha = args.commit
    if not commit_sha:
        commit_sha = _git_head_sha()
        if not commit_sha:
            print('ERROR: --commit not provided and git HEAD detection failed', file=sys.stderr)
            return 2
        print('[auto] commit_sha from git HEAD: {}'.format(commit_sha))

    commit_short = _git_short_sha(commit_sha)

    # === Resolve files list ===
    files_changed: list[str] = []
    if args.files:
        files_changed = [f.strip() for f in args.files.split(',') if f.strip()]

    # === Build record ===
    record = {
        'timestamp_utc': _now_utc_iso(),
        'commit_sha': commit_sha,
        'commit_short': commit_short,
        'operator': args.operator,
        'files_changed': files_changed,
        'file_count': len(files_changed),
        'env_drift_severity': args.env_drift,
        'smoketest_status': args.smoketest,
        'deploy_duration_seconds': args.duration,
        'sync_to_zjlab_version': _detect_sync_version(),
    }

    json_text = json.dumps(record, indent=2, ensure_ascii=False)

    # === Write local (ALWAYS) ===
    try:
        _atomic_write_json(LOCAL_AUDIT_FILE, record)
        print('[local] wrote {} ({} bytes)'.format(LOCAL_AUDIT_FILE, len(json_text)))
    except OSError as e:
        print('ERROR: local write failed: {}'.format(e), file=sys.stderr)
        return 1

    # === Write remote (ONLY if --remote) ===
    if args.remote:
        ok, msg = _write_remote(json_text)
        print('[remote] {}'.format(msg))
        if not ok:
            return 1
    else:
        print('[remote] skipped (pass --remote to write to zjlab ~/last-deploy.json)')

    # === Print final record ===
    print()
    print('--- record ---')
    print(json_text)
    return 0


if __name__ == '__main__':
    sys.exit(main())