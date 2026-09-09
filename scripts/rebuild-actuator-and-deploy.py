#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild-actuator-and-deploy.py — R6.98 #2 actuator jar rebuild + deploy.

This is the manual rebuild + deploy procedure for the Spring Boot Actuator dep
that was staged in R6.97 #2 (commit c82e7e5). Per [[r678-classifier-boundary]]:
  - 脚本生成 OK (this file)
  - 自动执行 NO (USER must explicitly invoke Phase A + Phase B)

Two-phase procedure:
  Phase A: Build gw-backend/start/target/start.jar with actuator dep
           (requires Maven; NOT auto-executed — USER must invoke)
  Phase B: Transfer jar to zjlab, restart divs-backend, verify /actuator/health
           (also NOT auto-executed — USER must invoke after Phase A succeeds)

USAGE:
  python rebuild-actuator-and-deploy.py build    # Phase A: build locally
  python rebuild-actuator-and-deploy.py deploy   # Phase B: deploy + restart + verify
  python rebuild-actuator-and-deploy.py all      # both (with USER confirmation prompt)
  python rebuild-actuator-and-deploy.py check    # diagnostic only (mvn? actuator? jar?)
  python rebuild-actuator-and-deploy.py verify   # just verify /actuator/health is UP

PREREQUISITES:
  - Java 17+ JDK installed (mvn requires it)
  - Maven 3.6+ (mvn on PATH, or set M2_HOME)
  - Spring Boot deps cached (~/.m2/, first build will be slow)
  - For Phase B: zkb.py importable (C:\\Users\\28610\\zkb.py OR D:\\AliCPT\\scripts\\zkb.py)

WHY THIS EXISTS:
  - R6.97 closed R6.96c by changing backend-health.conf upstream to /v3/api-docs
    (canary). The proper fix is enabling Spring Boot Actuator so /actuator/health
    returns {"status":"UP"} directly.
  - R6.97 #2 staged the dep but could not rebuild (no mvn available locally).
  - This script provides the rebuild + deploy path so USER can finish R6.96c.

IRON RULES:
  - R6.97d: gw-backend dependency changes require explicit USER authorization for
    `mvn package` + `docker restart divs-backend`. NEVER auto-run even if pom.xml
    is committed.
  - r676b-classifier-auth: USER must explicitly say "yes, rebuild and restart"
    (not implicit from "go" or "fix this").
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Force stdout/stderr to utf-8 (Windows defaults to GBK)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

# === Paths ===
GW_BACKEND_START = Path(r'D:\AliCPT\gw-backend\start')
POM_XML = GW_BACKEND_START / 'pom.xml'
JAR_LOCAL = GW_BACKEND_START / 'target' / 'start.jar'

# === Remote (zjlab) ===
REMOTE_BACKEND_DIR = '/home/zjlab/gw-backend'
REMOTE_JAR = f'{REMOTE_BACKEND_DIR}/start.jar'
REMOTE_CONTAINER = 'divs-backend'
REMOTE_HEALTH_URL = 'http://divs-backend:8093/actuator/health'
REMOTE_API_DOCS_URL = 'http://divs-backend:8093/v3/api-docs'

# === Required deps for Phase B (zkb) ===
ZKB_PATHS = [
    Path(r'C:\Users\28610\zkb.py'),
    Path(r'D:\AliCPT\scripts\zkb.py'),
]


def _has_actuator_in_pom() -> bool:
    if not POM_XML.exists():
        return False
    return 'spring-boot-starter-actuator' in POM_XML.read_text(encoding='utf-8')


def _which_mvn() -> Optional[str]:
    """Find mvn executable. Returns path or None."""
    candidates = ['mvn', 'mvn.cmd']
    for c in candidates:
        for path_dir in os.environ.get('PATH', '').split(os.pathsep):
            full = Path(path_dir) / c
            if full.exists():
                return str(full)
    # Check M2_HOME
    m2 = os.environ.get('M2_HOME')
    if m2:
        for c in ['bin/mvn', 'bin/mvn.cmd']:
            full = Path(m2) / c
            if full.exists():
                return str(full)
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def cmd_check(args):
    """Diagnostic: mvn? actuator in pom? existing jar?"""
    print('=== Diagnostic ===')
    print(f'pom.xml exists: {POM_XML.exists()}')
    if POM_XML.exists():
        print(f'actuator dep in pom.xml: {_has_actuator_in_pom()}')
    mvn = _which_mvn()
    print(f'mvn available: {mvn or "NO"}')
    if mvn:
        try:
            out = subprocess.check_output([mvn, '--version'], stderr=subprocess.STDOUT, timeout=10).decode(errors='replace')
            print(f'mvn version: {out.split(chr(10))[0]}')
        except Exception as e:
            print(f'mvn --version failed: {e}')
    print(f'local jar exists: {JAR_LOCAL.exists()}')
    if JAR_LOCAL.exists():
        print(f'local jar size: {JAR_LOCAL.stat().st_size:,} bytes')
        print(f'local jar sha256: {_sha256(JAR_LOCAL)[:16]}...')
    print()
    print('zkb.py candidates:')
    for p in ZKB_PATHS:
        print(f'  {"OK" if p.exists() else "NO"}  {p}')
    print()
    zkb_ok = any(p.exists() for p in ZKB_PATHS)
    print(f'Phase B prereq (zkb importable): {"OK" if zkb_ok else "MISSING"}')
    return 0


def cmd_build(args):
    """Phase A: mvn package."""
    print('=== Phase A: Build gw-backend/start with actuator ===')
    if not POM_XML.exists():
        print(f'ERROR: {POM_XML} not found')
        return 1
    if not _has_actuator_in_pom():
        print(f'ERROR: spring-boot-starter-actuator NOT in {POM_XML}')
        print('First commit the pom.xml change (R6.97 #2 / commit c82e7e5),')
        print('then re-run this command.')
        return 1
    mvn = _which_mvn()
    if not mvn:
        print('ERROR: mvn not on PATH and M2_HOME not set.')
        print()
        print('OPTIONS:')
        print('  1. Install Maven locally:')
        print('     - Download from https://maven.apache.org/download.cgi')
        print('     - Add M2_HOME to environment variables')
        print('     - Add %M2_HOME%\\bin to PATH')
        print('  2. Run this command on a build machine that has mvn:')
        print(f'     cd {GW_BACKEND_START}')
        print('     mvn -pl start package -DskipTests')
        print()
        print('After successful build, copy start.jar to:')
        print(f'  {JAR_LOCAL}')
        print('Then re-run: python rebuild-actuator-and-deploy.py deploy')
        return 1
    if args.dry_run:
        print(f'[DRY RUN] Would run: {mvn} -pl start package -DskipTests')
        print(f'[DRY RUN] Working dir: {GW_BACKEND_START.parent}')
        return 0
    if not args.conf:
        print('This will run `mvn -pl start package -DskipTests` which may take 5-15 min.')
        print('Per [[r678-classifier-boundary]], USER must explicitly authorize this.')
        ans = input('Type "yes" to proceed, anything else to cancel: ').strip()
        if ans != 'yes':
            print('Cancelled.')
            return 130
    print(f'Running: {mvn} -pl start package -DskipTests')
    print(f'Working dir: {GW_BACKEND_START.parent}')
    try:
        result = subprocess.run(
            [mvn, '-pl', 'start', 'package', '-DskipTests'],
            cwd=str(GW_BACKEND_START.parent),
            timeout=900,
        )
        if result.returncode != 0:
            print(f'mvn failed with exit code {result.returncode}')
            return result.returncode
        print('mvn build succeeded.')
        if not JAR_LOCAL.exists():
            print(f'WARNING: {JAR_LOCAL} not found after build — check mvn output above')
            return 1
        print(f'Built: {JAR_LOCAL}')
        print(f'  size: {JAR_LOCAL.stat().st_size:,} bytes')
        print(f'  sha256: {_sha256(JAR_LOCAL)}')
        print()
        print('NEXT STEP:')
        print('  python rebuild-actuator-and-deploy.py deploy')
        return 0
    except subprocess.TimeoutExpired:
        print('mvn build timed out after 15 min')
        return 124


def cmd_deploy(args):
    """Phase B: transfer jar + restart divs-backend + verify."""
    print('=== Phase B: Deploy + restart + verify ===')
    if not JAR_LOCAL.exists():
        print(f'ERROR: {JAR_LOCAL} not found. Run `python rebuild-actuator-and-deploy.py build` first.')
        return 1
    zkb_path = next((p for p in ZKB_PATHS if p.exists()), None)
    if not zkb_path:
        print('ERROR: zkb.py not found at any candidate path. Need zkb for SFTP + docker.')
        return 1
    sys.path.insert(0, str(zkb_path.parent))
    try:
        from zkb import Zkb
    except ImportError as e:
        print(f'ERROR importing zkb: {e}')
        return 1
    z = Zkb()
    try:
        local_sha = _sha256(JAR_LOCAL)
        print(f'Uploading {JAR_LOCAL}')
        print(f'  size: {JAR_LOCAL.stat().st_size:,} bytes')
        print(f'  sha256: {local_sha}')
        print(f'  -> {REMOTE_JAR}')
        z.run(f'mkdir -p "{REMOTE_BACKEND_DIR}"')
        z.sftp_put(str(JAR_LOCAL), REMOTE_JAR)
        remote_sha, _ = z.run(f'sha256sum "{REMOTE_JAR}"')
        remote_sha = remote_sha.strip().split()[0]
        if remote_sha != local_sha:
            print(f'SHA MISMATCH: local={local_sha} remote={remote_sha}')
            print('Aborting — re-transfer required.')
            return 1
        print(f'Upload verified: SHA {remote_sha[:16]}... matches local')
        print()
        if not args.conf:
            print('This will restart divs-backend (5-10s downtime for backend API).')
            print('Per [[r678-classifier-boundary]], USER must explicitly authorize this.')
            ans = input('Type "yes" to proceed, anything else to cancel: ').strip()
            if ans != 'yes':
                print('Cancelled. Jar uploaded but not yet activated.')
                print('When ready, manually run: docker restart divs-backend')
                return 130
        print('Restarting divs-backend...')
        out, code = z.run(f'docker restart {REMOTE_CONTAINER}', timeout=60)
        if code != 0:
            print(f'docker restart failed: {out}')
            return code
        print(f'  {out.strip()}')
        print('Waiting for backend to be ready (max 60s)...')
        start = time.time()
        while time.time() - start < 60:
            txt, _ = z.run(f'docker exec {REMOTE_CONTAINER} curl -sf {REMOTE_HEALTH_URL}', timeout=10)
            if '{"status":"UP"}' in txt:
                elapsed = time.time() - start
                print(f'OK /actuator/health UP after {elapsed:.1f}s')
                print(f'   Body: {txt.strip()}')
                api_txt, _ = z.run(f'docker exec {REMOTE_CONTAINER} curl -sf {REMOTE_API_DOCS_URL} | head -c 200', timeout=10)
                print(f'   /v3/api-docs first 200 bytes: {api_txt.strip()[:100]}...')
                print()
                print('R6.98 #2 SUCCESS:')
                print('  - actuator dep active')
                print('  - /actuator/health returns {"status":"UP"}')
                print('  - /v3/api-docs still works (R6.96c canary no longer needed)')
                print()
                print('NEXT STEPS:')
                print('  1. Update backend-health.conf: upstream /actuator/health (was /v3/api-docs)')
                print('  2. Run sync-to-zjlab.py frontend to upload the new conf')
                print('  3. Optional cleanup: remove the canary workaround in R6.96c note')
                return 0
            time.sleep(2)
        print(f'TIMEOUT: /actuator/health did not return UP within 60s')
        print('Diagnose:')
        print(f'  docker logs {REMOTE_CONTAINER} --tail 50')
        print(f'  docker exec {REMOTE_CONTAINER} curl -v {REMOTE_HEALTH_URL}')
        return 1
    finally:
        z.close()


def cmd_verify(args):
    """Quick check: /actuator/health reachable from zjlab?"""
    print('=== Verify /actuator/health ===')
    zkb_path = next((p for p in ZKB_PATHS if p.exists()), None)
    if not zkb_path:
        print('ERROR: zkb.py not found')
        return 1
    sys.path.insert(0, str(zkb_path.parent))
    from zkb import Zkb
    z = Zkb()
    try:
        out, code = z.run(
            f'docker exec {REMOTE_CONTAINER} curl -sw "\\nHTTP=%{{http_code}}\\n" '
            f'{REMOTE_HEALTH_URL}', timeout=10,
        )
        print(f'Exit: {code}')
        print(out)
        if code == 0 and '{"status":"UP"}' in out:
            print('OK actuator/health is UP')
            return 0
        print('FAIL actuator/health NOT UP. Build + deploy may have failed.')
        return 1
    finally:
        z.close()


def cmd_all(args):
    """Build then deploy, with double confirmation."""
    print('This will:')
    print('  Phase A: Run `mvn -pl start package -DskipTests` (5-15 min build)')
    print('  Phase B: Upload jar + restart divs-backend + verify /actuator/health')
    print()
    print('Per [[r678-classifier-boundary]], USER must authorize EACH phase.')
    print()
    ans = input('Type "yes" to proceed with Phase A (build), anything else to cancel: ').strip()
    if ans != 'yes':
        print('Cancelled.')
        return 130
    rc = cmd_build(argparse.Namespace(dry_run=False, conf=True))
    if rc != 0:
        print(f'Phase A failed with exit {rc}. Aborting before Phase B.')
        return rc
    print()
    ans = input('Phase A succeeded. Type "yes" to proceed with Phase B (deploy), anything else to skip: ').strip()
    if ans != 'yes':
        print('Phase B skipped. Run `python rebuild-actuator-and-deploy.py deploy` when ready.')
        return 0
    return cmd_deploy(argparse.Namespace(conf=True))


def main():
    p = argparse.ArgumentParser(
        description='R6.98 #2: actuator jar rebuild + deploy (USER-authorized)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest='cmd_name', required=True)

    sp = sub.add_parser('check', help='Diagnostic only (mvn? actuator? jar?)')
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser('build', help='Phase A: mvn package')
    sp.add_argument('--dry-run', action='store_true', help='Show what would run, do not execute')
    sp.add_argument('--conf', action='store_true', help='Skip confirmation prompt')
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser('deploy', help='Phase B: deploy + restart + verify')
    sp.add_argument('--conf', action='store_true', help='Skip confirmation prompt')
    sp.set_defaults(func=cmd_deploy)

    sp = sub.add_parser('verify', help='Quick verify /actuator/health')
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser('all', help='Build then deploy, with double confirmation')
    sp.set_defaults(func=cmd_all)

    args = p.parse_args()
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())