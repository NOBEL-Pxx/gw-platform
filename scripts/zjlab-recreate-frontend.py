#!/usr/bin/env python3
"""R6.92 helper: Recreate gw-frontend container on zjlab + verify smoketest.

Why: envsubst only runs at container startup (see gw-frontend/docker-entrypoint.sh
lines 13-39). After uploading r692-smoketest.template, we need the entrypoint to
re-run envsubst to generate r692-smoketest.conf. nginx -s reload alone is NOT
enough (it just reloads existing config, doesn't run envsubst on new templates).

Connection: reads creds from sync-to-zjlab.py source (not embedded).
"""
import paramiko
import socket
import sys
import time
import re
from pathlib import Path

# Read creds from sync-to-zjlab.py source (not embedded here)
sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')

m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_r = re.search(r"^REMOTE_ROOT\s*=\s*'([^']+)'", sync_src, re.M)

if not (m_b and m_s and m_r):
    print('ERROR: failed to parse creds from sync-to-zjlab.py')
    sys.exit(1)

BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))
REMOTE_ROOT = m_r.group(1)

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

print('[connect] OK')
print()

# === Step A: docker compose up -d --force-recreate gw-frontend (no rebuild) ===
cmd_a = ('cd {} && '
         'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
         'up -d --force-recreate --no-deps --no-build gw-frontend 2>&1 | tail -10').format(REMOTE_ROOT)
print('[recreate] {}'.format(cmd_a))
stdin, stdout, stderr = tg.exec_command(cmd_a, timeout=120)
out_a = stdout.read().decode(errors='replace').rstrip()
err_a = stderr.read().decode(errors='replace').rstrip()
print(out_a)
if err_a:
    print('STDERR:', err_a)
print('EXIT:', code)
print()

# === Step B: Wait for container to be healthy + check envsubst ran ===
print('[verify] Waiting 10s for container startup + entrypoint envsubst...')
time.sleep(10)

cmd_b = ('docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}" '
         '&& echo --- '
         '&& docker exec gw-frontend ls -la /etc/nginx/conf.d/ /etc/nginx/conf.d/templates/ 2>&1')
print('[verify] container status + generated confs')
stdin, stdout, stderr = tg.exec_command(cmd_b, timeout=30)
out_b = stdout.read().decode(errors='replace').rstrip()
print(out_b)
print()

# === Step C: curl smoketest endpoint (internal) ===
cmd_c = 'docker exec gw-frontend sh -c "curl -sk http://localhost:80/r692-smoketest-status 2>&1 || echo curl-failed"'
print('[smoketest internal] {}'.format(cmd_c))
stdin, stdout, stderr = tg.exec_command(cmd_c, timeout=10)
out_c = stdout.read().decode(errors='replace').rstrip()
print(out_c)
print()

# === Step D: external curl via 6001 ===
print('[smoketest external] curl http://localhost:6001/r692-smoketest-status')
stdin, stdout, stderr = tg.exec_command('curl -sk -w "\\nHTTP=%{http_code}\\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=10)
out_d = stdout.read().decode(errors='replace').rstrip()
print(out_d)

print()

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')
print()

# === Step A: docker compose up -d --force-recreate gw-frontend (no rebuild) ===
cmd_a = ('cd {} && '
         'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
         'up -d --force-recreate --no-deps --no-build gw-frontend 2>&1 | tail -10').format(REMOTE_ROOT)
print('[recreate] {}'.format(cmd_a))
stdin, stdout, stderr = tg.exec_command(cmd_a, timeout=120)
out_a = stdout.read().decode(errors='replace').rstrip()
err_a = stderr.read().decode(errors='replace').rstrip()
print(out_a)
if err_a:
    print('STDERR:', err_a)
print('EXIT:', code)
print()

# === Step B: Wait for container to be healthy + check envsubst ran ===
print('[verify] Waiting 10s for container startup + entrypoint envsubst...')
time.sleep(10)

cmd_b = ('docker ps --filter name=gw-frontend --format "table {{.Names}}\t{{.Status}}" '
         '&& echo --- '
         '&& docker exec gw-frontend ls -la /etc/nginx/conf.d/ /etc/nginx/conf.d/templates/ 2>&1')
print('[verify] container status + generated confs')
stdin, stdout, stderr = tg.exec_command(cmd_b, timeout=30)
out_b = stdout.read().decode(errors='replace').rstrip()
print(out_b)
print()

# === Step C: curl smoketest endpoint (internal) ===
cmd_c = 'docker exec gw-frontend sh -c "curl -sk http://localhost:80/r692-smoketest-status 2>&1 || echo curl-failed"'
print('[smoketest internal] {}'.format(cmd_c))
stdin, stdout, stderr = tg.exec_command(cmd_c, timeout=10)
out_c = stdout.read().decode(errors='replace').rstrip()
print(out_c)
print()

# === Step D: external curl via 6001 ===
print('[smoketest external] curl http://localhost:6001/r692-smoketest-status')
stdin, stdout, stderr = tg.exec_command('curl -sk -w "\\nHTTP=%{http_code}\\n" http://localhost:6001/r692-smoketest-status 2>&1', timeout=10)
out_d = stdout.read().decode(errors='replace').rstrip()
print(out_d)

print()
print('=== DONE ===')
