#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-and-deploy-jar.py — R6.81a + R6.82: gw-backend jar build + deploy + rollback wrapper.

Why this exists:
  R6.80 (commit d43fd4e) shipped 3 deliverables (#4 zsmoke api-health, #5 MongoConfig,
  #7 /api/health controller). The CRITICAL pre-flight bug was:

      `mvn -pl start package`  (missing -am)

  rebuilds start.jar with STALE upstream JARs (gravitationalwave-server-service +
  gravitationalwave-server-web were not recompiled, .m2 cache reused old class files).
  Result: R6.79 R6.103 R6.78 changes never compiled into the deployed jar — JwtUtil
  `:?` fail-fast + HealthController + MongoConfig were silently missing from the live
  container until the `-am` flag was added.

  This script LOCKS IN `-am` as the only supported build command. There is no opt-out.
  It also unifies:
    - R6.97 #2 actuator jar rebuild [DEPRECATED R6.81a, stub RECYCLED 2026-09-11 via send2trash]
    - R6.103 rebuild-divs-backend-with-actuator [DEPRECATED R6.81a, stub RECYCLED 2026-09-11 via send2trash]
    - R6.80 jar deploy path (docker cp to divs-backend)

USAGE:
  python build-and-deploy-jar.py check     # diagnostic: mvn? JAVA_HOME? jar? deps?
  python build-and-deploy-jar.py build     # Phase A: mvn -pl start -am clean package
  python build-and-deploy-jar.py deploy    # Phase B: SFTP + docker cp + restart + wait
  python build-and-deploy-jar.py verify    # quick /api/health probe
  python build-and-deploy-jar.py rollback  # R6.82: restore app.jar.previous -> app.jar + SHA verify + restart
  python build-and-deploy-jar.py all       # build + deploy + verify (USER prompts)

PREREQUISITES:
  - Java 21 JDK (parent pom.java.version=21); `JAVA_HOME` env var must point to JDK 21
  - Portable Maven at D:\\AliCPT\\tools\\apache-maven-3.9.9\\bin\\mvn.cmd
    (or set `GW_MVN` env var to override path)
  - The mvn command is HARD-CODED to use `-pl start -am` (R6.80 critical fix).
    There is no flag, env var, or option to omit `-am`. Editing the script
    is the only way to change the build command — and the test suite
    guards against accidental removal.
  - Spring Boot deps cached in ~/.m2 (first build downloads ~500MB)
  - For Phase B: zkb.py importable (D:\\AliCPT\\scripts\\zkb.py)
  - zjlab credentials via 9 `ZJLAB_*` env vars (all-or-nothing); zkb.py
    falls back to parsing sync-to-zjlab.py when env vars are absent
    (Windows dev only — Phase B uses sync-to-zjlab.py credentials path
    automatically via `Zkb(sync_script_path=...)`)

WHY THESE EXIST (iron rules):
  - r678-classifier-boundary: 脚本生成 ✅ (this file), 自动执行 ❌ (USER must invoke
    each phase; --conf flag only with explicit USER authorization)
  - r676b-classifier-auth: USER must explicitly say "yes" at each phase (no implicit
    "go" or "fix this" interpretation)
  - parallel-review-after-batch: 3-perspective review REQUIRED before push
  - safe-int-env-helper: int() cast for any env-port reads (none used here directly,
    delegated to zkb.parse_creds)
  - recycle-bin-only: deletes (if any) must go to Recycle Bin via send2trash
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

# Force stdout/stderr to utf-8 (Windows defaults to GBK)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        pass

# === Paths ===
GW_BACKEND_ROOT = Path(r'D:\AliCPT\gw-backend')
GW_BACKEND_START = GW_BACKEND_ROOT / 'start'
TARGET_JAR = GW_BACKEND_START / 'target' / 'start.jar'

# === Maven (R6.80 lesson: never without -am) ===
DEFAULT_MVN = Path(r'D:\AliCPT\tools\apache-maven-3.9.9\bin\mvn.cmd')
MVN = Path(os.environ.get('GW_MVN', str(DEFAULT_MVN)))

# === zkb.py ===
ZKB_CANDIDATES = [
    Path(r'D:\AliCPT\scripts\zkb.py'),
    Path(r'C:\Users\28610\zkb.py'),  # legacy R6.95 location
]

# === Windows-dev credential fallback (R6.81a C1 deploy-review fix) ===
# zkb.py requires 9 ZJLAB_* env vars OR a sync_script_path. On Windows dev
# workstations the env vars are typically unset, so pass sync-to-zjlab.py
# explicitly. On zjlab itself the env vars are normally set and the
# fallback is harmless (zkb prefers env vars).
ZKB_SYNC_SCRIPT_FALLBACK = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py')

# === zjlab deployment ===
REMOTE_BACKEND_DIR = '/home/zjlab/gw-backend'
REMOTE_JAR_HOST = f'{REMOTE_BACKEND_DIR}/start.jar'
REMOTE_CONTAINER = 'divs-backend'
CONTAINER_JAR_PATH = '/home/gravitational-wave-backend/app.jar'
# R6.82: rollback support. PREVIOUS = last deploy's app.jar (one-step undo).
# BACKUP = the previous-previous (rotated out when a new deploy makes a new PREVIOUS).
CONTAINER_PREVIOUS_JAR_PATH = '/home/gravitational-wave-backend/app.jar.previous'
CONTAINER_BACKUP_JAR_PATH = '/home/gravitational-wave-backend/app.jar.backup'

# === Backend port (R6.81a M1 deploy-review fix: single source of truth) ===
BACKEND_PORT = 8093

# === Wait-for-UP timeout (R6.81a H2 deploy-review fix) ===
# Spring Boot cold start + MongoDB retry + connection pool init can take 60-120s on
# zjlab. 60s is too tight. Default 120s; --timeout flag still overrides.
DEFAULT_WAIT_TIMEOUT = 120

# === Verification (R6.80 lessons) ===
# These are the JARs that MUST be present in BOOT-INF/lib/. Missing any = stale upstream
# rebuild (the R6.80 bug) or pom.xml regression.
EXPECTED_BOOT_INF_LIBS = (
    # Spring Boot Actuator (R6.97 #2)
    'BOOT-INF/lib/spring-boot-actuator-3.4.1.jar',
    'BOOT-INF/lib/spring-boot-actuator-autoconfigure-3.4.1.jar',
    # Upstream reactor modules (R6.80 critical: these are what `-am` rebuilds)
    'BOOT-INF/lib/gravitationalwave-server-service-0.0.1-SNAPSHOT.jar',
    'BOOT-INF/lib/gravitationalwave-server-web-0.0.1-SNAPSHOT.jar',
)

# === Health endpoints ===
HEALTH_ENDPOINTS = (
    '/api/health',           # R6.80 new public-facing probe
    '/actuator/health',      # R6.97 #2 actuator (pre-existing)
    '/v3/api-docs',          # R6.38 springdoc-openapi canary
)


def sha256_file(path: Path) -> str:
    """SHA256 of a file (1 MiB chunks)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _check_mvn() -> Optional[str]:
    """Return absolute path to mvn executable, or None if not found."""
    if MVN.exists():
        return str(MVN)
    for c in ('mvn', 'mvn.cmd'):
        for path_dir in os.environ.get('PATH', '').split(os.pathsep):
            full = Path(path_dir) / c
            if full.exists():
                return str(full)
    m2 = os.environ.get('M2_HOME')
    if m2:
        for c in ('bin/mvn', 'bin/mvn.cmd'):
            full = Path(m2) / c
            if full.exists():
                return str(full)
    return None


def _java_home() -> Optional[str]:
    """Return JAVA_HOME (env) or None."""
    jh = os.environ.get('JAVA_HOME')
    if jh and Path(jh).exists():
        return jh
    return None


def _verify_jar_contents(jar_path: Path) -> tuple[bool, list[str]]:
    """Open start.jar (Spring Boot fat jar) and check EXPECTED_BOOT_INF_LIBS.

    R6.81a M2 fix: open the outer zip ONCE and reuse for all lookups
    (previously opened 5+ times). Inner nested jars are still opened
    separately (they require BytesIO round-trip).

    Returns (all_ok, list_of_messages).
    """
    msgs = []
    ok = True
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = set(zf.namelist())
            infolist = zf.infolist()
    except zipfile.BadZipFile as e:
        return False, [f'  [ERROR] {jar_path} is not a valid zip: {e}']

    name_to_info = {info.filename: info for info in infolist}

    # Verify required BOOT-INF/lib jars
    for required in EXPECTED_BOOT_INF_LIBS:
        if required in names:
            sz = name_to_info[required].file_size
            msgs.append(f'  [OK]  {required}  ({sz:,} bytes)')
        else:
            msgs.append(f'  [MISSING]  {required}')
            ok = False

    # Sanity: count all BOOT-INF/lib/ entries
    lib_count = sum(1 for n in names if n.startswith('BOOT-INF/lib/'))
    classes_count = sum(1 for n in names if n.startswith('BOOT-INF/classes/'))
    msgs.append(f'  [INFO] BOOT-INF/lib/ contains {lib_count} jars')
    msgs.append(f'  [INFO] BOOT-INF/classes/ contains {classes_count} entries')

    # If web module jar present, verify key R6.80/R6.79 classes are inside it.
    # NOTE: classes inside the inner nested jars are at the JAR ROOT (no
    # BOOT-INF/classes/ prefix). Only the start module's own classes use
    # BOOT-INF/classes/.
    web_inner = 'BOOT-INF/lib/gravitationalwave-server-web-0.0.1-SNAPSHOT.jar'
    service_inner = 'BOOT-INF/lib/gravitationalwave-server-service-0.0.1-SNAPSHOT.jar'
    KEY_CLASSES = (
        # (jar_inside_boot_inf, class_path, label)
        (web_inner, 'com/zhejianglab/gravitationalwave/gravitationalwaveserver/service/controller/HealthController.class',
         'HealthController (R6.80 /api/health)'),
        (service_inner, 'com/zhejianglab/gravitationalwave/gravitationalwaveserver/service/config/MongoConfig.class',
         'MongoConfig (R6.80 mongo resilience)'),
    )
    if web_inner in names or service_inner in names:
        with zipfile.ZipFile(jar_path, 'r') as outer:
            for inner_jar, class_path, label in KEY_CLASSES:
                if inner_jar not in names:
                    continue
                try:
                    with outer.open(inner_jar) as f:
                        inner_bytes = f.read()
                    with zipfile.ZipFile(io.BytesIO(inner_bytes), 'r') as inner:
                        if class_path in inner.namelist():
                            msgs.append(f'  [OK]  {label} present in {inner_jar}')
                        else:
                            msgs.append(f'  [MISSING]  {label} NOT in {inner_jar}  (R6.80 build bug?)')
                            ok = False
                except Exception as e:
                    msgs.append(f'  [WARN]  could not inspect {inner_jar}: {e}')

    return ok, msgs


def _import_zkb():
    """Find and import zkb.py. Returns (Zkb_class, error_msg)."""
    zkb_path = next((p for p in ZKB_CANDIDATES if p.exists()), None)
    if not zkb_path:
        return None, 'zkb.py not found at any candidate path'
    sys.path.insert(0, str(zkb_path.parent))
    try:
        from zkb import Zkb  # type: ignore
        return Zkb, None
    except ImportError as e:
        return None, f'import error: {e}'


def _instantiate_zkb():
    """Instantiate Zkb with Windows-dev fallback for credentials.

    R6.81a C1 deploy-review fix: zkb.parse_creds() raises RuntimeError if
    no ZJLAB_* env vars AND no sync_script_path. On a Windows dev box,
    the env vars are typically unset, so we explicitly pass the
    sync-to-zjlab.py path. On zjlab itself the env vars are normally
    set, and the fallback is harmless (zkb prefers env vars).

    R6.81b Tier 1 #3: explicit [WARN] log when fallback is missing so the
    user/dev sees that the ZJLAB_* env-var-only path was taken. Without
    this, a missing fallback would surface later as an opaque RuntimeError
    from zkb.parse_creds() with no breadcrumb back to the missing file.
    """
    Zkb, err = _import_zkb()
    if err:
        return None, err
    if ZKB_SYNC_SCRIPT_FALLBACK.exists():
        return Zkb(sync_script_path=ZKB_SYNC_SCRIPT_FALLBACK), None
    # Fallback missing — surface it now (R6.81b Tier 1 #3)
    print(
        f'[WARN] ZKB_SYNC_SCRIPT_FALLBACK not found: {ZKB_SYNC_SCRIPT_FALLBACK}',
        file=sys.stderr,
    )
    print(
        '[WARN] Attempting Zkb() with ZJLAB_* env vars only. If those are unset,'
        ' zkb.parse_creds() will raise RuntimeError.',
        file=sys.stderr,
    )
    return Zkb(), None  # pragma: no cover - unusual Windows setup


def cmd_check(args):
    """Diagnostic: prereqs + existing jar + actuator presence."""
    print('=== R6.81a build-and-deploy-jar diagnostic ===')
    print(f'GW_BACKEND_ROOT : {GW_BACKEND_ROOT}  {"OK" if GW_BACKEND_ROOT.exists() else "MISSING"}')
    print(f'GW_BACKEND_START: {GW_BACKEND_START}  {"OK" if GW_BACKEND_START.exists() else "MISSING"}')
    print(f'(parent pom.xml): {GW_BACKEND_ROOT / "pom.xml"}  '
          f'{"OK" if (GW_BACKEND_ROOT / "pom.xml").exists() else "MISSING"}')
    print(f'(start  pom.xml): {GW_BACKEND_START / "pom.xml"}  '
          f'{"OK" if (GW_BACKEND_START / "pom.xml").exists() else "MISSING"}')

    actuator_in_pom = (
        'spring-boot-starter-actuator' in (GW_BACKEND_START / 'pom.xml').read_text(encoding='utf-8')
        if (GW_BACKEND_START / 'pom.xml').exists() else False
    )
    print(f'actuator dep in start/pom.xml: {actuator_in_pom}')

    mvn = _check_mvn()
    print(f'Maven: {mvn or "NOT FOUND"}  (env GW_MVN override supported)')
    if mvn:
        try:
            out = subprocess.check_output(
                [mvn, '--version'], stderr=subprocess.STDOUT, timeout=15
            ).decode(errors='replace')
            first = out.splitlines()[0] if out.splitlines() else '(empty)'
            print(f'  {first}')
        except Exception as e:
            print(f'  mvn --version failed: {e}')

    jh = _java_home()
    print(f'JAVA_HOME: {jh or "NOT SET"}  (parent pom.xml requires java.version=21)')

    print(f'target jar: {TARGET_JAR}  '
          f'{"OK" if TARGET_JAR.exists() else "MISSING"}')
    if TARGET_JAR.exists():
        sz = TARGET_JAR.stat().st_size
        sha = sha256_file(TARGET_JAR)
        print(f'  size:  {sz:,} bytes  ({sz / 1024 / 1024:.2f} MB)')
        print(f'  sha256: {sha}')
        print('  contents check:')
        ok, msgs = _verify_jar_contents(TARGET_JAR)
        for m in msgs:
            print(m)
        if not ok:
            print('  [FAIL] jar is missing required BOOT-INF/lib entries — needs rebuild')
        else:
            print('  [OK] jar contents check passed')

    print()
    zkb_ok = next((p for p in ZKB_CANDIDATES if p.exists()), None)
    print(f'zkb.py (for deploy/verify): '
          f'{"OK " + str(zkb_ok) if zkb_ok else "MISSING (Phase B will fail)"}')
    print(f'zkb credential fallback: '
          f'{"OK " + str(ZKB_SYNC_SCRIPT_FALLBACK) if ZKB_SYNC_SCRIPT_FALLBACK.exists() else "MISSING"}')
    return 0


def cmd_build(args):
    """Phase A: mvn -pl start -am clean package -DskipTests -B -q.

    The `-am` flag is CRITICAL. Without it, mvn reuses stale .m2 cached upstream
    JARs (gravitationalwave-server-service, gravitationalwave-server-web) and the
    rebuilt start.jar does NOT contain recent Java changes. This was the R6.80
    pre-flight bug.
    """
    print('=== R6.81a Phase A: mvn build (FORCE -am) ===')
    if not GW_BACKEND_ROOT.exists():
        print(f'ERROR: {GW_BACKEND_ROOT} not found')
        return 1
    mvn = _check_mvn()
    if not mvn:
        print('ERROR: mvn not found.')
        print('Set GW_MVN env var to mvn.cmd path, or install Maven to:')
        print(f'  {DEFAULT_MVN}')
        print('Download from: https://maven.apache.org/download.cgi')
        return 1

    pre_sha = sha256_file(TARGET_JAR) if TARGET_JAR.exists() else '(no prior jar)'
    pre_size = TARGET_JAR.stat().st_size if TARGET_JAR.exists() else 0
    print(f'Pre-build jar: {TARGET_JAR}')
    print(f'  sha256: {pre_sha}')
    print(f'  size:   {pre_size:,} bytes ({pre_size / 1024 / 1024:.2f} MB)')
    print()

    # === THE -am FLAG IS NON-NEGOTIABLE ===
    cmd = [
        mvn,
        '-pl', 'start',
        '-am',                            # <-- R6.80 critical fix
        'clean',
        'package',
        '-DskipTests',
        '-B',                             # batch mode (non-interactive)
        '-q',                             # quiet (less noise; CI-friendly)
    ]
    print(f'Running: {" ".join(cmd)}')
    print(f'CWD:     {GW_BACKEND_ROOT}')
    print('-' * 70)

    if args.dry_run:
        print('[DRY RUN] mvn not actually invoked.')
        print('[DRY RUN] Verify the -am flag is in the command above.')
        return 0

    if not args.conf:
        print()
        print('This will:')
        print(f'  1. mvn clean (delete target/)')
        print(f'  2. mvn package (rebuild start module + upstream via -am)')
        print(f'  3. Estimated time: 5-15 min (first build downloads ~500MB deps)')
        print()
        print('Per [[r678-classifier-boundary]], USER must explicitly authorize this.')
        ans = input('Type "yes" to proceed, anything else to cancel: ').strip()
        if ans != 'yes':
            print('Cancelled.')
            return 2  # R6.81a M3 fix: 2 (not 130) for user-cancel

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(GW_BACKEND_ROOT), shell=False)
    elapsed = time.time() - t0
    print('-' * 70)
    if proc.returncode != 0:
        print(f'mvn FAILED (exit={proc.returncode}, elapsed={elapsed:.1f}s)')
        print('Check mvn output above. Common causes:')
        print('  - JAVA_HOME not set or wrong version (need JDK 21)')
        print('  - Network issue downloading deps')
        print('  - Compile error in source (run mvn without -q for details)')
        return proc.returncode
    print(f'mvn BUILD SUCCESS (elapsed={elapsed:.1f}s)')

    if not TARGET_JAR.exists():
        print(f'ERROR: {TARGET_JAR} not found after build')
        return 2

    post_sha = sha256_file(TARGET_JAR)
    post_size = TARGET_JAR.stat().st_size
    print()
    print(f'Post-build jar: {TARGET_JAR}')
    print(f'  sha256: {post_sha}')
    print(f'  size:   {post_size:,} bytes ({post_size / 1024 / 1024:.2f} MB)')
    if post_sha == pre_sha:
        print('  NOTE: SHA unchanged from pre-build. Possible causes:')
        print('    - No source changes since last build')
        print('    - mvn clean failed silently')
        print('    - mvn package used cache from .m2 (should NOT happen with -am)')

    print()
    print('=== Verifying BOOT-INF/lib contents (R6.80 lessons) ===')
    ok, msgs = _verify_jar_contents(TARGET_JAR)
    for m in msgs:
        print(m)
    if not ok:
        print()
        print('FAIL: jar missing required entries. Possible causes:')
        print('  - R6.80 bug regression (mvn without -am)')
        print('  - pom.xml regressed (actuator dep removed)')
        print('  - source compilation failed (check mvn output above)')
        return 3

    print()
    print('=== R6.81a BUILD OK ===')
    print(f'Rebuilt: {TARGET_JAR}')
    print(f'SHA256:  {post_sha}')
    print(f'Size:    {post_size:,} bytes ({post_size / 1024 / 1024:.2f} MB)')
    print()
    print('NEXT STEP (USER ACTION REQUIRED, per [[r678-classifier-boundary]]):')
    print('  python build-and-deploy-jar.py deploy')
    return 0


def cmd_deploy(args):
    """Phase B: SFTP jar to zjlab + docker cp into divs-backend + restart + wait.

    Per [[r678-classifier-boundary]]: USER must explicitly authorize (--conf or "yes"
    prompt). This script NEVER auto-deploys.

    R6.81a deploy-review fixes:
      - C1: zkb instantiated with sync_script_path fallback for Windows dev
      - H1: SHA verified after docker cp (host SHA + container SHA)
      - H2: default wait timeout 120s (was 60s)
      - R6.82-A: cmd_deploy MUST rotate app.jar -> app.jar.previous before docker cp
      - R6.82-B: cmd_rollback requires --conf OR interactive "yes" prompt
      - R6.82-C: cmd_rollback MUST verify SHA inside container before docker restart
    """
    print('=== R6.81a Phase B: deploy + restart + wait-for-UP ===')
    if not TARGET_JAR.exists():
        print(f'ERROR: {TARGET_JAR} not found. Run `build` first.')
        return 1

    z, err = _instantiate_zkb()
    if err:
        print(f'ERROR: {err}')
        print(f'Need one of: {[str(p) for p in ZKB_CANDIDATES]}')
        return 1

    local_sha = sha256_file(TARGET_JAR)
    local_size = TARGET_JAR.stat().st_size
    print(f'Local jar:  {TARGET_JAR}')
    print(f'  size:   {local_size:,} bytes ({local_size / 1024 / 1024:.2f} MB)')
    print(f'  sha256: {local_sha}')
    print()

    try:
        # 1. Pre-flight: confirm divs-backend container is running
        print('[pre-flight] Checking divs-backend container...')
        containers = z.docker_ps(name_filter='divs-backend')
        if not containers:
            print('  [ERROR] divs-backend container not running on zjlab.')
            print('  Cannot deploy. Start the container first.')
            return 1
        for c in containers:
            print(f'  - {c["name"]}  {c["status"]}')

        # 1.5 R6.82-A backup: rotate container app.jar -> app.jar.previous
        # (and previous -> backup if previous already exists) BEFORE docker cp.
        # This guarantees that a fresh `rollback` subcommand can restore the
        # current running jar. Without this, a bad deploy would be unrecoverable
        # without manual SFTP+docker cp.
        print('[backup] Rotating container app.jar -> app.jar.previous (R6.82-A)')
        # Check if a previous jar already exists; if so, rotate to .backup first
        prev_check_out, prev_check_code = z.run(
            f'docker exec {REMOTE_CONTAINER} sh -c "ls -la {CONTAINER_PREVIOUS_JAR_PATH} 2>/dev/null"',
            timeout=10,
        )
        if prev_check_code == 0 and CONTAINER_PREVIOUS_JAR_PATH in prev_check_out:
            print('  previous jar exists, rotating -> .backup')
            rot_out, rot_code = z.run(
                f'docker exec {REMOTE_CONTAINER} cp {CONTAINER_PREVIOUS_JAR_PATH} {CONTAINER_BACKUP_JAR_PATH}',
                timeout=60,
            )
            if rot_code != 0:
                print(f'  [WARN] previous->backup rotation failed (code={rot_code}): {rot_out}')
                print(f'  Continuing deploy anyway (backup is best-effort, .previous still writable).')
            else:
                print(f'  [OK] rotated -> {CONTAINER_BACKUP_JAR_PATH}')
                # Deploy C1: verify rotation produced non-empty .backup (defends
                # against partial cp that returned 0 but truncated the file).
                size_out, size_code = z.run(
                    f'docker exec {REMOTE_CONTAINER} sh -c "test -s {CONTAINER_BACKUP_JAR_PATH} && echo OK || echo EMPTY"',
                    timeout=10,
                )
                if size_code != 0 or 'OK' not in size_out:
                    print(f'  [FAIL] post-rotation .backup is empty/truncated: {size_out}')
                    return 1
        # Now back up the CURRENT app.jar to .previous
        backup_out, backup_code = z.run(
            f'docker exec {REMOTE_CONTAINER} cp {CONTAINER_JAR_PATH} {CONTAINER_PREVIOUS_JAR_PATH}',
            timeout=60,
        )
        if backup_code != 0:
            print(f'  [FAIL] container backup failed (code={backup_code}): {backup_out}')
            # Security Q5: surface .backup as manual recovery option
            print(f'  .backup retains the previous-previous jar: docker exec {REMOTE_CONTAINER} ls -la {CONTAINER_BACKUP_JAR_PATH}')
            print(f'  Manual recovery: docker exec {REMOTE_CONTAINER} cp {CONTAINER_BACKUP_JAR_PATH} {CONTAINER_JAR_PATH}')
            return 1
        print(f'  [OK] backup -> {CONTAINER_PREVIOUS_JAR_PATH}')

        # 2. SFTP upload to host
        print(f'[upload] SFTP {TARGET_JAR.name} -> {REMOTE_JAR_HOST}')
        z.run(f'mkdir -p "{REMOTE_BACKEND_DIR}"', timeout=15)
        z.sftp_put(str(TARGET_JAR), REMOTE_JAR_HOST)
        # SHA verify on host (H1 step 1/2)
        remote_sha, _ = z.run(f'sha256sum "{REMOTE_JAR_HOST}"', timeout=15)
        remote_sha = remote_sha.strip().split()[0]
        if remote_sha != local_sha:
            print(f'  [FAIL] host SHA mismatch: local={local_sha[:16]} remote={remote_sha[:16]}')
            return 1
        print(f'  [OK] host SHA verified: {remote_sha[:16]}...')

        # 3. docker cp into container
        print(f'[container] docker cp {REMOTE_JAR_HOST} -> {REMOTE_CONTAINER}:{CONTAINER_JAR_PATH}')
        out, code = z.run(
            f'docker cp {REMOTE_JAR_HOST} {REMOTE_CONTAINER}:{CONTAINER_JAR_PATH}',
            timeout=60,
        )
        if code != 0:
            print(f'  [FAIL] docker cp exit={code}: {out}')
            return code
        print(f'  [OK] {out.strip() or "copied"}')

        # 3.5 SHA verify inside container (H1 step 2/2 — catches partial/truncated jar)
        print(f'[verify] sha256sum inside {REMOTE_CONTAINER}:{CONTAINER_JAR_PATH}')
        container_sha_raw, code = z.run(
            f'docker exec {REMOTE_CONTAINER} sha256sum {CONTAINER_JAR_PATH}',
            timeout=15,
        )
        if code != 0:
            print(f'  [FAIL] container sha256sum exit={code}: {container_sha_raw}')
            return 1
        container_sha = container_sha_raw.strip().split()[0]
        if container_sha != local_sha:
            print(f'  [FAIL] container SHA mismatch: local={local_sha[:16]} '
                  f'container={container_sha[:16]}')
            print(f'         Likely partial/truncated docker cp. Aborting before restart.')
            return 1
        print(f'  [OK] container SHA verified: {container_sha[:16]}...')

        if not args.conf:
            print()
            print('About to restart divs-backend (5-10s downtime for backend API).')
            print('Per [[r678-classifier-boundary]], USER must explicitly authorize this.')
            ans = input('Type "yes" to restart, anything else to skip restart: ').strip()
            if ans != 'yes':
                print('Cancelled. Jar copied to container but NOT yet activated.')
                print('Activate manually with: docker restart divs-backend')
                return 2  # R6.81a M3 fix: 2 (not 130)

        # 4. docker restart
        print(f'[restart] docker restart {REMOTE_CONTAINER}')
        out, code = z.run(f'docker restart {REMOTE_CONTAINER}', timeout=60)
        if code != 0:
            print(f'  [FAIL] docker restart exit={code}: {out}')
            return code
        print(f'  [OK] {out.strip() or "restarted"}')

        # 5. Wait for /api/health = UP (H2: default 120s)
        timeout_s = args.timeout
        print(f'[wait] polling /api/health (max {timeout_s}s)...')
        start = time.time()
        health_url = f'http://localhost:{BACKEND_PORT}/api/health'
        last_status = None
        while time.time() - start < timeout_s:
            elapsed = time.time() - start
            # R6.86-A: probe via wget — divs-backend container is busybox shell
            # (has wget but NOT curl). Pre-R6.86 used `docker exec curl -sf -m 5`
            # which returned exit 126 with "OCI runtime exec failed: curl not
            # found" for 120s, falsely reporting deploy failure while the app
            # was always healthy. See [[divs-backend-curl-missing]] + [[r685-summary]]
            # incident 2026-09-11. wget -T 5 = 5s timeout (-T is wget's flag).
            probe_cmd = (
                f'docker exec {REMOTE_CONTAINER} wget -qO- -T 5 --tries=1 {health_url}'
            )
            out, code = z.run(probe_cmd, timeout=15)
            if code == 0 and out.strip():
                # Parse Response.wrapSuccess envelope: {"code":0,"message":"success","data":{"status":"UP",...}}
                if '"status":"UP"' in out:
                    print(f'  [OK] /api/health = UP after {elapsed:.1f}s')
                    print(f'    body: {out.strip()[:300]}')
                    # R6.83 V1 + R6.85b + R6.88 markers via Zkb.check_marker_log() (generalized R6.84b).
                    # 6-marker AND-check: HealthController (R6.83) + LlmController (R6.85b) +
                    #   PipelineProxyController (R6.85b) + StaticFileController (R6.88) +
                    #   SearchController (R6.88) + ImageCutoutController (R6.88).
                    # Without this AND-check, a `mvn -pl start package` without `-am` would silently ship
                    # stale LlmController/PipelineProxyController/StaticFileController/SearchController/
                    # ImageCutoutController bytecode and pass /api/health UP.
                    # KEY_CLASSES whitelist cannot distinguish R6.80 vs R6.85 vs R6.88 bytecode because
                    # all 6 controller classes existed before their respective marker log lines were added.
                    # Marker lines emitted by @PostConstruct methods:
                    #   R6.83:  "R6.83: HealthController probe executor initialized (2 threads, daemon=true)"
                    #   R6.85b: "R6.85b: LlmController RestTemplate initialized (connect=10s, read=30s)"
                    #   R6.85b: "R6.85b: PipelineProxyController RestTemplate initialized (connect=30s, read=30s)"
                    #   R6.88:  "R6.88: StaticFileController initialized"
                    #   R6.88:  "R6.88: SearchController initialized"
                    #   R6.88:  "R6.88: ImageCutoutController initialized"
                    v1_markers = [
                        'R6.83: HealthController probe executor initialized',
                        'R6.85b: LlmController RestTemplate initialized',
                        'R6.85b: PipelineProxyController RestTemplate initialized',
                        'R6.88: StaticFileController initialized',
                        'R6.88: SearchController initialized',
                        'R6.88: ImageCutoutController initialized',
                    ]
                    markers_found, markers_snippet = z.check_marker_log(
                        REMOTE_CONTAINER,
                        v1_markers,
                    )
                    if markers_found:
                        print(f'  [V1] All {len(v1_markers)} markers found in container logs (R6.83 + R6.85b deploy confirmed)')
                    else:
                        # R6.89 F1: compute missing directly from v1_markers against the
                        # actual log snippet (markers_snippet is raw docker logs, NOT
                        # 'FOUND:<marker>' prefixed). Pre-R6.89 the check `f'FOUND:{marker}'
                        # not in markers_snippet` always evaluated True (the 'FOUND:' prefix
                        # never appears in raw logs), so the Missing list was always empty
                        # even when markers were missing.
                        missing = [m for m in v1_markers if m not in markers_snippet]
                        print(f'  [WARN V1] {len(missing)}/{len(v1_markers)} marker(s) NOT found in container logs.')
                        print(f'           Missing: {missing}')
                        print('           If you are deploying R6.83+R6.85b and any marker is missing,')
                        print('           the jar has stale bytecode. Check: did mvn run with -am flag?')
                        print('           Pre-R6.83 jars (no marker) are valid; post-R6.83 jars MUST emit R6.83 line.')
                        print('           Post-R6.85b jars MUST emit both R6.85b lines.')
                        if markers_snippet:
                            print(f'           Recent log grep output: {markers_snippet[:200]}')
                    return 0
                last_status = out.strip()[:200]
                print(f'  ... {elapsed:.1f}s status not UP: {last_status}')
            else:
                print(f'  ... {elapsed:.1f}s wget exit={code} (container still starting)')
            time.sleep(2)

        print()
        print(f'[FAIL] /api/health did not return UP within {timeout_s}s')
        print(f'  last status: {last_status}')
        print()
        print('Diagnose:')
        print(f'  docker logs {REMOTE_CONTAINER} --tail 100')
        # R6.86-A: divs-backend is busybox; use wget not curl for in-container probes.
        # Flags match probe_cmd (line 612) so operators copy-pasting the hint
        # get the same fail-fast behavior:
        #   -q   = quiet (no progress; body only)
        #   -O - = stdout
        #   -T 5 = 5s read timeout (wget's flag is -T, NOT curl's -m)
        #   --tries=1 = single attempt, no retry (default retries 20 with backoff,
        #               would block the polling loop on a slow container)
        # busybox wget exit codes:
        #   0 = success (HTTP 2xx), 4 = network/connect failure, 5 = SSL verify,
        #   8 = server error response (4xx/5xx).
        print(f'  docker exec {REMOTE_CONTAINER} wget -qO- -T 5 --tries=1 '
              f'http://localhost:{BACKEND_PORT}/api/health')
        print(f'  docker exec {REMOTE_CONTAINER} ls -la {CONTAINER_JAR_PATH}')
        return 1
    finally:
        z.close()


def cmd_rollback(args):
    """R6.82: restore previous app.jar in container + restart.

    Iron rules:
      - R6.82-B: requires --yes OR interactive prompt (per [[r678-classifier-boundary]])
      - R6.82-C: SHA verify inside container before docker restart (H1 invariant)

    Sequence:
      1. Pre-flight: container running + .previous exists
      2. SHA verify inside container of .previous (capture)
      3. docker exec ... cp .previous app.jar
      4. SHA verify inside container of app.jar (must match capture)
      5. Interactive prompt (or --yes): restart with restored jar
      6. docker restart divs-backend
      7. Wait for /api/health = UP (H2 default 120s)
    """
    # Security Q8: timestamped audit prefix on every rollback print (post-mortem)
    from datetime import datetime
    _ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    print(f'=== R6.82 rollback @ {_ts}: restore previous app.jar + restart ===')
    z, err = _instantiate_zkb()
    if err:
        print(f'ERROR: {err}')
        return 1
    try:
        # 1. Pre-flight
        print('[pre-flight] Checking divs-backend container...')
        containers = z.docker_ps(name_filter='divs-backend')
        if not containers:
            print('  [ERROR] divs-backend container not running on zjlab.')
            return 1
        for c in containers:
            print(f'  - {c["name"]}  {c["status"]}')

        # 2. Verify .previous exists
        prev_out, prev_code = z.run(
            f'docker exec {REMOTE_CONTAINER} sh -c "ls -la {CONTAINER_PREVIOUS_JAR_PATH} 2>/dev/null"',
            timeout=10,
        )
        if prev_code != 0 or CONTAINER_PREVIOUS_JAR_PATH not in prev_out:
            print(f'  [ERROR] No previous jar to roll back to: {CONTAINER_PREVIOUS_JAR_PATH}')
            print('  Either this is the first deploy, or .previous was rotated to .backup.')
            print(f'  Check: docker exec {REMOTE_CONTAINER} ls -la {CONTAINER_BACKUP_JAR_PATH}')
            return 1
        print(f'  [OK] {CONTAINER_PREVIOUS_JAR_PATH} present')

        # 3. SHA verify .previous (capture)
        prev_sha_raw, prev_sha_code = z.run(
            f'docker exec {REMOTE_CONTAINER} sha256sum {CONTAINER_PREVIOUS_JAR_PATH}',
            timeout=15,
        )
        if prev_sha_code != 0:
            print(f'  [FAIL] sha256sum .previous exit={prev_sha_code}: {prev_sha_raw}')
            return 1
        prev_sha = prev_sha_raw.strip().split()[0]
        print(f'  .previous sha256: {prev_sha[:16]}...')

        # 4. Restore .previous -> app.jar
        print(f'[restore] docker exec ... cp {CONTAINER_PREVIOUS_JAR_PATH} {CONTAINER_JAR_PATH}')
        cp_out, cp_code = z.run(
            f'docker exec {REMOTE_CONTAINER} cp {CONTAINER_PREVIOUS_JAR_PATH} {CONTAINER_JAR_PATH}',
            timeout=60,
        )
        if cp_code != 0:
            print(f'  [FAIL] restore cp exit={cp_code}: {cp_out}')
            return 1
        print(f'  [OK] restored')

        # 5. SHA verify app.jar (must match .previous)
        app_sha_raw, app_sha_code = z.run(
            f'docker exec {REMOTE_CONTAINER} sha256sum {CONTAINER_JAR_PATH}',
            timeout=15,
        )
        if app_sha_code != 0:
            print(f'  [FAIL] sha256sum app.jar exit={app_sha_code}: {app_sha_raw}')
            return 1
        app_sha = app_sha_raw.strip().split()[0]
        if app_sha != prev_sha:
            print(f'  [FAIL] post-restore SHA mismatch: previous={prev_sha[:16]} app.jar={app_sha[:16]}')
            print('         Likely partial/truncated cp. Aborting before restart.')
            return 1
        print(f'  [OK] app.jar sha256 verified: {app_sha[:16]}...')

        # 6. Interactive prompt (unless --conf)
        # Security Q1: --conf is process-trust only (matches cmd_deploy pattern);
        # audit-print so post-mortems can distinguish prompted vs. unprompted
        if args.conf:
            print('  [AUDIT] rollback invoked with --conf (USER authorization assumed)')
        if not args.conf:
            print()
            print('About to restart divs-backend with rolled-back jar (5-10s downtime).')
            print('Per [[r678-classifier-boundary]], USER must explicitly authorize this.')
            ans = input('Type "yes" to restart, anything else to skip restart: ').strip()
            if ans != 'yes':
                print('Cancelled. Jar restored to container but NOT yet activated.')
                print('Activate manually with: docker restart divs-backend')
                return 2  # R6.81a M3 pattern: 2 (not 130)

        # 7. Restart
        print(f'[restart] docker restart {REMOTE_CONTAINER}')
        out, code = z.run(f'docker restart {REMOTE_CONTAINER}', timeout=60)
        if code != 0:
            print(f'  [FAIL] docker restart exit={code}: {out}')
            return code
        print(f'  [OK] {out.strip() or "restarted"}')

        # 8. Wait for /api/health = UP (H2 default 120s)
        timeout_s = args.timeout
        print(f'[wait] polling /api/health (max {timeout_s}s)...')
        start = time.time()
        health_url = f'http://localhost:{BACKEND_PORT}/api/health'
        last_status = None
        while time.time() - start < timeout_s:
            elapsed = time.time() - start
            out, code = z.run(
                f'docker exec {REMOTE_CONTAINER} curl -sf -m 5 {health_url}',
                timeout=15,
            )
            if code == 0 and out.strip():
                if '"status":"UP"' in out:
                    print(f'  [OK] /api/health = UP after {elapsed:.1f}s')
                    print(f'    body: {out.strip()[:300]}')
                    print()
                    print('Rollback complete. Note: app.jar.backup is the previous-previous jar if needed.')
                    # Security Q8: final structured audit summary line
                    print(f'=== AUDIT: rollback complete @ {_ts}, restart={elapsed:.1f}s, health=UP ===')
                    return 0
                last_status = out.strip()[:200]
                print(f'  ... {elapsed:.1f}s status not UP: {last_status}')
            else:
                print(f'  ... {elapsed:.1f}s curl exit={code} (container still starting)')
            time.sleep(2)

        print()
        print(f'[FAIL] /api/health did not return UP within {timeout_s}s')
        print(f'  last status: {last_status}')
        print()
        print('Diagnose:')
        print(f'  docker logs {REMOTE_CONTAINER} --tail 100')
        print(f'  docker exec {REMOTE_CONTAINER} curl -v http://localhost:{BACKEND_PORT}/actuator/health')
        # Security Q8: surface multi-deploy limitation
        print()
        print('Note: .previous still holds the OLD jar. A subsequent deploy will rotate')
        print('  .previous -> .backup, losing the one-before-current history.')
        return 1
    finally:
        z.close()


def cmd_verify(args):
    """Quick verify: /api/health (R6.80) + /actuator/health (R6.97 #2) + /v3/api-docs."""
    print('=== R6.81a verify: health endpoints ===')
    z, err = _instantiate_zkb()
    if err:
        print(f'ERROR: {err}')
        return 1
    try:
        containers = z.docker_ps(name_filter='divs-backend')
        if not containers:
            print(f'ERROR: {REMOTE_CONTAINER} not running')
            return 1
        for c in containers:
            print(f'  {c["name"]}  {c["status"]}')
        print()
        all_ok = True
        for endpoint in HEALTH_ENDPOINTS:
            url = f'http://localhost:{BACKEND_PORT}{endpoint}'
            out, code = z.run(
                f'docker exec {REMOTE_CONTAINER} curl -sf -m 5 -w "\\nHTTP=%{{http_code}}\\n" {url}',
                timeout=15,
            )
            http_line = [l for l in out.splitlines() if l.startswith('HTTP=')]
            http_code = http_line[0].split('=')[1] if http_line else '?'
            body = '\n'.join(l for l in out.splitlines() if not l.startswith('HTTP='))
            ok = code == 0 and http_code in ('200',)
            status = '[OK]  ' if ok else '[FAIL]'
            print(f'  {status} {endpoint:25} HTTP {http_code}')
            if not ok:
                print(f'         curl exit={code}, body[:200]: {body[:200]}')
                all_ok = False
            else:
                print(f'         body[:150]: {body[:150].replace(chr(10), " ")}')

        print()
        if all_ok:
            print('=== verify OK: all 3 health endpoints 200 ===')
            return 0
        print('=== verify FAIL ===')
        return 1
    finally:
        z.close()


def cmd_all(args):
    """Build + deploy + verify with USER prompts per phase.

    R6.81a M4 fix: pass the full `args` object to sub-commands so future
    build-phase args propagate automatically (no fragile Namespace construction).
    """
    print('R6.81a `all` will:')
    print('  Phase A: mvn -pl start -am clean package -DskipTests -B -q  (5-15 min)')
    print('  Phase B: SFTP + docker cp + docker restart divs-backend  (30-60s)')
    print('  Verify:  /api/health, /actuator/health, /v3/api-docs  (5-10s)')
    print()
    print('Per [[r678-classifier-boundary]], USER must authorize EACH phase.')
    print()

    ans = input('Type "yes" to start Phase A (build), anything else to cancel: ').strip()
    if ans != 'yes':
        print('Cancelled.')
        return 2  # R6.81a M3 fix
    # Pass full args so future build-phase args propagate (M4 fix)
    rc = cmd_build(args)
    if rc != 0:
        print(f'Phase A failed (exit {rc}). Aborting before Phase B.')
        return rc

    print()
    ans = input('Phase A OK. Type "yes" to start Phase B (deploy + restart): ').strip()
    if ans != 'yes':
        print('Phase B skipped. Run `python build-and-deploy-jar.py deploy` when ready.')
        return 0
    rc = cmd_deploy(args)
    if rc != 0:
        print(f'Phase B failed (exit {rc}). Jar may be uploaded but not active.')
        return rc

    print()
    return cmd_verify(args)


def main():
    p = argparse.ArgumentParser(
        description='R6.81a+R6.82: gw-backend start.jar build, deploy, and rollback',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest='cmd_name', required=True)

    sp = sub.add_parser('check', help='Diagnostic: mvn / JAVA_HOME / jar / zkb.py')
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser('build', help='Phase A: mvn -pl start -am clean package')
    sp.add_argument('--dry-run', action='store_true',
                    help='Show command without executing')
    sp.add_argument('--conf', action='store_true',
                    help='Skip USER confirmation prompt (only with explicit auth)')
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser('deploy', help='Phase B: SFTP + docker cp + restart + wait-for-UP')
    sp.add_argument('--conf', action='store_true',
                    help='Skip USER restart confirmation (only with explicit auth)')
    sp.add_argument('--timeout', type=int, default=DEFAULT_WAIT_TIMEOUT,
                    help=f'Wait-for-UP timeout in seconds (default {DEFAULT_WAIT_TIMEOUT})')
    sp.set_defaults(func=cmd_deploy)

    sp = sub.add_parser('rollback', help='R6.82: restore previous container jar + restart')
    sp.add_argument('--conf', action='store_true',
                    help='Skip USER restart confirmation (only with explicit auth)')
    sp.add_argument('--timeout', type=int, default=DEFAULT_WAIT_TIMEOUT,
                    help=f'Wait-for-UP timeout in seconds (default {DEFAULT_WAIT_TIMEOUT})')
    sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser('verify', help='Quick /api/health + /actuator/health + /v3/api-docs')
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser('all', help='Build + deploy + verify (USER prompts per phase)')
    sp.add_argument('--timeout', type=int, default=DEFAULT_WAIT_TIMEOUT,
                    help=f'Wait-for-UP timeout in seconds (default {DEFAULT_WAIT_TIMEOUT})')
    sp.set_defaults(func=cmd_all)

    args = p.parse_args()
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print('Cancelled by user.')
        return 130


if __name__ == '__main__':
    sys.exit(main())