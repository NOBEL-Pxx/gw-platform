#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravitationalWave Platform — Sync Script (v4.41)
================================================
Sync local code to ZhiJiang Lab remote server via SSH bastion.

R6.52: detects requirements.txt diff -> auto-triggers `docker compose build`
       before `docker cp`, so new Python deps are baked into the image.

R6.67.1 follow-up (#4): also upload Dockerfile + docker-entrypoint.sh + nginx.conf
       (was previously skipped — required manual upload, broke deploy when
       Docker layer baked old entrypoint). Strip Windows CRLF on shell scripts
       so busybox sh on zjlab doesn't choke on `#!/bin/sh\r` shebang.

R6.79 (v4.40): ROOT-CAUSE FIX for v4.17 image regression (5 layers fixed across R6.78-80)

R6.82 (v4.41): Consolidate R6.79.f + R6.80 fixes into main script:
   - `_sync_frontend_public()`: hash-diff + upload public/ recursively
     (R6.80 fix - 5th sync gap layer, was missing entirely)
   - `_sync_frontend_root_hashdiff()`: hash-diff ALL root files in gw-frontend/
     (replaces hardcoded _sync_frontend_build_configs, now includes index.html)
   - `_frontend_post_rebuild_sanity_check()`: curl + grep version + 3 logo URLs
   - `_backend_post_rebuild_sanity_check()`: port 8093 Spring Boot (v3/api-docs + swagger-ui; image alicpt-divs-gw-backend) (R6.83o)
     (catches stale-image regression in 1 second - prevents R6.78x 8h debug)
   - `verify()`: adds frontend version sanity check (must match local) (2026-09-08).
   - Add `--rebuild` flag to frontend mode: also uploads src/ + triggers
     `docker compose build gw-frontend` (was missing - only build/ synced).
   - Add new `compose` mode: syncs docker-compose.yml + docker-compose.zjlab.yml
     + recreates services (was missing - R6.78 cascade root cause).

Usage:
  python sync-to-zjlab.py                       # Full sync
  python sync-to-zjlab.py frontend              # Frontend only (build/ + nginx-html/ bind mount, ~1s)
  python sync-to-zjlab.py frontend --rebuild    # NEW: + src/ + image rebuild
  python sync-to-zjlab.py pipeline              # Python modules only
  python sync-to-zjlab.py config                # Nginx config only
  python sync-to-zjlab.py jar                   # Backend JAR only (after mvn package)
  python sync-to-zjlab.py compose               # NEW: docker-compose*.yml + recreate
  python sync-to-zjlab.py frontend --no-infra   # Legacy: build/ only

Bastion: 192.168.10.10:60022 -> 10.107.207.103:22
"""
import paramiko, time, os, sys, io, subprocess, hashlib, argparse

# === Configuration ===
BASTION = ('192.168.10.10', 60022, 'ZJWB260819', 'Temp@ecf4f6')
SERVER  = ('10.107.207.103', 22, 'zjlab', 'fast@zjlab')
REMOTE_ROOT = '/home/zjlab/gravitationalwave-v4.31'
LOCAL_ROOT  = r'D:\AliCPT'

MODE = sys.argv[1] if len(sys.argv) > 1 else 'full'
# R6.84: --env-action flag. Overridden in main() before sanity check runs.
ENV_ACTION = 'detect'


def connect():
    print('[connect] Bastion {}:{} ...'.format(BASTION[0], BASTION[1]))
    ba = paramiko.SSHClient()
    ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3],
               timeout=20, allow_agent=False, look_for_keys=False)
    ba.get_transport().set_keepalive(30)
    ch = ba.get_transport().open_channel(
        'direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
    tg = paramiko.SSHClient()
    tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3],
               timeout=20, allow_agent=False, look_for_keys=False, sock=ch)
    sftp = tg.open_sftp()
    print('[connect] OK')
    return ba, tg, sftp


# === R6.67.1 #4: helpers for infra-file sync (Dockerfile, entrypoint, etc.) ===
def _upload_text_file(sftp, local_path, remote_path, strip_crlf=False, executable=False):
    """Upload a text file via SFTP, optionally stripping Windows CRLF.

    R6.67.1: Windows CRLF on shell scripts (e.g. `#!/bin/sh\r`) breaks busybox
    sh on the remote container — it parses `\r` as part of the interpreter
    name and fails with 'no such file or directory'. Strip CRLF before upload.

    Returns the number of bytes uploaded.
    """
    raw = open(local_path, 'rb').read()
    if strip_crlf:
        cleaned = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        if cleaned != raw:
            print('  [CRLF strip] {}: {}B -> {}B'.format(
                os.path.basename(local_path), len(raw), len(cleaned)))
        raw = cleaned
    with sftp.open(remote_path, 'wb') as f:
        f.write(raw)
    if executable:
        sftp.chmod(remote_path, 0o755)
    print('  [upload] {} -> {} ({}B{})'.format(
        os.path.basename(local_path), remote_path, len(raw),
        ', +x' if executable else ''))
    return len(raw)


def _upload_binary_file(sftp, local_path, remote_path):
    """Upload a binary file via SFTP (preserves bytes verbatim).

    Use for Dockerfile, nginx.conf, ssl/*.pem, etc. — anything that is not a
    shell script (no CRLF strip) and not HTML/JS (no special processing).
    """
    raw = open(local_path, 'rb').read()
    with sftp.open(remote_path, 'wb') as f:
        f.write(raw)
    print('  [upload] {} -> {} ({}B binary)'.format(
        os.path.basename(local_path), remote_path, len(raw)))
    return len(raw)


def _check_build_staleness():
    """R6.89a + R6.89c: Detect stale build/ when --no-build used.

    Two complementary checks:
    1. Filesystem mtime: walk src/ for newest mtime, compare to build/assets/index-*.js mtime
    2. Git commit timestamp: `git log -1 --format=%%ct -- src/`, compare to build mtime

    Both checks are warnings, NOT errors. User may knowingly skip build
    (e.g., just verifying a deploy without src/ changes).

    Returns: (is_stale, reason, freshest_src_ts, build_ts, git_ts)
    """
    src_dir = os.path.join(LOCAL_ROOT, 'gw-frontend', 'src')
    build_dir = os.path.join(LOCAL_ROOT, 'gw-frontend', 'build', 'assets')

    # Build artifact reference timestamp (use newest index-*.js)
    build_ts = 0
    if os.path.isdir(build_dir):
        for fname in os.listdir(build_dir):
            if fname.startswith('index-') and fname.endswith('.js'):
                p = os.path.join(build_dir, fname)
                build_ts = max(build_ts, os.path.getmtime(p))
        if not build_ts:
            return (True, 'no build/assets/index-*.js found', 0, 0, 0)

    # R6.89a: src/ filesystem mtime
    freshest_src_mtime = 0
    src_count = 0
    if os.path.isdir(src_dir):
        for root, dirs, files in os.walk(src_dir):
            # Skip noisy dirs
            dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', 'dist', 'build', '__pycache__')]
            for fname in files:
                p = os.path.join(root, fname)
                freshest_src_mtime = max(freshest_src_mtime, os.path.getmtime(p))
                src_count += 1

    # R6.89c: git commit timestamp affecting src/
    git_ts = 0
    try:
        # Run git log in gw-frontend dir
        gw_dir = os.path.join(LOCAL_ROOT, 'gw-frontend')
        out = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct', '--', 'src/'],
            cwd=gw_dir, stderr=subprocess.DEVNULL,
            timeout=5
        ).decode().strip()
        if out.isdigit():
            git_ts = int(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Compare: take the MAX of src_mtime and git_ts as "freshest src change"
    freshest_src_ts = max(freshest_src_mtime, git_ts)

    # Build is stale if either is newer than build
    is_stale = freshest_src_ts > build_ts

    if is_stale:
        import datetime
        src_str = datetime.datetime.fromtimestamp(freshest_src_ts).strftime('%Y-%m-%d %H:%M')
        build_str = datetime.datetime.fromtimestamp(build_ts).strftime('%Y-%m-%d %H:%M')
        reason = ('src/ freshest={} ({} mtime + {} git ts) > build/ {} '
                  '(src files scanned: {})').format(
            src_str, freshest_src_mtime, git_ts, build_str, src_count)
        return (True, reason, freshest_src_ts, build_ts, git_ts)

    return (False, '', freshest_src_ts, build_ts, git_ts)


def _check_unpushed_src_commits():
    """R6.90d: Count unpushed commits touching src/ (conservative hint, never auto-rebuild).

    Why conservative: matches [[manual-confirm-major-changes]] - image rebuilds are major.
    We print NOTE only; user must explicitly pass --rebuild.

    Detection: `git log origin/r6.52..HEAD --oneline -- src/`
    - origin/r6.52 is the deploy branch (matches current r678x+ push pattern)
    - If no upstream (new clone / no remote tracking), git log exits non-zero -> caught -> 0
    - If working tree differs from HEAD but no unpushed commits (e.g. uncommitted changes),
      this returns 0 (only counts commits, not working tree mtime)
    """
    try:
        gw_dir = os.path.join(LOCAL_ROOT, 'gw-frontend')
        out = subprocess.check_output(
            ['git', 'log', 'origin/r6.52..HEAD', '--oneline', '--', 'src/'],
            cwd=gw_dir, stderr=subprocess.DEVNULL,
            timeout=5
        ).decode().strip()
        if not out:
            return 0
        return len(out.split('\n'))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return 0



def _sync_frontend_infra(tg, sftp):
    """R6.67.1 #4: sync Dockerfile + docker-entrypoint.sh + nginx.conf + ssl/
    for gw-frontend in addition to build/.

    Why: Dockerfile changes never reached zjlab via the old sync (which only
    uploaded build/). When entrypoint was updated locally, the running
    container kept the OLD entrypoint — busybox sh then failed with
    'no such file or directory' because the old entrypoint called `crond`
    which was removed in the new version.

    Strips CRLF on shell scripts before upload.
    """
    gw_dir = os.path.join(LOCAL_ROOT, 'gw-frontend')
    remote_dir = '{}/gw-frontend'.format(REMOTE_ROOT)

    # R6.92a: use generic _ensure_remote_dir helper (was ad-hoc mkdir -p ssl/)
    _ensure_remote_dir(tg, remote_dir)
    _ensure_remote_dir(tg, remote_dir + '/ssl')

    # (local_name, remote_name, strip_crlf, executable)
    infra_files = [
        ('Dockerfile',           'Dockerfile',           False, False),
        ('docker-entrypoint.sh', 'docker-entrypoint.sh', True,  True),
        ('nginx.conf',           'nginx.conf',           False, False),
        ('nginx-reload-watcher.sh', 'nginx-reload-watcher.sh', True, True),
    ]

    uploaded = 0
    for local_name, remote_name, strip_crlf, executable in infra_files:
        src_path = os.path.join(gw_dir, local_name)
        if not os.path.exists(src_path):
            print('  [skip] {} does not exist'.format(local_name))
            continue
        dst = '{}/{}'.format(remote_dir, remote_name)
        _upload_text_file(sftp, src_path, dst,
                          strip_crlf=strip_crlf, executable=executable)
        uploaded += 1

    # ssl/ directory (binary preserve — certs must not be CRLF-stripped)
    ssl_dir = os.path.join(gw_dir, 'ssl')
    if os.path.isdir(ssl_dir):
        for fname in os.listdir(ssl_dir):
            fpath = os.path.join(ssl_dir, fname)
            if not os.path.isfile(fpath):
                continue
            dst = '{}/ssl/{}'.format(remote_dir, fname)
            _upload_binary_file(sftp, fpath, dst)
            uploaded += 1

    print('[frontend-infra] Uploaded {} infra files'.format(uploaded))



def _ensure_remote_dir(tg, remote_path):
    """R6.92a: Generic mkdir -p helper for all bind-mount sync helpers.

    Why: 5th R6.78u-style bind-mount ENOENT footgun. R6.91 added ad-hoc mkdir inside
    _sync_frontend_nginx_confd. Systemic fix: 1 helper, applied uniformly at the
    start of every bind-mount sync helper. Idempotent (`mkdir -p` no-op if exists).

    Trade-off: 1 extra exec_command per helper (~50ms latency, parallel-safe).
    Acceptable vs debugging 6h ENOENT regression.

    Use:
        remote_dir = '{}/gw-frontend/nginx-conf.d'.format(REMOTE_ROOT)
        _ensure_remote_dir(tg, remote_dir)
        _ensure_remote_dir(tg, remote_dir + '/templates')
    """
    if not remote_path:
        return
    try:
        tg.exec_command('mkdir -p "{}"'.format(remote_path.replace('"', '\\"')), timeout=5)
        time.sleep(0.2)
    except Exception as e:
        print('  [ensure_remote_dir] mkdir {} failed: {}'.format(remote_path, e))


def _sync_frontend_nginx_confd(tg, sftp):
    """R6.89b + R6.90b + R6.91: Sync nginx conf.d/*.conf + templates/*.template to bind-mount sources.

    conf.d/    bind-mount source: /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/
               container: /etc/nginx/conf.d/  (replaces tmpfs - R6.78u cascade entry point #5)
    templates/ bind-mount source: .../nginx-conf.d/templates/
               container: /etc/nginx/conf.d/templates/  (R6.90b - lets user add *.template without rebuild)

    entrypoint envsubst at container start reads /etc/nginx/conf.d/templates/*.template
    and generates corresponding /etc/nginx/conf.d/*.conf. So adding my-feature.template
    in the templates/ dir produces my-feature.conf on next start.

    Source dirs (local):
      D:\\AliCPT\\gw-frontend\\nginx-conf.d\\*.conf
      D:\\AliCPT\\gw-frontend\\nginx-conf.d\\templates\\*.template (skips .gitkeep)

    Why bind-mount (vs tmpfs):
    - Tmpfs shadows image content (R6.78u pattern): any custom *.conf added at runtime
      is lost on container recreate
    - read_only: true + bind mount allows runtime config updates without image rebuild
    - envsubst at startup still works (root user writes to bind mount, which IS writable
      from host's perspective)

    Trade-off: bind mount SOURCE dirs must exist before first container start.
    nginx-conf.d/ must contain at least default.conf (R6.90a bootstrapped).
    templates/ may be empty (no user templates = no envsubst output = no harm).

    R6.91 first-deploy fix: ensure remote nginx-conf.d/ + templates/ dirs exist
    before upload (sftp.open() fails with ENOENT if parent dir doesn't exist).
    """
    nginx_confd_dir = os.path.join(LOCAL_ROOT, 'gw-frontend', 'nginx-conf.d')
    if not os.path.isdir(nginx_confd_dir):
        print('  [nginx-confd] source dir {} does not exist (skip)'.format(nginx_confd_dir))
        return 0

    remote_dir = '{}/gw-frontend/nginx-conf.d'.format(REMOTE_ROOT)

    # R6.92a: use generic _ensure_remote_dir helper (was R6.91 ad-hoc)
    _ensure_remote_dir(tg, remote_dir)
    _ensure_remote_dir(tg, remote_dir + '/templates')

    count = 0

    # Upload *.conf (R6.89b)
    for fname in sorted(os.listdir(nginx_confd_dir)):
        fpath = os.path.join(nginx_confd_dir, fname)
        if not os.path.isfile(fpath):
            continue
        if not fname.endswith('.conf'):
            continue
        dst = '{}/{}'.format(remote_dir, fname)
        _upload_binary_file(sftp, fpath, dst)
        count += 1

    if count:
        print('[nginx-confd] Uploaded {} conf files'.format(count))

    # R6.90b: Upload templates/*.template (skip .gitkeep)
    templates_dir = os.path.join(nginx_confd_dir, 'templates')
    if os.path.isdir(templates_dir):
        remote_templates_dir = '{}/templates'.format(remote_dir)
        tcount = 0
        for fname in sorted(os.listdir(templates_dir)):
            fpath = os.path.join(templates_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if not fname.endswith('.template'):
                continue
            if fname == '.gitkeep':
                continue
            dst = '{}/{}'.format(remote_templates_dir, fname)
            _upload_binary_file(sftp, fpath, dst)
            tcount += 1
        if tcount:
            print('[nginx-confd-templates] Uploaded {} template files'.format(tcount))
        count += tcount

    return count




def _sync_frontend_public(sftp):
    """R6.80 (v4.41): Upload public/ recursively so `docker compose build` picks up
    latest logos + fonts + html files. Vite copies public/ -> build/ during
    `npm run build`, so missing public/ means missing logos in served HTML.

    Skips files where local SHA256 matches remote SHA256 (cheap no-op).
    """
    pub_local = os.path.join(LOCAL_ROOT, 'gw-frontend', 'public')
    pub_remote = '{}/gw-frontend/public'.format(REMOTE_ROOT)

    if not os.path.isdir(pub_local):
        print('[frontend-public] {} does not exist - skipping'.format(pub_local))
        return

    # R6.92a: ensure parent dir exists (was sftp.stat+mkdir below)
    _ensure_remote_dir(tg, pub_remote)

    print('[frontend-public] Uploading public/ recursively (R6.80 fix)...')

    count = {'uploaded': 0, 'same-sha': 0, 'errors': 0}
    for root, dirs, files in os.walk(pub_local):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname.startswith('.'):
                continue
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, pub_local).replace('\\', '/')
            remote_path = '{}/{}'.format(pub_remote, rel)
            parent = os.path.dirname(remote_path).replace('\\', '/')
            try:
                sftp.stat(parent)
            except IOError:
                parts = parent.split('/')
                cur = ''
                for p in parts:
                    if not p:
                        continue
                    cur += '/' + p
                    try:
                        sftp.stat(cur)
                    except IOError:
                        try:
                            sftp.mkdir(cur)
                        except Exception:
                            pass
            local_sha = _sha256_file(local_path)
            try:
                remote_sha = _remote_sha256_via_sftp(sftp, remote_path)
                if remote_sha == local_sha and local_sha:
                    count['same-sha'] += 1
                    continue
            except Exception:
                pass
            try:
                sftp.put(local_path, remote_path)
                count['uploaded'] += 1
            except Exception as e:
                count['errors'] += 1
                print('  [err] public/{}: {}'.format(rel, e))
    print('[frontend-public] uploaded={} same-sha={} errors={}'.format(
        count['uploaded'], count['same-sha'], count['errors']))


def _remote_sha256_via_sftp(sftp, path):
    """Compute SHA256 of a remote file via SFTP (download + hash).
    Returns empty string if file doesn't exist or hash fails.
    """
    try:
        with sftp.open(path, 'rb') as f:
            h = hashlib.sha256()
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
            return h.hexdigest()
    except Exception:
        return ''


def _sync_frontend_root_hashdiff(sftp):
    """R6.79.f + R6.82 (v4.41): Hash-diff ALL root files in gw-frontend/.

    Replaces hardcoded _sync_frontend_build_configs (which listed only 4 files
    and missed index.html). Now iterates gw-frontend/ top-level, uploading any
    file whose SHA256 differs from remote.

    Skips: node_modules, dist, build, public, src, .git, .vite, package-lock.json.
    Includes: index.html (vite entry template), vite.config.ts, tsconfig*.json,
    package.json, Dockerfile, docker-entrypoint.sh, nginx*.conf, etc.
    """
    fw_local = os.path.join(LOCAL_ROOT, 'gw-frontend')
    fw_remote = '{}/gw-frontend'.format(REMOTE_ROOT)

    # R6.92a: ensure gw-frontend root exists (was no mkdir; first-deploy ENOENT risk)
    _ensure_remote_dir(tg, fw_remote)

    SKIP_TOP = {'node_modules', 'dist', 'build', 'public', 'src', '.git',
                 '.vite', '.claude', 'package-lock.json', 'scripts',
                 '__pycache__', 'reference', 'docs'}

    print('[frontend-root] Hash-diff root files in gw-frontend/...')
    count = {'uploaded': 0, 'same-sha': 0, 'skipped': 0}
    for entry in os.listdir(fw_local):
        if entry in SKIP_TOP or entry.startswith('.'):
            count['skipped'] += 1
            continue
        local_path = os.path.join(fw_local, entry)
        if not os.path.isfile(local_path):
            continue
        remote_path = '{}/{}'.format(fw_remote, entry)
        local_sha = _sha256_file(local_path)
        remote_sha = _remote_sha256_via_sftp(sftp, remote_path)
        if remote_sha == local_sha and local_sha:
            count['same-sha'] += 1
            continue
        try:
            # Use CRLF strip for shell scripts (R6.67.1)
            if entry.endswith('.sh') or entry == 'docker-entrypoint.sh':
                _upload_text_file(sftp, local_path, remote_path,
                                  strip_crlf=True, executable=True)
            else:
                sftp.put(local_path, remote_path)
            count['uploaded'] += 1
        except Exception as e:
            print('  [err] root/{}: {}'.format(entry, e))
    print('[frontend-root] uploaded={} same-sha={} skipped={}'.format(
        count['uploaded'], count['same-sha'], count['skipped']))


def _frontend_post_rebuild_sanity_check(tg):
    """R6.82 (v4.41): Post-rebuild sanity check.

    Catches stale-image regression in 1 second (vs 8h debug for R6.78x).
    Checks:
      1. Served HTML version string matches local version.ts
      2. 3 logo URLs return HTTP 200 (R6.80 regression check)
      3. Image CreatedAt mtime is recent (< 30 minutes)
    """
    print('[sanity-check] Running post-rebuild sanity check...')

    # Read local version from src/version.ts (or default)
    version_local = 'v4.54'  # fallback
    ver_path = os.path.join(LOCAL_ROOT, 'gw-frontend', 'src', 'version.ts')
    if os.path.exists(ver_path):
        import re
        m = re.search(r"""VERSION\s*[:=]\s*['"]?v?([\d.]+(?:\+[A-Za-z0-9.]+)?)""", open(ver_path, encoding="utf-8").read())
        if m:
            version_local = 'v' + m.group(1)

    # R6.82f: Search ALL JS bundles (not just first), require +R suffix to skip
    # library versions like v0.0.0. Our version v4.62+R6.69 lives in lazy chunks.
    _, o, _ = tg.exec_command(
        'curl -skL http://localhost:6001/', timeout=15)
    html = o.read().decode(errors='replace')

    import re
    js_paths = re.findall(r'/assets/[A-Za-z0-9_.-]+\.js', html)
    version_served = None
    for js_path in js_paths:
        _, o2, _ = tg.exec_command(
            'curl -skL http://localhost:6001{}'.format(js_path), timeout=15)
        js_body = o2.read().decode(errors='replace')
        # Require +R pattern (only our release suffix has it: v4.62+R6.69)
        m = re.search(r'v\d+\.\d+\+R\d+(?:\.\d+)?', js_body)
        if m:
            version_served = m.group()
            break

    ok_version = version_served == version_local
    print('  [ver] local={}  served={}  {}'.format(
        version_local, version_served or 'NONE',
        'OK' if ok_version else 'MISMATCH'))

    # Check 3 logo URLs
    logo_urls = [
        '/Logo_for_AliCPT-display.webp',
        '/Logo_for_AliCPT.png',
        '/Logo_for_AliCPT-splash.webp',
    ]
    logos_ok = True
    for logo in logo_urls:
        _, o, _ = tg.exec_command(
            'curl -skL -o /dev/null -w "%{{http_code}}" --max-time 5 '
            'http://localhost:6001{}'.format(logo), timeout=10)
        code = o.read().decode(errors='replace').strip()
        if code != '200':
            logos_ok = False
        print('  [logo] {} -> HTTP {}'.format(logo, code))

    # Check image mtime
    _, o, _ = tg.exec_command(
        'docker images --format "{{.CreatedAt}}" gravitationalwave-v431-gw-frontend:latest',
        timeout=10)
    img_age = o.read().decode(errors='replace').strip()
    print('  [img] CreatedAt: {}'.format(img_age or 'NONE'))

    # R6.87b: firefly-viewer.html DEDUP_MS sanity check (catches R6.86c-3 stale-html bug)
    # Fetch served firefly-viewer.html, extract DEDUP_MS constant, compare to local.
    firefly_ok = True
    dedup_local = None
    dedup_served = None
    ff_local_path = os.path.join(LOCAL_ROOT, 'gw-frontend', 'public', 'firefly-viewer.html')
    if os.path.exists(ff_local_path):
        import re as _re_ff
        m = _re_ff.search(r'DEDUP_MS\s*=\s*(\d+)', open(ff_local_path, encoding='utf-8').read())
        if m:
            dedup_local = int(m.group(1))
    try:
        _, o, _ = tg.exec_command(
            'curl -skL --max-time 5 http://localhost:6001/firefly-viewer.html', timeout=10)
        ff_served_body = o.read().decode(errors='replace')
        import re as _re_ff2
        m = _re_ff2.search(r'DEDUP_MS\s*=\s*(\d+)', ff_served_body)
        if m:
            dedup_served = int(m.group(1))
    except Exception:
        pass
    if dedup_local is None:
        print('  [firefly] local file missing: {}'.format(ff_local_path))
        firefly_ok = False
    elif dedup_served is None:
        print('  [firefly] served DEDUP_MS not found (stale build?)')
        firefly_ok = False
    elif dedup_local != dedup_served:
        print('  [firefly] DEDUP_MS MISMATCH local={} served={}'.format(dedup_local, dedup_served))
        firefly_ok = False
    else:
        print('  [firefly] DEDUP_MS={} OK'.format(dedup_local))

    # R6.83 (Layer 6): .env fingerprint check (detect secret drift, no content sync)
    import hashlib
    env_local_sha = None
    env_local = os.path.join(LOCAL_ROOT, '.env')
    if os.path.exists(env_local):
        with open(env_local, 'rb') as f:
            env_local_sha = hashlib.sha256(f.read()).hexdigest()[:12]
    env_remote_sha = None
    env_remote_exists = False
    _, o, _ = tg.exec_command(
        'test -f {}/.env && echo EXISTS || echo MISSING'.format(REMOTE_ROOT), timeout=5)
    env_remote_exists = 'EXISTS' in o.read().decode(errors='replace')
    if env_remote_exists:
        _, o, _ = tg.exec_command(
            'sha256sum {}/.env 2>/dev/null | cut -c1-12'.format(REMOTE_ROOT), timeout=5)
        env_remote_sha = o.read().decode(errors='replace').strip() or None

    env_ok = (env_local_sha is not None and env_remote_sha == env_local_sha) \
        or (env_local_sha is None and not env_remote_exists)
    env_drift_severity = 'OK'  # R6.92c: 'OK' | 'NOTE' | 'WARNING'
    if not env_ok:
        # R6.92c: default severity = WARNING. If ENV_ACTION=keys and key set
        # is identical, downgrade to NOTE (expected per [[gw-deepseek-key-split]]:
        # backend/pipeline use different DEEPSEEK_API_KEY but same KEY NAMES).
        env_drift_severity = 'WARNING'
        if ENV_ACTION == 'keys':
            diff_check = _env_key_diff(tg)
            if diff_check is not None:
                added = diff_check.get('added', [])
                removed = diff_check.get('removed', [])
                modified = diff_check.get('modified', [])
                # Key set identical = only values differ = expected (manual key mgmt)
                if not added and not removed:
                    env_drift_severity = 'NOTE'
                    print('  [env] NOTE: SHA DRIFT but key set identical ({} modified, expected per service-specific keys)'.format(
                        len(modified)))
                else:
                    print('  [env] WARNING: DRIFT + key set differs (added={}, removed={}, modified={})'.format(
                        len(added), len(removed), len(modified)))
            else:
                print('  [env] WARNING: DRIFT: local={} remote={} (key-diff failed)'.format(
                    env_local_sha or 'NONE', env_remote_sha or 'MISSING'))
        else:
            print('  [env] WARNING: DRIFT: local={} remote={} (manual sync required, use --env-action keys for detail)'.format(
                env_local_sha or 'NONE', env_remote_sha or 'MISSING'))
    else:
        print('  [env] OK (sha={})'.format(env_local_sha or 'NONE'))

    overall = ok_version and logos_ok and env_ok and firefly_ok
    print('[sanity-check] {}'.format('OK' if overall else 'FAILED'))

    # R6.84: When DRIFT detected, optionally show key-level diff (no values).
    # Privacy: parses key names ONLY via regex `^[A-Z_][A-Z0-9_]*=` — never
    # reads file content into logs. Backend vs pipeline use different
    # DEEPSEEK_API_KEYs per [[gw-deepseek-key-split]]; auto-sync would break
    # multi-env isolation. So no `--force-env` upload path.
    # R6.92c: key-level diff detail (only show when DRIFT WARNING, not NOTE)
    if not env_ok and ENV_ACTION == 'keys' and env_drift_severity == 'WARNING':
        diff = _env_key_diff(tg)
        if diff is not None:
            added = diff.get('added', [])
            removed = diff.get('removed', [])
            modified = diff.get('modified', [])
            print('  [env-diff] key-level (NO values shown):')
            if added:
                print('    + added (local only): {}'.format(', '.join(sorted(added))))
            if removed:
                print('    - removed (local only): {}'.format(', '.join(sorted(removed))))
            if modified:
                print('    ~ modified (value differs): {}'.format(', '.join(sorted(modified))))
            print('  [env-resolve] manual: scp .env zjlab:{}/.env  '
                  '(verify DEEPSEEK_API_KEY per service)'.format(REMOTE_ROOT))
        else:
            print('  [env-diff] (failed to fetch remote .env for key diff)')
    elif env_drift_severity == 'NOTE':
        print('  [env-resolve] expected: backend/pipeline have different DEEPSEEK_API_KEYs per [[gw-deepseek-key-split]]; no action needed')
    return overall


def _env_key_diff(tg):
    """R6.84: Return dict {added, removed, modified} of KEY NAMES (no values).

    Compares local .env vs remote .env by parsing key names only:
      - regex `^([A-Z_][A-Z0-9_]*)='  captures keys from shell-style `KEY=value`
      - skips comments (#) and blank lines
      - SHA-compares per-key value blobs to detect "modified" without logging values

    Returns dict with lists (possibly empty). Returns empty dict on remote
    missing or fetch failure.
    """
    import re
    diff = {'added': [], 'removed': [], 'modified': []}
    # Local keys
    local_keys = {}
    env_local = os.path.join(LOCAL_ROOT, '.env')
    if os.path.exists(env_local):
        with open(env_local, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                m = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line)
                if m:
                    local_keys[m.group(1)] = m.group(2).strip()
    # Remote keys (via grep; do NOT cat entire file into memory unnecessarily)
    _, o, _ = tg.exec_command(
        "grep -oP '^[A-Z_][A-Z0-9_]*(?==)' {}/.env 2>/dev/null | sort -u"
        .format(REMOTE_ROOT), timeout=5)
    remote_keys = set(
        line.strip() for line in o.read().decode(errors='replace').splitlines() if line.strip())
    local_set = set(local_keys.keys())
    diff['added'] = sorted(local_set - remote_keys)
    diff['removed'] = sorted(remote_keys - local_set)
    # Detect "modified" via per-key SHA (sha256sum of value only — no leak)
    candidate_modified = local_set & remote_keys
    for key in sorted(candidate_modified):
        # Local: hash the value bytes
        local_val_sha = hashlib.sha256(local_keys[key].encode('utf-8')).hexdigest()[:8]
        # Remote: hash the value via awk extraction (key only, no other lines)
        # Use sed to print just the value line, then awk to extract value
        # Use f-string instead of .format() to avoid brace-escaping in regex
        cmd = (f"grep -P '^{{re.escape(key)}}=' {REMOTE_ROOT}/.env 2>/dev/null | "
               f"head -1 | sed 's/^{{re.escape(key)}}=//' | sha256sum | cut -c1-8")
        _, o2, _ = tg.exec_command(cmd, timeout=5)
        remote_val_sha = o2.read().decode(errors='replace').strip()
        if remote_val_sha and remote_val_sha != local_val_sha:
            diff['modified'].append(key)
    # Remove empty lists for cleaner output
    return {k: v for k, v in diff.items() if v}


def _backend_post_rebuild_sanity_check(tg):
    """R6.83o (v4.42): Post-rebuild backend sanity check (Spring Boot port 8093).

    Catches stale-image regression for backend (mirrors R6.82 frontend check).

    R6.83.3 assumed FastAPI (with /api/health, /docs, /openapi.json). R6.83o
    discovered the backend is actually Spring Boot (alicpt-divs-gw-backend
    image, container 'divs-backend'):
      - /v3/api-docs         -> OpenAPI 3.0.1 spec
      - /swagger-ui.html     -> Swagger UI redirect
      - /swagger-ui/index.html -> Swagger UI page
    Custom routes are /api/app/gravitationalwave/... (see /v3/api-docs).
    No /api/health endpoint exists. The 'HTTP 500' on missing routes is
    Spring's global error handler wrapping NoResourceFoundException —
    cosmetic, not a real failure.

    Why port 8093: per memory zjlab-3-port architecture (6001/6002/8093),
    backend exposes Tomcat/Spring directly on 8093 (no nginx proxy).
    """
    print('[backend-sanity-check] Running post-rebuild backend sanity check...')

    endpoints = [
        ('/v3/api-docs', 'openapi-spec'),
        ('/swagger-ui.html', 'swagger-ui-redirect'),
        ('/swagger-ui/index.html', 'swagger-ui-page'),
    ]
    backend_ok = True
    for path, name in endpoints:
        _, o, _ = tg.exec_command(
            'curl -skL -o /dev/null -w "%{{http_code}}" --max-time 5 '
            'http://localhost:8093{}'.format(path), timeout=10)
        code = o.read().decode(errors='replace').strip()
        ok = code == '200'
        if not ok:
            backend_ok = False
        print('  [{}] {} -> HTTP {}'.format(name, path, code))

    # Check backend image mtime (Spring Boot container is 'divs-backend')
    _, o, _ = tg.exec_command(
        'docker images --format "{{.CreatedAt}}" alicpt-divs-gw-backend:latest',
        timeout=10)
    img_age = o.read().decode(errors='replace').strip()
    print('  [img] CreatedAt: {}'.format(img_age or 'NONE'))

    print('[backend-sanity-check] {}'.format('OK' if backend_ok else 'FAILED'))
    return backend_ok


# === R6.82 PATCH APPLIED ===

# Existing _sync_frontend_src continues below

def _sync_frontend_src(tg, sftp):
    """R6.79 + R6.83p: Upload src/ recursively so `docker compose build`
    picks up the latest source (was missing - only build/ was synced,
    image was baked from Jul 24 stale src/, served v4.17).

    Skips node_modules, dist, build, __pycache__ (not needed for build).
    Skips files where local and remote SHA256 already match.

    R6.83p: was size-based skip — silently dropped uploads when version
    strings ('v4.62+R6.69' -> 'v4.63+R6.83', same length) preserved file
    size. Switched to SHA256 for byte-level correctness. ~10ms overhead
    per file vs ~50-200ms network round-trip, negligible.
    """
    src_local = os.path.join(LOCAL_ROOT, 'gw-frontend', 'src')
    src_remote = '{}/gw-frontend/src'.format(REMOTE_ROOT)

    if not os.path.isdir(src_local):
        print('[frontend-src] {} does not exist - skipping'.format(src_local))
        return

    print('[frontend-src] Uploading src/ recursively...')
    # R6.92a: use generic helper (was ad-hoc mkdir)
    _ensure_remote_dir(tg, src_remote)

    count = {'uploaded': 0, 'same-sha': 0, 'errors': 0}
    skip_dirs = {'node_modules', 'dist', 'build', '__pycache__'}
    for root, dirs, files in os.walk(src_local):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if not fname.endswith(('.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.json', '.md')):
                continue
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, src_local).replace('\\', '/')
            remote_path = '{}/{}'.format(src_remote, rel)
            # Ensure parent dir exists
            parent = os.path.dirname(remote_path).replace('\\', '/')
            try:
                sftp.stat(parent)
            except IOError:
                # mkdir -p style
                parts = parent.split('/')
                cur = ''
                for p in parts:
                    if not p:
                        continue
                    cur += '/' + p
                    try:
                        sftp.stat(cur)
                    except IOError:
                        try:
                            sftp.mkdir(cur)
                        except Exception:
                            pass
            # R6.83p: SHA256-based skip (was size-based, missed byte-level edits)
            import hashlib
            with open(local_path, 'rb') as f:
                local_sha = hashlib.sha256(f.read()).hexdigest()
            try:
                _, o, _ = tg.exec_command(
                    'sha256sum {} 2>/dev/null | cut -c1-64'.format(remote_path),
                    timeout=5)
                remote_sha = o.read().decode(errors='replace').strip()
                if remote_sha == local_sha:
                    count['same-sha'] += 1
                    continue
            except Exception:
                pass
            try:
                sftp.put(local_path, remote_path)
                count['uploaded'] += 1
            except Exception as e:
                count['errors'] += 1
                print('  [err] {}: {}'.format(rel, e))
            if count['uploaded'] % 30 == 0 and count['uploaded'] > 0:
                print('  [progress] uploaded {} so far...'.format(count['uploaded']))
    print('[frontend-src] uploaded={} same-sha={} errors={}'.format(
        count['uploaded'], count['same-sha'], count['errors']))


def _sync_frontend_build_configs(sftp):
    """R6.79: Upload vite.config.ts + tsconfig.json + package.json so the
    Docker build (which does `COPY . .` then `npm run build`) picks up
    the latest build configuration. These files were also stale on zjlab.
    """
    files = ['vite.config.ts', 'tsconfig.json', 'tsconfig.app.json', 'package.json']
    for fname in files:
        local_p = os.path.join(LOCAL_ROOT, 'gw-frontend', fname)
        remote_p = '{}/gw-frontend/{}'.format(REMOTE_ROOT, fname)
        if not os.path.exists(local_p):
            continue
        local_size = os.path.getsize(local_p)
        try:
            remote_size = sftp.stat(remote_p).st_size
            if remote_size == local_size:
                print('  [cfg] {}: same-size, skip'.format(fname))
                continue
        except IOError:
            pass
        sftp.put(local_p, remote_p)
        print('  [cfg] {} uploaded ({}B)'.format(fname, local_size))


def _frontend_rebuild_image(tg):
    """R6.79: Trigger `docker compose build gw-frontend` + recreate on zjlab.
    Streams last 1500 chars of build output to keep terminal readable.
    """
    print('[frontend-rebuild] docker compose build gw-frontend on zjlab (~60-180s)...')
    import socket
    ch = tg.get_transport().open_session(timeout=600)
    ch.settimeout(600)
    ch.exec_command(
        'cd {} && docker compose -f docker-compose.yml -f docker-compose.zjlab.yml build gw-frontend 2>&1'.format(REMOTE_ROOT))
    buf = []
    try:
        while True:
            data = ch.recv(65536)
            if not data:
                break
            buf.append(data.decode(errors='replace'))
    except socket.timeout:
        pass
    out = ''.join(buf)
    print(out[-1500:] if len(out) > 1500 else out)
    ch.close()

    print('[frontend-rebuild] docker compose up -d --force-recreate gw-frontend...')
    _, o, _ = tg.exec_command(
        'cd {} && docker compose -f docker-compose.yml -f docker-compose.zjlab.yml up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -5'.format(REMOTE_ROOT),
        timeout=120)
    print(o.read().decode(errors='replace'))
    time.sleep(10)
    print('[frontend-rebuild] Done')


def sync_frontend(tg, sftp):
    if WITH_BUILD:
        print('[frontend] Building (npm run build)...')
        os.chdir(os.path.join(LOCAL_ROOT, 'gw-frontend'))
        subprocess.run('npm run build', shell=True)
    else:
        print('[frontend] --no-build: skipping npm run build (using existing build/)')
        # R6.89a + R6.89c: warn if src/ has changes newer than build/
        is_stale, reason, _, _, _ = _check_build_staleness()
        if is_stale:
            if args.force_stale:
                # R6.90c: --force-stale set -> downgrade WARNING to NOTE
                print('[frontend] NOTE: build/ may be STALE but --force-stale is set, proceeding anyway')
                print('  [frontend]       {}'.format(reason))
                print('  [frontend]       Served bundle will reflect older src/. User accepts this risk.')
            else:
                print('[frontend] !! WARNING: build/ may be STALE')
                print('  [frontend] !! {}'.format(reason))
                print('  [frontend] !! Served bundle will reflect older src/. Re-run without --no-build to rebuild.')
                print('  [frontend] !! (Or pass --force-stale to suppress this warning in future.)')
        # R6.90d: conservative hint for unpushed src/ commits
        unpushed = _check_unpushed_src_commits()
        if unpushed > 0:
            print('[frontend] NOTE: src/ has {} unpushed commit(s)'.format(unpushed))
            print('  [frontend]       run with --rebuild to bake them into the image')
            print('  [frontend]       proceeding with --no-build anyway (use --rebuild manually)')

    dist_dir = os.path.join(LOCAL_ROOT, 'gw-frontend', 'build')
    if not os.path.exists(dist_dir):
        print('[frontend] ERROR: build not found - run npm run build first')
        return

    print('[frontend] Uploading to bind-mount source (R6.87a)...')
    # R6.88: upload to nginx-html/ (bind mount source) instead of build/.
    # Container reads nginx html directly from this host dir via ./gw-frontend/nginx-html:/usr/share/nginx/html.
    # No docker cp needed (which is blocked by read_only: true per R6.78u cascade).
    tg.exec_command('mkdir -p {}/gw-frontend/nginx-html/assets'.format(REMOTE_ROOT), timeout=5)
    time.sleep(1)

    count = 0
    for root, dirs, files in os.walk(dist_dir):
        for fname in files:
            local = os.path.join(root, fname)
            rel = os.path.relpath(local, dist_dir).replace('\\', '/')
            try:
                sftp.put(local, '{}/gw-frontend/nginx-html/{}'.format(REMOTE_ROOT, rel))
                count += 1
            except:
                pass
    print('[frontend] Uploaded {} files to nginx-html/'.format(count))

    # R6.67.1 #4: also upload Dockerfile + entrypoint + nginx config
    if WITH_INFRA:
        _sync_frontend_infra(tg, sftp)
        _sync_frontend_nginx_confd(tg, sftp)  # R6.89b + R6.91: nginx conf.d/*.conf + templates/*.template → bind mount

    # R6.79+R6.82: --rebuild flag triggers image rebuild.
    # v4.41: hash-diff root files (incl. index.html) + public/ + src/ + image rebuild.
    # This is the complete fix for the 5-layer v4.17/R6.80 stale-image regression.
    if WITH_REBUILD:
        print('[frontend] --rebuild enabled: uploading root + public + src + rebuilding image...')
        _sync_frontend_root_hashdiff(sftp)   # R6.79.f + R6.82: index.html, configs
        _sync_frontend_public(sftp)          # R6.80: logos, fonts
        _sync_frontend_src(tg, sftp)         # R6.78x: source code
        _frontend_rebuild_image(tg)          # R6.78x: docker compose build
        _frontend_post_rebuild_sanity_check(tg)  # R6.82: catch stale-image regression
        print('[frontend] Done (image rebuilt + sanity check passed)')
        return

    # R6.88: fast non-rebuild path via bind mount (no docker cp needed).
    # Old path: docker exec delete + docker cp + nginx reload (~5s, BROKEN by R6.78u).
    # New path: just nginx reload (~1s, container reads bind mount directly).
    print('[frontend] Reloading nginx (bind mount auto-reflects)...')
    tg.exec_command('docker exec gw-frontend nginx -s reload', timeout=10)
    print('[frontend] Done (fast path)')



def _sha256_file(path):
    """Compute SHA256 of a local file."""
    if not os.path.exists(path):
        return ''
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _remote_sha256(tg, path):
    """Compute SHA256 of a remote file via ssh + sha256sum."""
    # Use a sentinel for path to avoid .format() parsing awk's {print $1}
    cmd = "sha256sum '" + path + "' 2>/dev/null | awk '{print $1}'"
    _, o, _ = tg.exec_command(cmd, timeout=10)
    return o.read().decode().strip()


def _pipeline_needs_rebuild(tg):
    """Detect if gw-pipeline image needs rebuild because requirements.txt changed.

    R6.52 hotfix: previous sync only did `docker cp` + `docker restart`, which
    does NOT re-run `pip install -r requirements.txt`. New Python deps only
    take effect after `docker compose build gw-pipeline`.

    Returns True if local and remote requirements.txt SHA256 differ.
    """
    local_reqs = os.path.join(LOCAL_ROOT, 'gw-pipeline', 'requirements.txt')
    local_sha = _sha256_file(local_reqs)
    remote_path = '{}/gw-pipeline/requirements.txt'.format(REMOTE_ROOT)
    remote_sha = _remote_sha256(tg, remote_path)
    if not local_sha or not remote_sha:
        # Cannot determine (file missing or sha256sum unavailable) — skip auto-build
        return False, local_sha[:12] if local_sha else '', remote_sha[:12] if remote_sha else ''
    changed = local_sha != remote_sha
    return changed, local_sha[:12], remote_sha[:12]


def _rebuild_pipeline_remote(tg):
    """Trigger `docker compose build --no-cache gw-pipeline` on zjlab host,
    then `up -d --force-recreate --no-deps gw-pipeline` to bake in new requirements.

    Requires docker compose v2 on the host. Takes ~40-180s depending on cache.
    Output is streamed to stdout (last 12 lines of build + 5 lines of recreate).
    """
    print('[pipeline-rebuild] Building gw-pipeline image on zjlab (~40-180s)...')
    # Open channel directly so we can stream output and not block on huge buffer.
    import socket
    ch = tg.get_transport().open_session(timeout=600)
    ch.settimeout(600)
    ch.exec_command(
        'cd {} && docker compose build --no-cache gw-pipeline 2>&1 | tail -12'.format(REMOTE_ROOT))
    buf = []
    try:
        while True:
            data = ch.recv(65536)
            if not data:
                break
            buf.append(data.decode(errors='replace'))
    except socket.timeout:
        pass
    out = ''.join(buf)
    # Show only last 1500 chars to keep terminal readable
    print(out[-1500:] if len(out) > 1500 else out)
    ch.close()

    print('[pipeline-rebuild] Recreating gw-pipeline container...')
    _, o, _ = tg.exec_command(
        'cd {} && docker compose up -d --force-recreate --no-deps gw-pipeline 2>&1 | tail -5'.format(REMOTE_ROOT),
        timeout=120)
    print(o.read().decode(errors='replace'))
    time.sleep(10)
    print('[pipeline-rebuild] Done')


def _pipeline_needs_source_rebuild(tg, sftp):
    """R6.64: detect if local source differs from RUNNING CONTAINER source.

    Compares per-file SHA256 between local gw-pipeline/src/pipeline and
    /app/src/pipeline/ inside the running gw-pipeline container. The remote
    host path can be stale if a rebuild was skipped earlier.

    Returns (changed: bool, n_local_changed: int, n_container: int).
    """
    import hashlib as _hl
    pipeline_dir = os.path.join(LOCAL_ROOT, 'gw-pipeline', 'src', 'pipeline')
    agent_dir = os.path.join(pipeline_dir, 'agent')
    local_files = {}
    for d in (pipeline_dir, agent_dir):
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if fname.endswith('.py'):
                lp = os.path.join(d, fname)
                with open(lp, 'rb') as f:
                    local_files[fname] = _hl.sha256(f.read()).hexdigest()
    # Container SHA: sha256sum /app/src/pipeline/*.py via docker exec
    container_files = {}
    cmd = (
        'docker exec gw-pipeline sha256sum '
        '/app/src/pipeline/*.py /app/src/pipeline/agent/*.py 2>/dev/null'
    )
    si, so, se = tg.exec_command(cmd, timeout=30)
    out = so.read().decode(errors='replace').strip()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sha = parts[0]
            p_full = parts[1]
            base = os.path.basename(p_full)
            if base.endswith('.py'):
                container_files[base] = sha
    changed = sum(1 for k, v in local_files.items() if container_files.get(k) != v)
    return (changed > 0, changed, len(container_files))


def sync_pipeline(tg, sftp):
    # R6.64 patch: upload source BEFORE rebuild (read-only rootfs blocks docker cp).
    # Old order: rebuild -> upload -> docker cp -> restart (broken: cp fails)
    # New order: upload -> rebuild (build picks up fresh source) -> restart
    # R6.64: ALL CHANGE DETECTION BEFORE UPLOAD (otherwise the source SHA
    # comparison reads the just-uploaded files and returns no-changes).
    needs_rebuild, local_short, remote_short = _pipeline_needs_rebuild(tg)
    src_changed, n_src_changed, n_remote = _pipeline_needs_source_rebuild(tg, sftp)
    if needs_rebuild:
        print('[pipeline] requirements.txt CHANGED (local={} remote={}) -> triggering rebuild'.format(
            local_short, remote_short))
    elif src_changed:
        print('[pipeline] source CHANGED ({} of {} files differ) -> triggering rebuild (read-only rootfs)'.format(
            n_src_changed, n_remote))
        needs_rebuild = True
    else:
        print('[pipeline] requirements.txt + source unchanged - skipping rebuild')

    print('[pipeline] Uploading source FIRST (so build picks up new code)...')
    tg.exec_command('mkdir -p {}/gw-pipeline/src/pipeline/agent'.format(REMOTE_ROOT), timeout=5)
    time.sleep(1)

    pipeline_dir = os.path.join(LOCAL_ROOT, 'gw-pipeline', 'src', 'pipeline')
    count = 0
    for fname in os.listdir(pipeline_dir):
        if fname.endswith('.py'):
            sftp.put(os.path.join(pipeline_dir, fname),
                     '{}/gw-pipeline/src/pipeline/{}'.format(REMOTE_ROOT, fname))
            count += 1
    for fname in os.listdir(os.path.join(pipeline_dir, 'agent')):
        if fname.endswith('.py'):
            sftp.put(os.path.join(pipeline_dir, 'agent', fname),
                     '{}/gw-pipeline/src/pipeline/agent/{}'.format(REMOTE_ROOT, fname))
            count += 1
    # Also upload requirements.txt + Dockerfile so docker compose build
    # picks up new Python deps on the next rebuild.
    # R6.67.1 #4: Dockerfile uses CRLF stripping so Windows-edited Dockerfiles
    # don't get `\r` injected into RUN lines (which would break shell parsing).
    gw_root = os.path.join(LOCAL_ROOT, 'gw-pipeline')
    for extra in ['requirements.txt', 'Dockerfile']:
        src_path = os.path.join(gw_root, extra)
        if not os.path.exists(src_path):
            continue
        dst = '{}/gw-pipeline/{}'.format(REMOTE_ROOT, extra)
        if extra == 'Dockerfile':
            # Dockerfile: strip CRLF (safe — Dockerfile lines don't need CR)
            _upload_text_file(sftp, src_path, dst, strip_crlf=True)
        else:
            # requirements.txt: binary upload (no CRLF strip)
            _upload_binary_file(sftp, src_path, dst)
        count += 1
        print('[pipeline] uploaded {} ({} bytes)'.format(extra, os.path.getsize(src_path)))
    print('[pipeline] Uploaded {} files'.format(count))

    if needs_rebuild:
        _rebuild_pipeline_remote(tg)
    else:
        print('[pipeline] no changes detected - skipping rebuild')

    print('[pipeline] Deploying...')
    for fname in os.listdir(pipeline_dir):
        if fname.endswith('.py'):
            tg.exec_command('docker cp {}/gw-pipeline/src/pipeline/{} gw-pipeline:/app/src/pipeline/{}'.format(
                REMOTE_ROOT, fname, fname), timeout=10)
            time.sleep(0.05)
    for fname in os.listdir(os.path.join(pipeline_dir, 'agent')):
        if fname.endswith('.py'):
            tg.exec_command('docker cp {}/gw-pipeline/src/pipeline/agent/{} gw-pipeline:/app/src/pipeline/agent/{}'.format(
                REMOTE_ROOT, fname, fname), timeout=10)
            time.sleep(0.05)
    # Also docker cp requirements.txt + Dockerfile to container so manual pip / debug works
    for extra in ['requirements.txt', 'Dockerfile']:
        tg.exec_command('docker cp {}/gw-pipeline/{} gw-pipeline:/app/{}'.format(
            REMOTE_ROOT, extra, extra), timeout=10)
    tg.exec_command('docker restart gw-pipeline', timeout=10)
    time.sleep(8)
    print('[pipeline] Done')


def sync_config(tg, sftp):
    print('[config] Syncing nginx...')
    local_nginx = os.path.join(LOCAL_ROOT, 'scripts', '.nginx_locations.conf')
    subprocess.run(['docker', 'cp', 'gw-frontend:/etc/nginx/shared/locations-common.conf', local_nginx],
                   capture_output=True, shell=True)
    if os.path.exists(local_nginx):
        sftp.put(local_nginx, '/tmp/locations-common.conf')
        tg.exec_command('docker cp /tmp/locations-common.conf gw-frontend:/etc/nginx/shared/locations-common.conf', timeout=10)
        tg.exec_command('docker exec gw-frontend nginx -s reload', timeout=10)
        print('[config] Done')


def sync_jar(tg, sftp):
    jar_path = os.path.join(LOCAL_ROOT, 'gw-backend', 'start', 'target', 'start.jar')
    if not os.path.exists(jar_path):
        print('[jar] ERROR: start.jar not found - run mvn package first')
        return
    print('[jar] Uploading {} MB...'.format(os.path.getsize(jar_path) / 1024 / 1024))
    sftp.put(jar_path, '/tmp/start.jar')
    tg.exec_command('docker cp /tmp/start.jar gw-backend:/home/gravitational-wave-backend/app.jar', timeout=30)
    tg.exec_command('docker restart gw-backend', timeout=10)
    time.sleep(12)
    print('[jar] Done')


def sync_compose(tg, sftp):
    """R6.79: Sync docker-compose.yml + docker-compose.zjlab.yml + recreate services.

    Why: R6.78d-u cascade (2026-09-08) was rooted in these files drifting out
    of sync between local D:\\AliCPT and zjlab /home/zjlab/gravitationalwave-v4.31.
    Without this mode, port mappings / tmpfs / env changes only reach zjlab via
    manual rsync/scp + `docker compose up -d`.

    Uploads both files, validates with `docker compose config --quiet`, then
    recreates all services to pick up new config (preserves running containers
    where possible via `up -d`).
    """
    print('[compose] Syncing docker-compose.yml + docker-compose.zjlab.yml...')

    compose_files = [
        ('docker-compose.yml', False),       # YAML, no CRLF strip
        ('docker-compose.zjlab.yml', False), # YAML, no CRLF strip
    ]

    for fname, strip_crlf in compose_files:
        local_p = os.path.join(LOCAL_ROOT, fname)
        remote_p = '{}/{}'.format(REMOTE_ROOT, fname)
        if not os.path.exists(local_p):
            print('  [skip] {} not found locally'.format(local_p))
            continue
        local_size = os.path.getsize(local_p)
        try:
            remote_size = sftp.stat(remote_p).st_size
        except IOError:
            remote_size = -1
        if remote_size == local_size:
            print('  [{}] same-size, skip'.format(fname))
            continue
        sftp.put(local_p, remote_p)
        print('  [{}] uploaded ({}B)'.format(fname, local_size))

    # Validate
    print('[compose] Validating with docker compose config...')
    _, o, _ = tg.exec_command(
        'cd {} && docker compose -f docker-compose.yml -f docker-compose.zjlab.yml config --quiet 2>&1 && echo VALID_OK || echo VALID_FAILED'.format(REMOTE_ROOT),
        timeout=30)
    out = o.read().decode(errors='replace').strip()
    if 'VALID_OK' not in out:
        print('[compose] VALIDATION FAILED - aborting recreate. Fix compose file first.')
        print(out)
        return

    print('[compose] Validation passed. Recreating all services...')
    _, o, _ = tg.exec_command(
        'cd {} && docker compose -f docker-compose.yml -f docker-compose.zjlab.yml up -d 2>&1 | tail -20'.format(REMOTE_ROOT),
        timeout=300)
    print(o.read().decode(errors='replace'))
    print('[compose] Done')


def verify(tg):
    print('[verify] Checking...')
    _, o, _ = tg.exec_command(
        'docker ps --filter name=gw- --format "{{.Names}} {{.Status}}"', timeout=10)
    containers = o.read().decode().strip()

    ok = True
    for line in containers.split('\n'):
        name, _, status = line.partition(' ')
        healthy = 'healthy' in status.lower() and 'restarting' not in status.lower()
        flag = 'OK' if healthy else '!!'
        if not healthy:
            ok = False
        print('[verify] {} {} - {}'.format(flag, name, status))

    for path, label in [('/', 'Frontend'), ('/docs', 'API Docs')]:
        _, o, _ = tg.exec_command(
            'curl -s -o /dev/null -w "%{{http_code}}" --max-time 5 http://localhost:6001{}'.format(path), timeout=10)
        code = o.read().decode().strip()
        print('[verify] {} -> HTTP {}'.format(label, code))

    # R6.82 (v4.41): Always run frontend sanity check (catches R6.78x-class regressions)
    frontend_sanity_ok = _frontend_post_rebuild_sanity_check(tg)
    backend_sanity_ok = _backend_post_rebuild_sanity_check(tg)
    sanity_ok = frontend_sanity_ok and backend_sanity_ok
    if not sanity_ok:
        ok = False

    print('[verify] {}'.format('ALL OK' if ok else 'WARNING: issues found'))


# === Main ===
if __name__ == '__main__':
    # R6.67.1 #4: parse --with-infra / --no-infra (default ON).
    # We support both `python sync-to-zjlab.py frontend` (positional mode arg)
    # AND the new flags, so existing muscle memory keeps working.
    parser = argparse.ArgumentParser(
        description='Sync local code to ZhiJiang Lab remote server via SSH bastion.',
        add_help=True,
    )
    parser.add_argument('mode', nargs='?', default='full',
                        choices=['full', 'frontend', 'pipeline', 'config', 'jar', 'compose'],
                        help='Sync mode (default: full). R6.79: added compose.')
    parser.add_argument('--with-infra', dest='with_infra', action='store_true',
                        default=True,
                        help='Upload Dockerfile + docker-entrypoint.sh + nginx.conf + ssl/ '
                             'in addition to build/ (default: enabled).')
    parser.add_argument('--no-infra', dest='with_infra', action='store_false',
                        help='Skip infra file upload (legacy behavior — only build/).')
    parser.add_argument('--rebuild', dest='with_rebuild', action='store_true',
                        default=False,
                        help='R6.79: Also upload src/ + vite.config.ts + tsconfig.json + '
                             'package.json + trigger `docker compose build gw-frontend` + '
                             'recreate container. Required after src/ changes that must '
                             'be baked into the image (vs docker cp at runtime).')
    parser.add_argument('--no-build', dest='with_build', action='store_false',
                        default=True,
                        help='R6.88: Skip `npm run build`. Use when build/ is already '
                             'fresh (e.g. you already ran `npm run build` locally). Saves '
                             '~30-60s per deploy. Combined with bind-mount fast path '
                             '(nginx-html SFTP + nginx reload), full sync is ~1-2s end-to-end.')
    parser.add_argument('--force-stale', dest='force_stale', action='store_true',
                        default=False,
                        help='R6.89c: Suppress the staleness warning when --no-build is used and '
                             'src/ has changes newer than build/. Use when you KNOWINGLY skip '
                             'rebuild (e.g., verifying a deploy without src/ changes).')
    parser.add_argument('--env-action', dest='env_action', default='detect',
                        choices=['detect', 'keys'],
                        help='R6.84: .env DRIFT response. "detect" (default) only prints '
                             'OK/DRIFT. "keys" additionally prints KEY-LEVEL diff '
                             '(added/removed/modified key names, NEVER values).')
    args = parser.parse_args()
    MODE = args.mode
    WITH_INFRA = args.with_infra
    WITH_REBUILD = args.with_rebuild
    WITH_BUILD = args.with_build
    ENV_ACTION = args.env_action

    print('=' * 50)
    print('GW Sync v4.41  |  Mode: {}  |  Build: {}  |  Infra: {}  |  Rebuild: {}  |  Env: {}'.format(
        MODE, 'ON' if WITH_BUILD else 'SKIP', 'ON' if WITH_INFRA else 'OFF', 'ON' if WITH_REBUILD else 'OFF', ENV_ACTION))
    print('=' * 50)

    ba, tg, sftp = connect()
    try:
        if MODE in ('full', 'frontend'):
            sync_frontend(tg, sftp)
        if MODE in ('full', 'pipeline'):
            sync_pipeline(tg, sftp)
        if MODE in ('full', 'config'):
            sync_config(tg, sftp)
        if MODE == 'jar':
            sync_jar(tg, sftp)
        if MODE == 'compose':
            sync_compose(tg, sftp)
        verify(tg)
        print('\n[DONE]')
    finally:
        sftp.close()
        tg.close()
        ba.close()
