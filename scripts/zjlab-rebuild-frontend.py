"""R6.94: Rebuild gw-frontend image + recreate + verify smoketest via HTTPS."""
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

# Verify R6.93 fix is in host file
print()
print('[pre-check] host entrypoint R6.93 fix:')
stdin, stdout, stderr = tg.exec_command(
    'grep -n "TEMPLATES_DIR\|conf.d/templates" /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh 2>&1 | head -10')
print(stdout.read().decode(errors='replace').rstrip())

# Force rebuild (NO --no-cache since host file may have CRLF or other cache triggers)
print()
print('[rebuild] docker build gw-frontend (streaming)...')
import socket
cmd = ('cd ' + REMOTE_ROOT + '/gw-frontend && '
       'docker build -t gravitationalwave-v431-gw-frontend . 2>&1')
print('cmd:', cmd)
ch2 = tg.get_transport().open_session(timeout=600)
ch2.settimeout(600)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data: break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s')
            break
except socket.timeout:
    pass
out = ''.join(buf)
print('=== BUILD OUTPUT (last 3000 chars) ===')
print(out[-3000:] if len(out) > 3000 else out)
ch2.close()

# Verify new image SHA
print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-frontend --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

# Force recreate
print()
print('[recreate] docker compose up -d --force-recreate gw-frontend...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

# Wait + verify entrypoint
print()
print('[wait] 25s for startup...')
time.sleep(25)

print('[verify] entrypoint R6.93 dual-iteration in NEW container:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -20"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest conf generated:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf /etc/nginx/conf.d/templates/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTPS (6002):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -sk -w \'\nHTTP=%{http_code}\n\' https://localhost:443/r692-smoketest-status -k 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via external 6001 (follow redirect):')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')

# Verify R6.93 fix is in host file
print()
print('[pre-check] host entrypoint R6.93 fix:')
stdin, stdout, stderr = tg.exec_command(
    'grep -n "TEMPLATES_DIR\|conf.d/templates" /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh 2>&1 | head -10')
print(stdout.read().decode(errors='replace').rstrip())

# Force rebuild (NO --no-cache since host file may have CRLF or other cache triggers)
print()
print('[rebuild] docker build gw-frontend (streaming)...')
import socket
cmd = ('cd ' + REMOTE_ROOT + '/gw-frontend && '
       'docker build -t gravitationalwave-v431-gw-frontend . 2>&1')
print('cmd:', cmd)
ch2 = tg.get_transport().open_session(timeout=600)
ch2.settimeout(600)
ch2.exec_command(cmd)
buf = []
start = time.time()
try:
    while True:
        data = ch2.recv(65536)
        if not data: break
        buf.append(data.decode(errors='replace'))
        if time.time() - start > 480:
            print('  [timeout-guard] hit 480s')
            break
except socket.timeout:
    pass
out = ''.join(buf)
print('=== BUILD OUTPUT (last 3000 chars) ===')
print(out[-3000:] if len(out) > 3000 else out)
ch2.close()

# Verify new image SHA
print()
print('[verify] new image SHA:')
stdin, stdout, stderr = tg.exec_command('docker images gravitationalwave-v431-gw-frontend --format "{{.ID}}  {{.CreatedAt}}"')
print(stdout.read().decode(errors='replace').rstrip())

# Force recreate
print()
print('[recreate] docker compose up -d --force-recreate gw-frontend...')
cmd2 = ('cd ' + REMOTE_ROOT + ' && '
        'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
        'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -10')
stdin, stdout, stderr = tg.exec_command(cmd2, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

# Wait + verify entrypoint
print()
print('[wait] 25s for startup...')
time.sleep(25)

print('[verify] entrypoint R6.93 dual-iteration in NEW container:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -20"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest conf generated:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf /etc/nginx/conf.d/templates/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTPS (6002):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -sk -w \'\nHTTP=%{http_code}\n\' https://localhost:443/r692-smoketest-status -k 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via external 6001 (follow redirect):')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())
