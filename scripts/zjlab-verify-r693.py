#!/usr/bin/env python3
"""R6.100 #3: DEPRECATED thin wrapper — use zsmoke.py directly.

Original purpose (R6.93): Verify entrypoint + conf.d + smoketest after deploy.
Superseded by R6.99 #6 unified zsmoke.py suite.

This shim forwards to zsmoke.py with the equivalent --only check subset.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ZSMOKE = SCRIPT_DIR / 'zsmoke.py'

if not ZSMOKE.exists():
    print('ERROR: zsmoke.py not found at {}'.format(ZSMOKE), file=sys.stderr)
    sys.exit(3)

argv = [sys.executable, str(ZSMOKE),
        '--only', 'nginx-config,gw-frontend'] + sys.argv[1:]

print('[zjlab-verify-r693] DEPRECATED: use zsmoke.py directly')
print('[zjlab-verify-r693] Forwarding to: {}'.format(' '.join(argv)))
sys.exit(subprocess.call(argv))
