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
    'echo === gw-pipeline container state ===',
    'docker ps -a --filter name=gw-pipeline',
    'echo === gw-pipeline last 50 log lines ===',
    'docker logs gw-pipeline 2>&1 | tail -50',
    'echo === gw-pipeline image entrypoint/cmd ===',
    'docker inspect gw-pipeline --format="{{.Config.Cmd}}\nEntrypoint={{.Config.Entrypoint}}\nImage={{.Image}}"',
    'echo === list pipeline source dirs on host (R6.73 middleware change) ===',
    'ls -la /home/zjlab/gravitationalwave-v4.31/pipeline/ 2>&1 | head -20',
    'echo === find middleware files locally + remotely ===',
    'find /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/middleware -type f 2>&1 | head -20',
    'echo === src.pipeline.middleware import context ===',
    'grep -rn "from src.pipeline.middleware" /home/zjlab/gravitationalwave-v4.31/pipeline/ 2>&1 | head -10',
    'echo === other references to middleware ===',
    'grep -rn "IPWhitelistMiddleware\|middleware" /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/main.py /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/__init__.py /home/zjlab/gravitationalwave-v4.31/pipeline/src/main.py 2>&1 | head -20',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=30)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

cmds = [
    'echo === gw-pipeline container state ===',
    'docker ps -a --filter name=gw-pipeline',
    'echo === gw-pipeline last 50 log lines ===',
    'docker logs gw-pipeline 2>&1 | tail -50',
    'echo === gw-pipeline image entrypoint/cmd ===',
    'docker inspect gw-pipeline --format="{{.Config.Cmd}}\nEntrypoint={{.Config.Entrypoint}}\nImage={{.Image}}"',
    'echo === list pipeline source dirs on host (R6.73 middleware change) ===',
    'ls -la /home/zjlab/gravitationalwave-v4.31/pipeline/ 2>&1 | head -20',
    'echo === find middleware files locally + remotely ===',
    'find /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/middleware -type f 2>&1 | head -20',
    'echo === src.pipeline.middleware import context ===',
    'grep -rn "from src.pipeline.middleware" /home/zjlab/gravitationalwave-v4.31/pipeline/ 2>&1 | head -10',
    'echo === other references to middleware ===',
    'grep -rn "IPWhitelistMiddleware\|middleware" /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/main.py /home/zjlab/gravitationalwave-v4.31/pipeline/src/pipeline/__init__.py /home/zjlab/gravitationalwave-v4.31/pipeline/src/main.py 2>&1 | head -20',
]
for c in cmds:
    print('--- ' + c + ' ---')
    stdin, stdout, stderr = tg.exec_command(c, timeout=30)
    out = stdout.read().decode(errors='replace').rstrip()
    err = stderr.read().decode(errors='replace').rstrip()
    if out: print(out)
    if err and 'Warning' not in err: print('STDERR:', err)
    print()
