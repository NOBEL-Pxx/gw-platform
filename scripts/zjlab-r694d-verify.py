"""R6.94d final verify: smoketest via HTTPS 443 (direct resolver).

Re-verifies gw-frontend after R6.94d fix: smoketest endpoint must respond
200 on port 443 via `curl --resolve` (no Host header needed when using
the resolver to map the hostname to 127.0.0.1:6002).

R6.96: rewritten from scratch using Zkb (the old version was corrupted
by an incomplete paramiko -> Zkb refactor).
"""
from zkb import Zkb

z = Zkb()

# 1. force-recreate gw-frontend (the smoketest bindmount needs container restart)
print('[recreate gw-frontend]')
out, _ = z.run(
    'docker compose -f docker-compose.yml -f docker-compose.zjlab.yml '
    'up -d --force-recreate --no-deps gw-frontend 2>&1 | tail -5',
    timeout=120,
)
print(out.rstrip())

print('[wait 25s for nginx to start]')
import time; time.sleep(25)

# 2. container must be Up
out, _ = z.run(
    'docker ps --filter name=gw-frontend --format "{{.Names}} {{.Status}}"'
)
print('[status]', out.rstrip())

# 3. nginx config syntax must be valid
out, _ = z.run('docker exec gw-frontend sh -c "nginx -t 2>&1 | tail -3"')
print('[nginx -t]', out.rstrip())

# 4. smoketest via HTTPS 6002 with localhost:6002 resolved
print('[smoketest HTTPS 6002 direct]')
out, _ = z.run(
    'curl -sk --resolve "localhost:6002:127.0.0.1" '
    '-w "\nHTTP=%{http_code}\n" '
    'https://localhost:6002/r692-smoketest-status 2>&1 | tail -3',
    timeout=15,
)
print(out.rstrip())

# 5. smoketest via HTTP 6001 with -L follow
print('[smoketest via HTTP 6001 -L follow]')
out, _ = z.run(
    'curl -skL -w "\nHTTP=%{http_code}\n" '
    'http://localhost:6001/r692-smoketest-status 2>&1 | tail -3',
    timeout=15,
)
print(out.rstrip())

# 6. main app /index must still respond 200 (default.conf still handles it)
print('[regular /index still 200]')
out, _ = z.run(
    'curl -skL -o /dev/null -w "HTTP=%{http_code}\n" '
    'http://localhost:6001/ 2>&1',
    timeout=15,
)
print(out.rstrip())

# 7. gw-pipeline should also be running
out, _ = z.run(
    'docker ps --filter name=gw-pipeline --format "{{.Names}} {{.Status}}"'
)
print('[gw-pipeline status]', out.rstrip())

z.close()