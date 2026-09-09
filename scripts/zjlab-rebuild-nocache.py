"""R6.94: Force no-cache rebuild of gw-frontend to bypass COPY cache."""
import re, time
from pathlib import Path
import paramiko

sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')
m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_r = re.search(r"^REMOTE_ROOT\s*=\s*'([^']+)'", sync_src, re.M)
BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))
REMOTE_ROOT = m_r.group(1)

ba = paramiko.SSHClient(); ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3], timeout=20, allow_agent=False, look_for_keys=False)
ch = ba.get_transport().open_channel('direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient(); tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)
print('[connect] OK')

import socket
print('[rebuild no-cache] docker build --no-cache -t gw-frontend . ...')
cmd = ('cd ' + REMOTE_ROOT + '/gw-frontend && '
       'docker build --no-cache -t gravitationalwave-v431-gw-frontend . 2>&1')
ch2 = tg.get_transport().open_session(timeout=900)
ch2.settimeout(900)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data: break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s'); break
except socket.timeout: pass
out = ''.join(buf)
out_safe = out.encode('ascii', 'replace').decode('ascii')
print('=== BUILD (last 2000 chars) ===')
print(out_safe[-2000:] if len(out_safe) > 2000 else out_safe)
ch2.close()

print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-frontend --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

print('[recreate]...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

print('[wait] 30s...')
time.sleep(30)

print('[verify] entrypoint dual-iteration in NEW container:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -10"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] smoketest conf:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] smoketest endpoint:')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')

import socket
print('[rebuild no-cache] docker build --no-cache -t gw-frontend . ...')
cmd = ('cd ' + REMOTE_ROOT + '/gw-frontend && '
       'docker build --no-cache -t gravitationalwave-v431-gw-frontend . 2>&1')
ch2 = tg.get_transport().open_session(timeout=900)
ch2.settimeout(900)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data: break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s'); break
except socket.timeout: pass
out = ''.join(buf)
out_safe = out.encode('ascii', 'replace').decode('ascii')
print('=== BUILD (last 2000 chars) ===')
print(out_safe[-2000:] if len(out_safe) > 2000 else out_safe)
ch2.close()

print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-frontend --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

print('[recreate]...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

print('[wait] 30s...')
time.sleep(30)

print('[verify] entrypoint dual-iteration in NEW container:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -10"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] smoketest conf:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] smoketest endpoint:')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())
