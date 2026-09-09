#!/usr/bin/env python3
"""R6.100 #3: DEPRECATED thin wrapper — image content checks (one-shot, NOT in zsmoke.py).

Original purpose (R6.97 #2): Verify gw-pipeline image has middleware/ + ip_whitelist.py
after actuator-rebuild deploy. Catches "wrong image deployed" class regressions.

Superseded by R6.99 #6 zsmoke.py for standing checks, BUT image content is one-shot
(deploy-time only), so kept as a thin wrapper.

Per r678-classifier-boundary: this script is READ-ONLY (it only PRINTS the docker
commands to run manually on the bastion). It does NOT actually run docker locally,
because that requires zkb.py + bastion creds.

MEDIUM #9 fix: removed auto --no-fail injection. Standing checks via zsmoke.py now
propagate exit codes correctly (was: always exited 0 due to --no-fail auto-append,
which masked failures).
"""
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ZSMOKE = SCRIPT_DIR / 'zsmoke.py'

if not ZSMOKE.exists():
    print('ERROR: zsmoke.py not found at {}'.format(ZSMOKE), file=sys.stderr)
    sys.exit(3)

print('[zjlab-verify-image] DEPRECATED: use zsmoke.py for standing checks.')
print('[zjlab-verify-image] This wrapper runs standing checks + prints image content commands.')

# Part 1: standing checks via zsmoke.py (forward all args; exit code propagates)
argv_standing = [sys.executable, str(ZSMOKE),
                 '--only', 'gw-frontend,gw-pipeline,gw-backend'] + sys.argv[1:]
print('[zjlab-verify-image] Standing checks: {}'.format(' '.join(argv_standing)))
rc_standing = subprocess.call(argv_standing)

# Part 2: image content checks (READ-ONLY — PRINT commands; do not execute).
# Reason: docker access requires bastion SSH; this script runs on the local D:\ machine.
print()
print('[zjlab-verify-image] Image content checks (READ-ONLY; run manually on bastion):')
print('  zkb ssh gw@10.107.207.103  # then:')
print('  docker inspect gravitationalwave-v431-gw-pipeline --format="ID={{.Id}} Created={{.Created}}"')
print('  docker run --rm gravitationalwave-v431-gw-pipeline sh -c "ls /app/src/pipeline/middleware/ 2>&1"')
print('  docker run --rm gravitationalwave-v431-gw-pipeline sh -c "find /app/src/pipeline -name ip_whitelist*"')

# Standing checks exit code is the authoritative signal
sys.exit(rc_standing)
