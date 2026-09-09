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
    'echo === /etc/nginx/templates/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/templates/ 2>&1',
    'echo === /etc/nginx/conf.d/templates/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/conf.d/templates/ 2>&1',
    'echo === /etc/nginx/conf.d/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/conf.d/ 2>&1',
    'echo === head of default.conf in container ===',
    'docker exec gw-frontend head -5 /etc/nginx/conf.d/default.conf 2>&1',
    'echo === wc default.conf in container ===',
    'docker exec gw-frontend wc -c /etc/nginx/conf.d/default.conf 2>&1',
    'echo === wc default.conf on HOST bind-mount source ===',
    'wc -c /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf 2>&1',
    'echo === check if envsubst ran (looking at entrypoint log via container inspect) ===',
    'docker inspect gw-frontend --format="{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}"',
]
for c in cmds:
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    print('> ' + c)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

cmds = [
    'echo === /etc/nginx/templates/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/templates/ 2>&1',
    'echo === /etc/nginx/conf.d/templates/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/conf.d/templates/ 2>&1',
    'echo === /etc/nginx/conf.d/ contents ===',
    'docker exec gw-frontend ls -la /etc/nginx/conf.d/ 2>&1',
    'echo === head of default.conf in container ===',
    'docker exec gw-frontend head -5 /etc/nginx/conf.d/default.conf 2>&1',
    'echo === wc default.conf in container ===',
    'docker exec gw-frontend wc -c /etc/nginx/conf.d/default.conf 2>&1',
    'echo === wc default.conf on HOST bind-mount source ===',
    'wc -c /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf 2>&1',
    'echo === check if envsubst ran (looking at entrypoint log via container inspect) ===',
    'docker inspect gw-frontend --format="{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}"',
]
for c in cmds:
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    print('> ' + c)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)
    print()
