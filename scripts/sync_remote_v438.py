"""Deploy v4.38 to remote ZhiJiang Lab server via SSH bastion."""
import paramiko, time, os

B = ('192.168.10.10', 60022, 'ZJWB260819', 'Temp@ecf4f6')
T = ('10.107.207.103', 22, 'zjlab', 'fast@zjlab')
R = '/home/zjlab/gravitationalwave-v4.31'
SRC = r'D:\AliCPT'

print('[1] Connecting via bastion...')
ba = paramiko.SSHClient()
ba.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ba.connect(B[0], B[1], B[2], B[3], timeout=20, allow_agent=False, look_for_keys=False)
ba.get_transport().set_keepalive(30)
ch = ba.get_transport().open_channel('direct-tcpip', (T[0], T[1]), ('127.0.0.1', 0), timeout=10)
tg = paramiko.SSHClient()
tg.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tg.connect(T[0], T[1], T[2], T[3], timeout=20, allow_agent=False, look_for_keys=False, sock=ch)
sftp = tg.open_sftp()
print('[OK] Connected')

# Ensure directories
print('[2] Creating remote directories...')
for d in ['gw-pipeline/src/pipeline', 'scripts', 'docs']:
    tg.exec_command(f'mkdir -p {R}/{d}', timeout=5)
time.sleep(1)

# Upload v4.38 Python modules
print('[3] Uploading v4.38 Python modules...')
modules = [
    'config_manager.py', 'provenance.py', 'routes_v438.py', 'fits_upload.py'
]
for m in modules:
    local = os.path.join(SRC, 'gw-pipeline', 'src', 'pipeline', m)
    if os.path.exists(local):
        sftp.put(local, f'{R}/gw-pipeline/src/pipeline/{m}')
        print(f'  {m}')

# Upload modified server.py
local_server = os.path.join(SRC, 'gw-pipeline', 'src', 'pipeline', 'server.py')
if os.path.exists(local_server):
    sftp.put(local_server, f'{R}/gw-pipeline/src/pipeline/server.py')
    print(f'  server.py')

# Hot-deploy into remote container
print('[4] Hot-deploying to remote gw-pipeline...')
for m in modules + ['server.py']:
    remote_src = f'{R}/gw-pipeline/src/pipeline/{m}'
    tg.exec_command(f'docker cp {remote_src} gw-pipeline:/app/src/pipeline/{m}', timeout=10)
    time.sleep(0.3)
    print(f'  {m}')

# Restart remote pipeline
print('[5] Restarting remote gw-pipeline...')
tg.exec_command('docker restart gw-pipeline', timeout=10)
time.sleep(8)

# Verify
print('[6] Verification...')
_, o, e = tg.exec_command('docker exec gw-pipeline python -c "import urllib.request; r=urllib.request.urlopen(\'http://localhost:8200/health\'); print(r.read().decode()[:150])"', timeout=10)
resp = o.read().decode('utf-8', errors='replace')
print(f'  Health: {resp[:150]}')

_, o, e = tg.exec_command('docker exec gw-pipeline python -c "import urllib.request; r=urllib.request.urlopen(\'http://localhost:8200/pipeline/metrics\'); d=r.read().decode(); print(len(d), \'bytes\', d.count(chr(10)), \'lines\')"', timeout=10)
metrics = o.read().decode('utf-8', errors='replace')
print(f'  Metrics: {metrics.strip()}')

_, o, e = tg.exec_command('docker exec gw-pipeline python -c "import urllib.request; r=urllib.request.urlopen(\'http://localhost:8200/pipeline/admin/config\'); print(r.status)"', timeout=10)
config_status = o.read().decode('utf-8', errors='replace').strip()
print(f'  Config endpoint: HTTP {config_status} (401=registered)')

_, o, e = tg.exec_command('curl -s -o /dev/null -w "%{http_code}" http://localhost:6001/', timeout=10)
frontend = o.read().decode('utf-8', errors='replace').strip()
print(f'  Frontend: HTTP {frontend}')

tg.close()
ba.close()
print('\n[DONE] Remote v4.38 deployment complete')
print('New features on remote:')
print('  Fix #2: OpenAPI /docs (rbac whitelist)')
print('  Fix #3: Config Manager — /pipeline/admin/config/*')
print('  Fix #4: Provenance/DOI — /pipeline/provenance/*')
print('  Fix #5: FITS Upload + Vision — /pipeline/fits/upload, /pipeline/agent/vision')
print('  Fix #6: Batch Export — /pipeline/export/*')
