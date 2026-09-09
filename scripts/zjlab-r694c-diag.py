"""Check nginx startup error."""
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

print('[1] nginx container logs (tail):')
stdin, stdout, stderr = tg.exec_command('docker logs --tail 30 gw-frontend 2>&1')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] stop container, run nginx manually to see error:')
stdin, stdout, stderr = tg.exec_command('docker stop gw-frontend 2>&1')
print(stdout.read().decode(errors='replace').rstrip())
stdin, stdout, stderr = tg.exec_command(
    'docker run --rm --name gw-fe-test '
    '--network gw-net '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d:/etc/nginx/conf.d '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-includes:/etc/nginx/includes:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-shared:/etc/nginx/shared:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx.conf:/etc/nginx/nginx.conf:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/mime.types:/etc/nginx/mime.types:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/ssl:/etc/nginx/ssl:ro '
    'gravitationalwave-v431-gw-frontend '
    'nginx -t 2>&1 | tail -10',
    timeout=30)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[1] nginx container logs (tail):')
stdin, stdout, stderr = tg.exec_command('docker logs --tail 30 gw-frontend 2>&1')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[2] stop container, run nginx manually to see error:')
stdin, stdout, stderr = tg.exec_command('docker stop gw-frontend 2>&1')
print(stdout.read().decode(errors='replace').rstrip())
stdin, stdout, stderr = tg.exec_command(
    'docker run --rm --name gw-fe-test '
    '--network gw-net '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d:/etc/nginx/conf.d '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-includes:/etc/nginx/includes:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-shared:/etc/nginx/shared:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx.conf:/etc/nginx/nginx.conf:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/mime.types:/etc/nginx/mime.types:ro '
    '-v /home/zjlab/gravitationalwave-v4.31/gw-frontend/ssl:/etc/nginx/ssl:ro '
    'gravitationalwave-v431-gw-frontend '
    'nginx -t 2>&1 | tail -10',
    timeout=30)
print(stdout.read().decode(errors='replace').rstrip())
