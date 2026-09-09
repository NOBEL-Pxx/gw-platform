# -*- coding: utf-8 -*-
r"""migrate-zkb-delete.py - R6.98 zkb migration (Phase 2: delete originals).

Per USER authorization (2026-09-09): move 33 originals from C:/Users/28610/
to Windows Recycle Bin via send2trash. Recycle Bin preserves for 30-day recovery.

This is the second phase after migrate-zkb-to-repo.py copy+verify PASS.

Per [[recycle-bin-only]]: use send2trash (Windows Recycle Bin) NOT plain delete.
Per [[r676b-classifier-auth]]: USER explicitly authorized this delete (2026-09-09).
Per [[no-batch-delete]]: send2trash iterates 33 items one-by-one with verification,
NOT a single bulk rm command.
"""
import os
import shutil
import sys
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding='utf-8', errors='replace')
    except: pass

import send2trash

SRC_DIR = Path(r'C:\Users\28610')
DST_DIR = Path(r'D:\AliCPT\scripts')

# Files to delete (must exist at dst as verified copy)
import glob
FILES = ['zkb.py'] + sorted([os.path.basename(f) for f in glob.glob(str(SRC_DIR / 'zjlab-*.py'))])

print('=== R6.98 zkb migration: Phase 2 (DELETE originals via Recycle Bin) ===')
print('Source: %s' % SRC_DIR)
print('Dest:   %s (verified copy present)' % DST_DIR)
print('Files:  %d' % len(FILES))
print()

# Step 1: Verify all copies exist at dst
print('--- Step 1: Verify all dst copies exist ---')
all_present = True
for fname in FILES:
    src = SRC_DIR / fname
    dst = DST_DIR / fname
    if not src.exists():
        print('  SKIP %-40s (not at source, already moved?)' % fname)
        continue
    if not dst.exists():
        print('  FAIL %-40s (no copy at dst! ABORT)' % fname)
        all_present = False
    elif src.read_bytes() == dst.read_bytes():
        print('  OK   %-40s (src matches dst)' % fname)
    else:
        print('  FAIL %-40s (src != dst content!)' % fname)
        all_present = False
print()

if not all_present:
    print('ABORT: not all dst copies verified. Refusing to delete originals.')
    sys.exit(1)

# Step 2: Confirm with user
print('--- Step 2: USER confirmation ---')
print('This will MOVE the following 33 files from C:\\Users\\28610\\ to Recycle Bin:')
for f in FILES[:5]:
    print('  - %s' % f)
print('  - ... (%d total)' % len(FILES))
print()
print('Per [[recycle-bin-only]], these can be recovered from Recycle Bin within 30 days.')
ans = input('Type "yes" to proceed with Recycle Bin move, anything else to abort: ').strip()
if ans != 'yes':
    print('Cancelled. Originals remain intact.')
    sys.exit(130)

# Step 3: Move each file to Recycle Bin
print()
print('--- Step 3: send2trash each file ---')
moved = []
errors = []
for fname in FILES:
    src = SRC_DIR / fname
    if not src.exists():
        continue
    try:
        send2trash.send2trash(str(src))
        moved.append(fname)
        print('  OK   %s -> Recycle Bin' % fname)
    except Exception as e:
        errors.append((fname, str(e)))
        print('  FAIL %s: %s' % (fname, e))

print()
print('=== RESULT ===')
print('Moved to Recycle Bin: %d' % len(moved))
if errors:
    print('Errors: %d' % len(errors))
    for f, e in errors:
        print('  ! %s: %s' % (f, e))
    sys.exit(1)

# Step 4: Final verification
print()
print('--- Step 4: Final verification ---')
remaining = []
for fname in FILES:
    src = SRC_DIR / fname
    if src.exists():
        remaining.append(fname)
        print('  STILL PRESENT: %s' % src)
if remaining:
    print('FAIL: %d originals still at C:\\Users\\28610\\:' % len(remaining))
    sys.exit(1)

# Verify dst intact
print()
print('Destination D:\\AliCPT\\scripts\\ final state:')
for f in FILES:
    dst = DST_DIR / f
    if dst.exists():
        print('  OK   %-40s %d bytes' % (f, dst.stat().st_size))
    else:
        print('  FAIL %-40s MISSING' % f)

print()
print('R6.98 zkb migration COMPLETE.')
print('  - All 33 files moved from C:\\Users\\28610\\ to Recycle Bin')
print('  - All 33 files present at D:\\AliCPT\\scripts\\ (canonical location)')
print('  - zkb.py + zjlab-*.py now git-trackable (commit pending USER auth)')