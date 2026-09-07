#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravitationalWave Platform — Sync Script (v4.39)
================================================
Sync local code to ZhiJiang Lab remote server via SSH bastion.

R6.52: detects requirements.txt diff -> auto-triggers `docker compose build`
       before `docker cp`, so new Python deps are baked into the image.

R6.67.1 follow-up (#4): also upload Dockerfile + docker-entrypoint.sh + nginx.conf
       (was previously skipped — required manual upload, broke deploy when
       Docker layer baked old entrypoint). Strip Windows CRLF on shell scripts
       so busybox sh on zjlab doesn't choke on `#!/bin/sh\r` shebang.

Usage:
  python sync-to-zjlab.py          # Full sync
  python sync-to-zjlab.py frontend # Frontend only
  python sync-to-zjlab.py pipeline # Python modules only
  python sync-to-zjlab.py config   # Nginx config only
  python sync-to-zjlab.py jar      # Backend JAR only (after mvn package)
  python sync-to-zjlab.py frontend --no-infra  # Legacy: build/ only

Bastion: 192.168.10.10:60022 -> 10.107.207.103:22
"""
import paramiko, time, os, sys, io, subprocess, hashlib, argparse

# === Configuration ===
BASTION = ('192.168.10.10', 60022, 'ZJWB260819', 'Temp@ecf4f6')
SERVER  = ('10.107.207.103', 22, 'zjlab', 'fast@zjlab')
REMOTE_ROOT = '/home/zjlab/gravitationalwave-v4.31'
LOCAL_ROOT  = r'D:\AliCPT'

MODE = sys.argv[1] if len(sys.argv) > 1 else 'full'


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

    # Make sure target dirs exist (build/ already done; we add root + ssl/)
    tg.exec_command('mkdir -p {}/ssl'.format(remote_dir), timeout=5)
    time.sleep(0.5)

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


def sync_frontend(tg, sftp):
    print('[frontend] Building...')
    os.chdir(os.path.join(LOCAL_ROOT, 'gw-frontend'))
    subprocess.run('npm run build', shell=True)

    dist_dir = os.path.join(LOCAL_ROOT, 'gw-frontend', 'build')
    if not os.path.exists(dist_dir):
        print('[frontend] ERROR: build not found - run npm run build first')
        return

    print('[frontend] Uploading...')
    tg.exec_command('mkdir -p {}/gw-frontend/build/assets'.format(REMOTE_ROOT), timeout=5)
    time.sleep(1)

    count = 0
    for root, dirs, files in os.walk(dist_dir):
        for fname in files:
            local = os.path.join(root, fname)
            rel = os.path.relpath(local, dist_dir).replace('\\', '/')
            try:
                sftp.put(local, '{}/gw-frontend/build/{}'.format(REMOTE_ROOT, rel))
                count += 1
            except:
                pass
    print('[frontend] Uploaded {} files'.format(count))

    # R6.67.1 #4: also upload Dockerfile + entrypoint + nginx config
    if WITH_INFRA:
        _sync_frontend_infra(tg, sftp)

    print('[frontend] Deploying...')
    tg.exec_command('docker exec gw-frontend find /usr/share/nginx/html/assets -type f -delete', timeout=10)
    time.sleep(1)
    tg.exec_command('docker cp {}/gw-frontend/build/. gw-frontend:/usr/share/nginx/html/'.format(REMOTE_ROOT), timeout=30)
    tg.exec_command('docker exec gw-frontend nginx -s reload', timeout=10)
    print('[frontend] Done')



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
                        choices=['full', 'frontend', 'pipeline', 'config', 'jar'],
                        help='Sync mode (default: full)')
    parser.add_argument('--with-infra', dest='with_infra', action='store_true',
                        default=True,
                        help='Upload Dockerfile + docker-entrypoint.sh + nginx.conf + ssl/ '
                             'in addition to build/ (default: enabled).')
    parser.add_argument('--no-infra', dest='with_infra', action='store_false',
                        help='Skip infra file upload (legacy behavior — only build/).')
    args = parser.parse_args()
    MODE = args.mode
    WITH_INFRA = args.with_infra

    print('=' * 50)
    print('GW Sync v4.39  |  Mode: {}  |  Infra: {}'.format(MODE, 'ON' if WITH_INFRA else 'OFF'))
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
        verify(tg)
        print('\n[DONE]')
    finally:
        sftp.close()
        tg.close()
        ba.close()
