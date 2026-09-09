"""Diagnose why r692-smoketest.conf not generated despite entrypoint fix."""
import re
from pathlib import Path
import paramiko

sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')
m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))

ba = paramiko.SSHClient(); ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3], timeout=20, allow_agent=False, look_for_keys=False)
ch = ba.get_transport().open_channel('direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient(); tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)

print('[1] container entrypoint FULL contents (1-50):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "head -50 /docker-entrypoint.sh"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] container templates dir contents (bind mount?):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/templates/ 2>&1; echo ---; ls -la /etc/nginx/conf.d/ 2>&1 | head -20"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[3] container entrypoint envsubst trace (grep logs for envsubst):')
stdin, stdout, stderr = tg.exec_command(
    'docker logs gw-frontend 2>&1 | grep -i "envsubst\|templates\|r692" | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[4] Run envsubst manually inside container to see if it works:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cd /etc/nginx/conf.d && envsubst < templates/r692-smoketest.template > r692-smoketest.conf 2>&1 && echo OK || echo FAIL; ls -la r692-smoketest.conf 2>&1; cat r692-smoketest.conf 2>&1"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[1] container entrypoint FULL contents (1-50):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "head -50 /docker-entrypoint.sh"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] container templates dir contents (bind mount?):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/templates/ 2>&1; echo ---; ls -la /etc/nginx/conf.d/ 2>&1 | head -20"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[3] container entrypoint envsubst trace (grep logs for envsubst):')
stdin, stdout, stderr = tg.exec_command(
    'docker logs gw-frontend 2>&1 | grep -i "envsubst\|templates\|r692" | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[4] Run envsubst manually inside container to see if it works:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cd /etc/nginx/conf.d && envsubst < templates/r692-smoketest.template > r692-smoketest.conf 2>&1 && echo OK || echo FAIL; ls -la r692-smoketest.conf 2>&1; cat r692-smoketest.conf 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())
