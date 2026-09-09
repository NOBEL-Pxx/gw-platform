"""R6.93 fix: Upload middleware + anomaly dirs directly to host, force rebuild without cache."""
import paramiko, re, os, time
from pathlib import Path

sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')
m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))
REMOTE_ROOT = re.search(r"^REMOTE_ROOT\s*=\s*'([^']+)'", sync_src, re.M).group(1)

ba = paramiko.SSHClient()
ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3], timeout=20, allow_agent=False, look_for_keys=False)
ba.get_transport().set_keepalive(30)
ch = ba.get_transport().open_channel('direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient()
tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)
sftp = tg.open_sftp()
print('[connect] OK')

# Step 1: Upload middleware + anomaly dirs directly
LOCAL_PIPELINE = Path(r'D:\AliCPT\gw-pipeline\src\pipeline')
REMOTE_PIPELINE_SRC = REMOTE_ROOT + '/gw-pipeline/src/pipeline'

for subdir in ['middleware', 'anomaly']:
    local_dir = LOCAL_PIPELINE / subdir
    remote_dir = REMOTE_PIPELINE_SRC + '/' + subdir
    print('[upload-dir] {} -> {}'.format(subdir, remote_dir))
    
    # Ensure remote dir exists
    try:
        sftp.mkdir(remote_dir)
        print('  mkdir {}'.format(remote_dir))
    except IOError as e:
        print('  mkdir skipped ({}): {}'.format(remote_dir, e))
    
    # Upload all .py files in subdir
    for f in sorted(local_dir.glob('*.py')):
        remote_path = remote_dir + '/' + f.name
        sftp.put(str(f), remote_path)
        print('  upload {} ({}B)'.format(f.name, f.stat().st_size))

# Verify upload
print()
print('[verify] host pipeline middleware contents:')
stdin, stdout, stderr = tg.exec_command('ls -la ' + REMOTE_PIPELINE_SRC + '/middleware/ 2>&1')
print(stdout.read().decode(errors='replace').rstrip())

# Step 2: Force rebuild without cache
print()
print('[rebuild] docker compose build --no-cache gw-pipeline on zjlab (~2-5min)...')
cmd = ('cd {} && '
       'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
       'build --no-cache gw-pipeline 2>&1 | tail -20').format(REMOTE_ROOT)
print('cmd: ' + cmd)
import socket
ch2 = tg.get_transport().open_session(timeout=600)
ch2.settimeout(600)
ch2.exec_command(cmd)
buf = []
try:
    while True:
        data = ch2.recv(65536)
        if not data:
            break
        buf.append(data.decode(errors='replace'))
except socket.timeout:
    pass
out = ''.join(buf)
print(out[-3000:] if len(out) > 3000 else out)
ch2.close()

# Step 3: Recreate pipeline container
print()
print('[recreate] docker compose up -d --force-recreate gw-pipeline...')
cmd2 = ('cd {} && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-pipeline 2>&1 | tail -10').format(REMOTE_ROOT)
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())
print('EXIT:', code)

# Step 4: Wait + verify
print()
print('[wait] sleeping 15s for startup...')
time.sleep(15)

cmds = [
    'docker ps -a --filter name=gw-pipeline --format "table {{.Names}}\t{{.Status}}"',
    'docker logs gw-pipeline 2>&1 | tail -15',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=30)
    print(stdout.read().decode(errors='replace').rstrip())

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

sftp = tg.open_sftp()
print('[connect] OK')

# Step 1: Upload middleware + anomaly dirs directly
LOCAL_PIPELINE = Path(r'D:\AliCPT\gw-pipeline\src\pipeline')
REMOTE_PIPELINE_SRC = REMOTE_ROOT + '/gw-pipeline/src/pipeline'

for subdir in ['middleware', 'anomaly']:
    local_dir = LOCAL_PIPELINE / subdir
    remote_dir = REMOTE_PIPELINE_SRC + '/' + subdir
    print('[upload-dir] {} -> {}'.format(subdir, remote_dir))
    
    # Ensure remote dir exists
    try:
        sftp.mkdir(remote_dir)
        print('  mkdir {}'.format(remote_dir))
    except IOError as e:
        print('  mkdir skipped ({}): {}'.format(remote_dir, e))
    
    # Upload all .py files in subdir
    for f in sorted(local_dir.glob('*.py')):
        remote_path = remote_dir + '/' + f.name
        sftp.put(str(f), remote_path)
        print('  upload {} ({}B)'.format(f.name, f.stat().st_size))

# Verify upload
print()
print('[verify] host pipeline middleware contents:')
stdin, stdout, stderr = tg.exec_command('ls -la ' + REMOTE_PIPELINE_SRC + '/middleware/ 2>&1')
print(stdout.read().decode(errors='replace').rstrip())

# Step 2: Force rebuild without cache
print()
print('[rebuild] docker compose build --no-cache gw-pipeline on zjlab (~2-5min)...')
cmd = ('cd {} && '
       'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
       'build --no-cache gw-pipeline 2>&1 | tail -20').format(REMOTE_ROOT)
print('cmd: ' + cmd)
import socket
ch2 = tg.get_transport().open_session(timeout=600)
ch2.settimeout(600)
ch2.exec_command(cmd)
buf = []
try:
    while True:
        data = ch2.recv(65536)
        if not data:
            break
        buf.append(data.decode(errors='replace'))
except socket.timeout:
    pass
out = ''.join(buf)
print(out[-3000:] if len(out) > 3000 else out)
ch2.close()

# Step 3: Recreate pipeline container
print()
print('[recreate] docker compose up -d --force-recreate gw-pipeline...')
cmd2 = ('cd {} && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-pipeline 2>&1 | tail -10').format(REMOTE_ROOT)
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())
print('EXIT:', code)

# Step 4: Wait + verify
print()
print('[wait] sleeping 15s for startup...')
time.sleep(15)

cmds = [
    'docker ps -a --filter name=gw-pipeline --format "table {{.Names}}\t{{.Status}}"',
    'docker logs gw-pipeline 2>&1 | tail -15',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=30)
    print(stdout.read().decode(errors='replace').rstrip())
    print()
