"""Diagnose why r692-smoketest.conf not serving."""
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

print('[1] r692-smoketest.conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] default.conf (to see ssl block pattern):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/default.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[3] bind mount templates dir (still has stale r692-smoketest.template?):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/templates/"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[4] nginx config includes order:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/nginx.conf | grep -A2 -B1 include"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[1] r692-smoketest.conf contents:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/r692-smoketest.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] default.conf (to see ssl block pattern):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/conf.d/default.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[3] bind mount templates dir (still has stale r692-smoketest.template?):')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/templates/"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[4] nginx config includes order:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "cat /etc/nginx/nginx.conf | grep -A2 -B1 include"')
print(stdout.read().decode(errors='replace').rstrip())
