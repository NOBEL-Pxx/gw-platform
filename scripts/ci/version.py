#!/usr/bin/env python3
"""
R6.22 — Version Manager (Git tag based)
========================================
Replaces version-snapshot.py for all NEW versions.

The legacy version-snapshot.py covers only 27 source files, leaving the build
config, GitHub Actions, and other critical files unprotected. Git tags cover
EVERYTHING in version control.

LEGACY NOTE: version-snapshot.py is DEPRECATED but preserved (R6.22 deprecation
notice in version-snapshot.py itself). Existing snapshots in version-snapshots/
remain valid as historical records.

Usage:
  python scripts/ci/version.py tag v4.56-R6.22 -m "R6.22 version tag"
  python scripts/ci/version.py list
  python scripts/ci/version.py current
  python scripts/ci/version.py rollback v4.55-R6.21
  python scripts/ci/version.py validate v4.56-R6.22
"""
import sys, subprocess, re, json
from datetime import datetime

ALLOWED_PATTERN = re.compile(r'^v\d+\.\d+(\.\d+)?-R\d+\.\d+$')

def git(*args, **kw):
    return subprocess.run(['git'] + list(args), capture_output=True, text=True, **kw)

def err(msg):
    print(f'[ERR] {msg}', file=sys.stderr)
    sys.exit(1)

def ok(msg):
    print(f'[OK]  {msg}')

def validate_tag(tag):
    if not ALLOWED_PATTERN.match(tag):
        err(f'Bad tag format: {tag!r}. Expected: v4.56-R6.22 or v4.56.0-R6.22')

def cmd_tag(args):
    """Create a new versioned git tag."""
    if not args:
        err('Usage: version.py tag <tag> [-m message]')
    tag = args[0]
    validate_tag(tag)

    # Check if tag exists
    r = git('tag', '--list', tag)
    if r.stdout.strip():
        err(f'Tag already exists: {tag}')

    # Message
    msg = f'R6.22 version tag — {tag}'
    i = args.index('-m') if '-m' in args else -1
    if i > 0 and i + 1 < len(args):
        msg = args[i + 1]

    # Tag must be on clean tree (only staged/modified counts; untracked is fine)
    status = git('status', '--porcelain', '--untracked-files=no')
    if status.stdout.strip():
        err('Working tree has staged or modified files. Commit/stash first. Untracked files are OK.')

    r = git('tag', '-a', tag, '-m', msg)
    if r.returncode != 0:
        err(f'git tag failed: {r.stderr}')

    ok(f'Tagged {tag}: {msg}')
    print(f'  → push with: git push origin {tag}')

def cmd_list(_):
    """List all version tags, newest first."""
    r = git('tag', '--sort=-version:refname', '--format=%(refname:short)|%(subject)|%(taggerdate:iso)')
    if not r.stdout.strip():
        print('(no tags yet)')
        return
    print(f'{"TAG":<22} {"DATE":<22} MESSAGE')
    print('-' * 80)
    for line in r.stdout.strip().split('\n'):
        parts = line.split('|', 2)
        if len(parts) == 3:
            tag, subj, date = parts
            print(f'{tag:<22} {date[:19]:<22} {subj}')

def cmd_current(_):
    """Show current HEAD's tag (if any)."""
    r = git('describe', '--tags', '--exact-match', '--abbrev=0')
    if r.returncode == 0:
        print(f'HEAD is at tag: {r.stdout.strip()}')
        return
    # Try nearest
    r2 = git('describe', '--tags', '--abbrev=0')
    if r2.returncode == 0:
        print(f'HEAD is between tags. Nearest tag (older): {r2.stdout.strip()}')
    else:
        print('HEAD has no tag')

def cmd_rollback(args):
    """Roll back to a previous tag."""
    if not args:
        err('Usage: version.py rollback <tag>')
    tag = args[0]
    validate_tag(tag)
    r = git('tag', '--list', tag)
    if not r.stdout.strip():
        err(f'Tag does not exist: {tag}')

    print(f'⚠️  About to roll back to: {tag}')
    print('   This will: git checkout <tag> && docker compose up -d --force-recreate')
    confirm = input('   Type "yes" to confirm: ')
    if confirm != 'yes':
        err('Rollback cancelled')

    git('checkout', tag)
    ok(f'Checked out {tag}')
    print('  → now run: bash scripts/ci/deploy.sh deploy ' + tag)

def cmd_validate(args):
    """Validate a tag format and verify the tag exists."""
    if not args:
        err('Usage: version.py validate <tag>')
    tag = args[0]
    validate_tag(tag)
    r = git('tag', '--list', tag)
    if not r.stdout.strip():
        err(f'Tag does not exist: {tag}')
    ok(f'Valid: {tag}')

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    cmds = {
        'tag': cmd_tag,
        'list': cmd_list,
        'current': cmd_current,
        'rollback': cmd_rollback,
        'validate': cmd_validate,
    }
    if cmd not in cmds:
        err(f'Unknown command: {cmd}. Available: {", ".join(cmds.keys())}')
    cmds[cmd](args)

if __name__ == '__main__':
    main()
