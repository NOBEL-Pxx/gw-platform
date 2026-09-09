"""R6.94c: Verify smoketest via 443 ssl (with HTTPS listener + filename 0-prefix)."""
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

print('[recreate] gw-frontend:')
cmd = ('cd ' + REMOTE_ROOT + ' && '
       'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
       'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -5')
stdin, stdout, stderr = tg.exec_command(cmd, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[wait] 25s...')
time.sleep(25)

print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "{{.Names}} {{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] conf.d files:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/*.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] nginx -t:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "nginx -t 2>&1 | tail -3"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTP 6001 -L (follow redirect):')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTPS 6002 direct:')
stdin, stdout, stderr = tg.exec_command(
    'curl -sk -w "\nHTTP=%{http_code}\n" --resolve localhost:6002:127.0.0.1 https://localhost:6002/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] regular page still works:')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -o /dev/null -w "HTTP=%{http_code}\n" http://localhost:6001/ 2>&1', timeout=15)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[recreate] gw-frontend:')
cmd = ('cd ' + REMOTE_ROOT + ' && '
       'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
       'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -5')
stdin, stdout, stderr = tg.exec_command(cmd, timeout=120)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[wait] 25s...')
time.sleep(25)

print('[verify] container status:')
stdin, stdout, stderr = tg.exec_command(
    'docker ps --filter name=gw-frontend --format "{{.Names}} {{.Status}}"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] conf.d files:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/*.conf"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] nginx -t:')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "nginx -t 2>&1 | tail -3"')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTP 6001 -L (follow redirect):')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] smoketest via HTTPS 6002 direct:')
stdin, stdout, stderr = tg.exec_command(
    'curl -sk -w "\nHTTP=%{http_code}\n" --resolve localhost:6002:127.0.0.1 https://localhost:6002/r692-smoketest-status 2>&1 | tail -5', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[verify] regular page still works:')
stdin, stdout, stderr = tg.exec_command(
    'curl -skL -o /dev/null -w "HTTP=%{http_code}\n" http://localhost:6001/ 2>&1', timeout=15)
print(stdout.read().decode(errors='replace').rstrip())
