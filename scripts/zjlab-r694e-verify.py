"""R6.94e final verify: smoketest via custom Host header (default.conf unaffected).

Re-verifies gw-frontend after R6.94e fix: smoketest endpoint must respond
200 on port 443 with `Host: r692-smoketest.local`, and the main app
must STILL respond 200 on the default Host (default.conf handles it,
not shadowed by smoketest's unique server_name).

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
print('[nginx -t (no conflicts now?)]', out.rstrip())

# 4. smoketest via HTTPS 6002 with --resolve hostname:6002
print('[smoketest via HTTPS 6002 + Host header]')
out, _ = z.run(
    'curl -sk --resolve "r692-smoketest.local:6002:127.0.0.1" '
    '-w "\nHTTP=%{http_code}\n" '
    'https://r692-smoketest.local:6002/r692-smoketest-status 2>&1 | tail -3',
    timeout=15,
)
print(out.rstrip())

# 5. smoketest via HTTP 6001 with -L + Host header
print('[smoketest via 6001 -L + Host header]')
out, _ = z.run(
    'curl -skL -H "Host: r692-smoketest.local" '
    '-w "\nHTTP=%{http_code}\n" '
    'http://localhost:6001/r692-smoketest-status 2>&1 | tail -3',
    timeout=15,
)
print(out.rstrip())

# 6. main app /index (default.conf still handles it on default Host)
print('[regular /index (default.conf should handle)]')
out, _ = z.run(
    'curl -skL -o /dev/null -w "HTTP=%{http_code}\n" '
    'http://localhost:6001/ 2>&1',
    timeout=15,
)
print(out.rstrip())

# 7. main app /index on HTTPS 6002 with default Host (no smoketest override)
print('[regular /index (no Host override)]')
out, _ = z.run(
    'curl -sk -o /dev/null -w "HTTP=%{http_code}\n" '
    '--resolve "localhost:6002:127.0.0.1" https://localhost:6002/ 2>&1',
    timeout=15,
)
print(out.rstrip())

z.close()