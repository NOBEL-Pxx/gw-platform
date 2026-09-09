"""Check if R6.93 entrypoint fix is deployed + entrypoint run logs."""
import re, time
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

# 1. Check entrypoint fix in running container
print('[1] entrypoint R6.93 fix in running container?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -40"')
print(stdout.read().decode(errors='replace').rstrip())

# 2. Compare with host file
print()
print('[2] host entrypoint file:')
stdin, stdout, stderr = tg.exec_command(
    'grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh 2>&1 | head -40')
print(stdout.read().decode(errors='replace').rstrip())

# 3. Container start time vs file mod time
print()
print('[3] times:')
stdin, stdout, stderr = tg.exec_command(
    'docker inspect --format="{{.State.StartedAt}}" gw-frontend; '
    'stat -c "%y  %n" /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh')
print(stdout.read().decode(errors='replace').rstrip())

# 4. Container logs (entrypoint envsubst trace)
print()
print('[4] container logs (entrypoint envsubst trace):')
stdin, stdout, stderr = tg.exec_command('docker logs --tail 50 gw-frontend 2>&1 | head -60')
print(stdout.read().decode(errors='replace').rstrip())

# 5. Check 301 redirect source
print()
print('[5] where does /r692-smoketest-status go?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -skI http://localhost:80/r692-smoketest-status 2>&1"')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

# 1. Check entrypoint fix in running container
print('[1] entrypoint R6.93 fix in running container?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /docker-entrypoint.sh 2>&1 | head -40"')
print(stdout.read().decode(errors='replace').rstrip())

# 2. Compare with host file
print()
print('[2] host entrypoint file:')
stdin, stdout, stderr = tg.exec_command(
    'grep -n \'TEMPLATES_DIR\|conf.d/templates\|for tmpl in\|envsubst\' /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh 2>&1 | head -40')
print(stdout.read().decode(errors='replace').rstrip())

# 3. Container start time vs file mod time
print()
print('[3] times:')
stdin, stdout, stderr = tg.exec_command(
    'docker inspect --format="{{.State.StartedAt}}" gw-frontend; '
    'stat -c "%y  %n" /home/zjlab/gravitationalwave-v4.31/gw-frontend/docker-entrypoint.sh')
print(stdout.read().decode(errors='replace').rstrip())

# 4. Container logs (entrypoint envsubst trace)
print()
print('[4] container logs (entrypoint envsubst trace):')
stdin, stdout, stderr = tg.exec_command('docker logs --tail 50 gw-frontend 2>&1 | head -60')
print(stdout.read().decode(errors='replace').rstrip())

# 5. Check 301 redirect source
print()
print('[5] where does /r692-smoketest-status go?')
stdin, stdout, stderr = tg.exec_command(
    'docker exec gw-frontend sh -c "curl -skI http://localhost:80/r692-smoketest-status 2>&1"')
print(stdout.read().decode(errors='replace').rstrip())
