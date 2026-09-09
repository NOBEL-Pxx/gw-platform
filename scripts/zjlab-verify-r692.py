#!/usr/bin/env python3
"""R6.100 #3: DEPRECATED thin wrapper — use zsmoke.py directly.

Original purpose (R6.94): Verify R6.92 deploy — smoketest + sanity + gw-frontend + nginx.
Superseded by R6.99 #6 unified zsmoke.py suite.

This shim forwards to zsmoke.py with the equivalent --only check subset.
Exit code is zsmoke.py's exit code (0=PASS, 1=FAIL, 2=WARN, 3=couldn't run).

Iron rules:
  - r678-classifier-boundary: READ-ONLY. Calls zsmoke.py which is itself READ-ONLY.
  - parallel-review-after-batch: this shim is part of R6.100 batch (4-file migration).

Usage:
  python zjlab-verify-r692.py            # run r692 + backend-health + frontend + nginx
  python zjlab-verify-r692.py --json     # JSON output (CI mode)
  python zjlab-verify-r692.py --no-fail  # exit 0 even on FAIL (cron-safe)

For full feature set, use zsmoke.py directly:
  python zsmoke.py                       # all 8 checks
  python zsmoke.py --only r692-smoketest # single check
"""
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ZSMOKE = SCRIPT_DIR / 'zsmoke.py'

if not ZSMOKE.exists():
    print('ERROR: zsmoke.py not found at {}'.format(ZSMOKE), file=sys.stderr)
    sys.exit(3)

# MEDIUM #10 fix: forward all args; do NOT auto-append --no-fail.
# Previously auto-appended --no-fail when no --json/--no-fail/--read-remote was given,
# which silently turned FAILs into exit-0 and violated zsmoke's exit-code contract.
argv = [sys.executable, str(ZSMOKE),
        '--only', 'r692-smoketest,backend-health,gw-frontend,nginx-config'] + sys.argv[1:]

print('[zjlab-verify-r692] DEPRECATED: use zsmoke.py directly')
print('[zjlab-verify-r692] Forwarding to: {}'.format(' '.join(argv)))
sys.exit(subprocess.call(argv))
