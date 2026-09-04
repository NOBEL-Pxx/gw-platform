#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravitationalWave Platform — Sync Script (v4.39)
================================================
Sync local code to ZhiJiang Lab remote server via SSH bastion.

R6.52: detects requirements.txt diff -> auto-triggers `docker compose build`
       before `docker cp`, so new Python deps are baked into the image.

Usage:
  python sync-to-zjlab.py          # Full sync
  python sync-to-zjlab.py frontend # Frontend only
  python sync-to-zjlab.py pipeline # Python modules only
  python sync-to-zjlab.py config   # Nginx config only
  python sync-to-zjlab.py jar      # Backend JAR only (after mvn package)

Bastion: 192.168.10.10:60022 -> 10.107.207.103:22
"""
import paramiko, time, os, sys, io, subprocess, hashlib

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


def sync_pipeline(tg, sftp):
    # R6.52 hotfix: auto-rebuild gw-pipeline image when requirements.txt changes
    needs_rebuild, local_short, remote_short = _pipeline_needs_rebuild(tg)
    if needs_rebuild:
        print('[pipeline] requirements.txt CHANGED (local={} remote={}) -> triggering rebuild'.format(
            local_short, remote_short))
        _rebuild_pipeline_remote(tg)
    else:
        print('[pipeline] requirements.txt unchanged (sha={}) - skipping rebuild'.format(local_short or remote_short))

    print('[pipeline] Uploading...')
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
    # R6.52 hotfix: also upload requirements.txt + Dockerfile + docs/changelog
    # so docker compose build picks up new Python deps on the next rebuild.
    gw_root = os.path.join(LOCAL_ROOT, 'gw-pipeline')
    for extra in ['requirements.txt', 'Dockerfile']:
        src_path = os.path.join(gw_root, extra)
        if os.path.exists(src_path):
            sftp.put(src_path, '{}/gw-pipeline/{}'.format(REMOTE_ROOT, extra))
            count += 1
            print('[pipeline] uploaded {} ({} bytes)'.format(extra, os.path.getsize(src_path)))
    print('[pipeline] Uploaded {} files'.format(count))

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
    print('=' * 50)
    print('GW Sync v4.39  |  Mode: {}'.format(MODE))
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
