"""R6.94: Force docker build --no-cache with logging."""
import paramiko, re, socket, time
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
print('[connect] OK')

# Verify middleware is in place on host BEFORE build
print()
print('[pre-check] host middleware files:')
stdin, stdout, stderr = tg.exec_command('ls -la ' + REMOTE_ROOT + '/gw-pipeline/src/pipeline/middleware/')
print(stdout.read().decode(errors='replace').rstrip())

# Run docker build directly with stream
print()
print('[build] docker build --no-cache (streaming)...')
cmd = ('cd ' + REMOTE_ROOT + '/gw-pipeline && '
       'docker build --no-cache -t gravitationalwave-v431-gw-pipeline . 2>&1')
print('cmd:', cmd)
ch2 = tg.get_transport().open_session(timeout=900)
ch2.settimeout(900)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data:
            break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s, stopping stream capture')
            break
except socket.timeout:
    pass
out = ''.join(buf)
print('=== BUILD OUTPUT (last 4000 chars) ===')
print(out[-4000:] if len(out) > 4000 else out)
ch2.close()

# Verify image SHA changed
print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-pipeline --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

# Check if middleware is in new image
print()
print('[verify] middleware in new image:')
stdin, stdout, stderr = tg.exec_command(
    'docker run --rm gravitationalwave-v431-gw-pipeline sh -c "ls /app/src/pipeline/middleware/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# Recreate pipeline container with new image
print()
print('[recreate] docker compose up -d --force-recreate gw-pipeline...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-pipeline 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

# Wait + verify
print()
print('[wait] 20s for startup...')
time.sleep(20)

print('[verify] pipeline status + logs:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps -a --filter name=gw-pipeline --format "table {{.Names}}\t{{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())
print()
stdin, stdout, stderr = tg.exec_command('docker logs gw-pipeline 2>&1 | tail -20')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')

# Verify middleware is in place on host BEFORE build
print()
print('[pre-check] host middleware files:')
stdin, stdout, stderr = tg.exec_command('ls -la ' + REMOTE_ROOT + '/gw-pipeline/src/pipeline/middleware/')
print(stdout.read().decode(errors='replace').rstrip())

# Run docker build directly with stream
print()
print('[build] docker build --no-cache (streaming)...')
cmd = ('cd ' + REMOTE_ROOT + '/gw-pipeline && '
       'docker build --no-cache -t gravitationalwave-v431-gw-pipeline . 2>&1')
print('cmd:', cmd)
ch2 = tg.get_transport().open_session(timeout=900)
ch2.settimeout(900)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data:
            break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s, stopping stream capture')
            break
except socket.timeout:
    pass
out = ''.join(buf)
print('=== BUILD OUTPUT (last 4000 chars) ===')
print(out[-4000:] if len(out) > 4000 else out)
ch2.close()

# Verify image SHA changed
print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-pipeline --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

# Check if middleware is in new image
print()
print('[verify] middleware in new image:')
stdin, stdout, stderr = tg.exec_command(
    'docker run --rm gravitationalwave-v431-gw-pipeline sh -c "ls /app/src/pipeline/middleware/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# Recreate pipeline container with new image
print()
print('[recreate] docker compose up -d --force-recreate gw-pipeline...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-pipeline 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

# Wait + verify
print()
print('[wait] 20s for startup...')
time.sleep(20)

print('[verify] pipeline status + logs:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps -a --filter name=gw-pipeline --format "table {{.Names}}\t{{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())
print()
stdin, stdout, stderr = tg.exec_command('docker logs gw-pipeline 2>&1 | tail -20')
print(stdout.read().decode(errors='replace').rstrip())
