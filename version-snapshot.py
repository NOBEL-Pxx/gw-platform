# R6.22 — DEPRECATION NOTICE for version-snapshot.py
#
# This script is DEPRECATED as of R6.22 (2026-09-01).
#
# WHY:
#   1. Covers only 27 files (out of hundreds in the repo).
#   2. No database migration tracking.
#   3. Rollback is manual file copy, not atomic.
#   4. Three version schemes coexisted: v4.55, R6.18/19/21, snapshot timestamps.
#
# REPLACEMENT: scripts/ci/version.py (Git tag based)
#   - Every file in the repo is versioned.
#   - Tag format: v4.56-R6.22 (single unified scheme).
#   - Rollback = `git checkout <tag>` (atomic).
#   - Audit trail in `.deploy-audit.log`.
#
# EXISTING SNAPSHOTS:
#   version-snapshots/snapshot_2026*/ remain valid as HISTORICAL RECORDS.
#   They are NOT removed (per user policy: no batch deletion).
#
# FOR NEW WORK:
#   Use: python scripts/ci/version.py tag v4.56-R6.22 -m "message"
#   Use: bash scripts/ci/deploy.sh deploy v4.56-R6.22
#
# See 引力波天文数据平台技术详解.md section v4.54 R6.22 for the full migration plan.
#
# ─────────────────────────────────────────────────────────────────────────
# Original script follows (kept for historical reference and emergency use)
# ─────────────────────────────────────────────────────────────────────────

# -*- coding: utf-8 -*-
"""
Version Rollback System for GravitationalWave Platform
Creates timestamped snapshots of key files. Usage:
  python version-snapshot.py save    — create a new snapshot
  python version-snapshot.py list    — list all snapshots
  python version-snapshot.py restore <timestamp>  — restore from snapshot
"""
import os, sys, shutil, json
from datetime import datetime

SNAPSHOT_DIR = r'D:\AliCPT\version-snapshots'
MANIFEST_FILE = os.path.join(SNAPSHOT_DIR, 'manifest.json')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Files to include in each snapshot (relative to D:\AliCPT)
TRACKED_FILES = [
    # Frontend source
    r'gw-frontend\src\pages\login\index.tsx',
    r'gw-frontend\src\components\AIFloatingButton.tsx',
    r'gw-frontend\src\pages\settings\index.tsx',
    r'gw-frontend\src\pages\assistant\index.tsx',
    r'gw-frontend\src\pages\common\Layout.tsx',
    r'gw-frontend\src\router.tsx',
    r'gw-frontend\src\index.css',
    r'gw-frontend\src\service\deepseek.ts',
    r'gw-frontend\src\service.ts',
    r'gw-frontend\src\data\ai-models.ts',
    r'gw-frontend\.env.development',
    r'gw-frontend\.env.production',
    r'gw-frontend\tailwind.config.js',
    r'gw-frontend\vite.config.ts',
    # Backend source (key controllers + services)
    r'gw-backend\gravitationalwave-server-web\src\main\java\com\zhejianglab\gravitationalwave\gravitationalwaveserver\service\controller\SearchController.java',
    r'gw-backend\gravitationalwave-server-web\src\main\java\com\zhejianglab\gravitationalwave\gravitationalwaveserver\service\controller\ErrorController.java',
    r'gw-backend\gravitationalwave-server-web\src\main\java\com\zhejianglab\gravitationalwave\gravitationalwaveserver\service\controller\AuthController.java',
    r'gw-backend\gravitationalwave-server-web\src\main\java\com\zhejianglab\gravitationalwave\gravitationalwaveserver\service\controller\StaticFileController.java',
    r'gw-backend\start\src\main\resources\application-local.properties',
    r'gw-backend\start\src\main\resources\application.properties',
    # Pipeline source (Python FastAPI)
    r'gw-pipeline\src\pipeline\server.py',
    r'gw-pipeline\src\pipeline\fits_core.py',
    r'gw-pipeline\src\pipeline\source_extraction.py',
    r'gw-pipeline\src\pipeline\thumbnail_cache.py',
    # Docker
    r'docker-compose.yml',
    # New backend LLM files (when created)
    r'gw-backend\gravitationalwave-server-web\src\main\java\com\zhejianglab\gravitationalwave\gravitationalwaveserver\service\controller\LlmController.java',
]

def save_snapshot():
    """Create a new timestamped snapshot."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'snapshot_{timestamp}')
    os.makedirs(snapshot_path, exist_ok=True)

    files_copied = []
    files_missing = []

    for rel_path in TRACKED_FILES:
        src = os.path.join(BASE_DIR, rel_path)
        dst = os.path.join(snapshot_path, rel_path)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            files_copied.append(rel_path)
        else:
            files_missing.append(rel_path)

    # Write manifest
    manifest = {
        'timestamp': timestamp,
        'date': datetime.now().isoformat(),
        'files_copied': len(files_copied),
        'files_missing': files_missing,
    }

    # Update master manifest
    all_manifests = []
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
            all_manifests = json.load(f)

    all_manifests.append(manifest)
    with open(MANIFEST_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_manifests, f, indent=2, ensure_ascii=False)

    print(f'Snapshot saved: snapshot_{timestamp}')
    print(f'  Files copied: {len(files_copied)}')
    if files_missing:
        print(f'  Files missing (not yet created): {len(files_missing)}')
        for m in files_missing:
            print(f'    - {m}')

def list_snapshots():
    """List all available snapshots."""
    if not os.path.exists(MANIFEST_FILE):
        print('No snapshots found.')
        return

    with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
        manifests = json.load(f)

    print(f'Total snapshots: {len(manifests)}')
    print()
    for i, m in enumerate(manifests):
        print(f'  [{i}] snapshot_{m["timestamp"]}')
        print(f'      Date: {m["date"]}')
        print(f'      Files: {m["files_copied"]}')
        print()

def restore_snapshot(timestamp):
    """Restore files from a specific snapshot."""
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'snapshot_{timestamp}')
    if not os.path.exists(snapshot_path):
        print(f'Snapshot not found: snapshot_{timestamp}')
        print('Use "list" to see available snapshots.')
        sys.exit(1)

    # First, create a safety backup of current state
    print('Creating safety backup of current state...')
    safety_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_snapshot()  # This creates a new snapshot with current files

    # Now restore
    restored = 0
    for rel_path in TRACKED_FILES:
        src = os.path.join(snapshot_path, rel_path)
        dst = os.path.join(BASE_DIR, rel_path)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1
            print(f'  Restored: {rel_path}')

    print(f'\nRestored {restored} files from snapshot_{timestamp}')
    print(f'A safety backup of the pre-restore state was saved as snapshot_{safety_ts}')

if __name__ == '__main__':
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    if len(sys.argv) < 2:
        print('Usage:')
        print('  python version-snapshot.py save              — create new snapshot')
        print('  python version-snapshot.py list              — list all snapshots')
        print('  python version-snapshot.py restore <timestamp> — restore snapshot')
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == 'save':
        save_snapshot()
    elif cmd == 'list':
        list_snapshots()
    elif cmd == 'restore':
        if len(sys.argv) < 3:
            print('Error: restore requires a timestamp. Use "list" to see available snapshots.')
            sys.exit(1)
        restore_snapshot(sys.argv[2])
    else:
        print(f'Unknown command: {cmd}')
        sys.exit(1)
