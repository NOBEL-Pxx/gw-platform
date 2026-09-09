# -*- coding: utf-8 -*-
r"""migrate-zkb-to-repo.py - R6.98 zkb migration (Phase 1: copy + verify).

Copies zkb.py + 32 zjlab-*.py from C:/Users/28610/ to D:/AliCPT/scripts/.
Does NOT delete originals - that requires explicit USER confirmation per
[[recycle-bin-only]] + [[manual-confirm-major-changes]].

Per [[r677-amend-force-push]]: explicit staging only (no bulk rm).
Per [[r676b-classifier-auth]]: USER must say "yes delete originals" before
the deletion step (separate phase).
"""
import ast
import glob
import os
import shutil
import sys
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding='utf-8', errors='replace')
    except: pass

SRC_DIR = Path(r'C:\Users\28610')
DST_DIR = Path(r'D:\AliCPT\scripts')

FILES = ['zkb.py'] + sorted([os.path.basename(f) for f in glob.glob(str(SRC_DIR / 'zjlab-*.py'))])

print('=== R6.98 zkb migration: Phase 1 (COPY only) ===')
print('Source: %s' % SRC_DIR)
print('Dest:   %s' % DST_DIR)
print('Files:  %d (zkb.py + %d zjlab-*.py)' % (len(FILES), len(FILES)-1))
print()

copied = []
skipped = []
errors = []

for fname in FILES:
    src = SRC_DIR / fname
    dst = DST_DIR / fname
    if not src.exists():
        errors.append('MISSING: %s' % src)
        continue
    try:
        if dst.exists():
            if src.read_bytes() == dst.read_bytes():
                skipped.append((fname, 'identical'))
                continue
            backup = DST_DIR / (fname + '.preR698')
            shutil.copy2(dst, backup)
            shutil.copy2(src, dst)
            copied.append((fname, 'overwrote (backup at .preR698)'))
        else:
            shutil.copy2(src, dst)
            copied.append((fname, 'new'))
    except Exception as e:
        errors.append('COPY FAIL: %s: %s' % (fname, e))

print('Copied: %d' % len(copied))
for f, msg in copied:
    print('  + %-40s %s' % (f, msg))
print('Skipped (identical): %d' % len(skipped))
for f, msg in skipped:
    print('  = %-40s %s' % (f, msg))
if errors:
    print('Errors: %d' % len(errors))
    for e in errors:
        print('  ! %s' % e)
print()

print('=== Phase 2: Verify ===')
all_ok = True
for fname in FILES:
    dst = DST_DIR / fname
    if not dst.exists():
        print('  FAIL %-40s missing' % fname)
        all_ok = False
        continue
    try:
        ast.parse(dst.read_text(encoding='utf-8'), filename=fname)
        print('  OK   %-40s %d bytes' % (fname, dst.stat().st_size))
    except SyntaxError as e:
        print('  FAIL %-40s %s' % (fname, e))
        all_ok = False

print()
print('=== Phase 3: zkb import test ===')
sys.path.insert(0, str(DST_DIR))
try:
    if 'zkb' in sys.modules:
        del sys.modules['zkb']
    import zkb
    print('  OK   zkb imported from %s' % zkb.__file__)
    print('  zkb.DEFAULT_SYNC_SCRIPT: %s' % zkb.DEFAULT_SYNC_SCRIPT)
    print('  zkb.parse_creds(): %s' % (zkb.parse_creds() is not None))
    for attr in ('sftp_put_text', 'sftp_get_text', 'docker_reload_nginx'):
        if hasattr(zkb.Zkb, attr):
            print('  OK   Zkb.%s() exists' % attr)
        else:
            print('  FAIL Zkb.%s() missing' % attr)
            all_ok = False
except Exception as e:
    print('  FAIL zkb import: %s' % e)
    all_ok = False
print()

print('=== RESULT ===')
if all_ok and not errors:
    print('MIGRATION COPY + VERIFY PASSED')
    print()
    print('Total files in D:\\AliCPT\\scripts\\:')
    n_zjlab = len(list(DST_DIR.glob('zjlab-*.py')))
    has_zkb = (DST_DIR / 'zkb.py').exists()
    print('  zjlab-*.py: %d' % n_zjlab)
    print('  zkb.py:     %s' % ('YES' if has_zkb else 'NO'))
    print()
    print('NEXT STEP - USER must confirm before deletion of originals:')
    print('  python C:\\Users\\28610\\migrate-zkb-to-repo.py delete')
    print()
    print('Until delete is run, originals at C:\\Users\\28610\\ remain intact.')
    print('Both copies will work - Python sys.path prefers script directory.')
else:
    print('MIGRATION FAILED - see errors above. Do NOT proceed to delete.')
    sys.exit(1)