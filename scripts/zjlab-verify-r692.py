"""R6.94: Verify R6.92 deploy — smoketest + sanity check + gw-frontend + nginx."""
import re, time
from pathlib import Path

sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')
m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))

import paramiko
ba = paramiko.SSHClient(); ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3], timeout=20, allow_agent=False, look_for_keys=False)
ch = ba.get_transport().open_channel('direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient(); tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)
print('[connect] OK')

# 1. Verify r692-smoketest.conf generated
print()
print('[1] smoketest conf generated?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf /etc/nginx/conf.d/templates/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# 2. curl smoketest internal
print()
print('[2] curl smoketest internal (http://localhost:80/r692-smoketest-status):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -sk -w \'\nHTTP=%{http_code}\n\' http://localhost:80/r692-smoketest-status 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# 3. curl smoketest external via 6001
print()
print('[3] curl smoketest external (http://localhost:6001/r692-smoketest-status):')
stdin, stdout, stderr = tg.exec_command(
    'curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

# 4. Verify gw-frontend status
print()
print('[4] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --filter name=gw-pipeline --filter name=gw-backend --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(stdout.read().decode(errors='replace').rstrip())

# 5. nginx -t inside gw-frontend
print()
print('[5] nginx config check inside container:')
stdin, stdout, stderr = tg.exec_command('docker exec gw-frontend sh -c "nginx -t 2>&1"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')

# 1. Verify r692-smoketest.conf generated
print()
print('[1] smoketest conf generated?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/r692-smoketest.conf /etc/nginx/conf.d/templates/ 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# 2. curl smoketest internal
print()
print('[2] curl smoketest internal (http://localhost:80/r692-smoketest-status):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -sk -w \'\nHTTP=%{http_code}\n\' http://localhost:80/r692-smoketest-status 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())

# 3. curl smoketest external via 6001
print()
print('[3] curl smoketest external (http://localhost:6001/r692-smoketest-status):')
stdin, stdout, stderr = tg.exec_command(
    'curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

# 4. Verify gw-frontend status
print()
print('[4] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --filter name=gw-pipeline --filter name=gw-backend --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(stdout.read().decode(errors='replace').rstrip())

# 5. nginx -t inside gw-frontend
print()
print('[5] nginx config check inside container:')
stdin, stdout, stderr = tg.exec_command('docker exec gw-frontend sh -c "nginx -t 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())
