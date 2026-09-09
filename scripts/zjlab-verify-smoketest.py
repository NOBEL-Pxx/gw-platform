import paramiko, re, time
from pathlib import Path

sync_src = Path(r'D:\AliCPT\scripts\sync-to-zjlab.py').read_text(encoding='utf-8')
m_b = re.search(r"^BASTION\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
m_s = re.search(r"^SERVER\s*=\s*\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)", sync_src, re.M)
BASTION = (m_b.group(1), int(m_b.group(2)), m_b.group(3), m_b.group(4))
SERVER  = (m_s.group(1), int(m_s.group(2)), m_s.group(3), m_s.group(4))

ba = paramiko.SSHClient()
ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(BASTION[0], BASTION[1], BASTION[2], BASTION[3], timeout=20, allow_agent=False, look_for_keys=False)
ba.get_transport().set_keepalive(30)
ch = ba.get_transport().open_channel('direct-tcpip', (SERVER[0], SERVER[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient()
tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(SERVER[0], SERVER[1], SERVER[2], SERVER[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)

cmds = [
    'echo === container status (all gw-) ===',
    'docker ps -a --filter name=gw- --format "table {{.Names}}\t{{.Status}}"',
    'echo === r692-smoketest.conf exists? ===',
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/ && echo --- && test -f /etc/nginx/conf.d/r692-smoketest.conf && echo EXISTS || echo MISSING"',
    'echo === r692-smoketest.conf content ===',
    'docker exec gw-frontend cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1',
    'echo === nginx config test ===',
    'docker exec gw-frontend nginx -t 2>&1 | tail -5',
    'echo === external curl smoketest (port 6001) ===',
    'curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status',
    'echo === internal curl smoketest (port 80) ===',
    'docker exec gw-frontend curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:80/r692-smoketest-status',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err and 'duplicate' not in err: print('STDERR:', err)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

cmds = [
    'echo === container status (all gw-) ===',
    'docker ps -a --filter name=gw- --format "table {{.Names}}\t{{.Status}}"',
    'echo === r692-smoketest.conf exists? ===',
    'docker exec gw-frontend sh -c "ls -la /etc/nginx/conf.d/ && echo --- && test -f /etc/nginx/conf.d/r692-smoketest.conf && echo EXISTS || echo MISSING"',
    'echo === r692-smoketest.conf content ===',
    'docker exec gw-frontend cat /etc/nginx/conf.d/r692-smoketest.conf 2>&1',
    'echo === nginx config test ===',
    'docker exec gw-frontend nginx -t 2>&1 | tail -5',
    'echo === external curl smoketest (port 6001) ===',
    'curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:6001/r692-smoketest-status',
    'echo === internal curl smoketest (port 80) ===',
    'docker exec gw-frontend curl -sk -w "\nHTTP=%{http_code}\n" http://localhost:80/r692-smoketest-status',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err and 'duplicate' not in err: print('STDERR:', err)
    print()
