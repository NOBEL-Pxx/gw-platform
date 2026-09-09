import paramiko, re
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
    # Show LOCAL default.conf for comparison
    'echo === LOCAL D:\AliCPT\gw-frontend\nginx-conf.d\default.conf ===',
    'cat /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf',
    'echo === END LOCAL ===',
    'echo === CONTAINER /etc/nginx/conf.d/default.conf (FIRST 50 LINES) ===',
    'docker exec gw-frontend head -50 /etc/nginx/conf.d/default.conf',
    'echo === CONTAINER default.conf size + line count ===',
    'docker exec gw-frontend sh -c "wc -lc /etc/nginx/conf.d/default.conf"',
    'echo === HOST default.conf size ===',
    'wc -lc /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf',
]
for c in cmds:
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    print('> ' + c)
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

cmds = [
    # Show LOCAL default.conf for comparison
    'echo === LOCAL D:\AliCPT\gw-frontend\nginx-conf.d\default.conf ===',
    'cat /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf',
    'echo === END LOCAL ===',
    'echo === CONTAINER /etc/nginx/conf.d/default.conf (FIRST 50 LINES) ===',
    'docker exec gw-frontend head -50 /etc/nginx/conf.d/default.conf',
    'echo === CONTAINER default.conf size + line count ===',
    'docker exec gw-frontend sh -c "wc -lc /etc/nginx/conf.d/default.conf"',
    'echo === HOST default.conf size ===',
    'wc -lc /home/zjlab/gravitationalwave-v4.31/gw-frontend/nginx-conf.d/default.conf',
]
for c in cmds:
    stdin, stdout, stderr = tg.exec_command(c, timeout=20)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    print('> ' + c)
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)
    print()
