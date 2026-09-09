"""Find the actual git repo on zjlab."""
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

print('[find] git repo dirs on zjlab:')
stdin, stdout, stderr = tg.exec_command('find /home/zjlab -maxdepth 3 -name ".git" -type d 2>/dev/null | head -10')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] /home/zjlab structure:')
stdin, stdout, stderr = tg.exec_command('ls -la /home/zjlab/ 2>&1 | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] gravitationalwave-v4.31 .git link or real dir?')
stdin, stdout, stderr = tg.exec_command('ls -la /home/zjlab/gravitationalwave-v4.31/ 2>&1 | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] git remotes for known repo:')
stdin, stdout, stderr = tg.exec_command('cat /home/zjlab/gravitationalwave-v4.31/.git/config 2>&1 | head -20')

# R6.96: refactored to use Zkb unified SSH wrapper (replaces paramiko boilerplate)
from zkb import Zkb
z = Zkb()

print('[find] git repo dirs on zjlab:')
stdin, stdout, stderr = tg.exec_command('find /home/zjlab -maxdepth 3 -name ".git" -type d 2>/dev/null | head -10')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] /home/zjlab structure:')
stdin, stdout, stderr = tg.exec_command('ls -la /home/zjlab/ 2>&1 | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] gravitationalwave-v4.31 .git link or real dir?')
stdin, stdout, stderr = tg.exec_command('ls -la /home/zjlab/gravitationalwave-v4.31/ 2>&1 | head -20')
print(stdout.read().decode(errors='replace').rstrip())

print()
print('[check] git remotes for known repo:')
stdin, stdout, stderr = tg.exec_command('cat /home/zjlab/gravitationalwave-v4.31/.git/config 2>&1 | head -20')
print(stdout.read().decode(errors='replace').rstrip())
