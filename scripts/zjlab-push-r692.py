#!/usr/bin/env python3
"""USER-AUTHORIZED: Push commit c778aaf (R6.92+R6.93+R6.94) to r6.52 via SSH."""
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
print('[connect] OK')

print('[push] git push origin r6.52 via SSH:')
cmd = 'cd /home/zjlab/gravitationalwave-v4.31 && git push origin r6.52 2>&1'
out, code = z.run(cmd, timeout=180)
out = out.rstrip()
print(out)
print('EXIT:', code)

print()
print('[verify] remote SHA:')
out, code = z.run('git ls-remote origin r6.52 2>&1 | head -3')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[connect] OK')

print('[push] git push origin r6.52 via SSH:')
cmd = 'cd /home/zjlab/gravitationalwave-v4.31 && git push origin r6.52 2>&1'
stdin, stdout, stderr = tg.exec_command(cmd, timeout=180)
out = out.rstrip()
print(out)
print('EXIT:', code)

print()
print('[verify] remote SHA:')
stdin, stdout, stderr = tg.exec_command(
    'git ls-remote origin r6.52 2>&1 | head -3')
print(stdout.read().decode(errors='replace').rstrip())