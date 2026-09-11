#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild-divs-backend-with-actuator.py — DEPRECATED R6.81a.

R6.81a (2026-09-11) consolidated this script + rebuild-actuator-and-deploy.py
+ the R6.80 jar-deploy path into a single canonical wrapper:

    D:\\AliCPT\\scripts\\build-and-deploy-jar.py

The original R6.103 procedure used a stale `mvn -pl start package` command
(without `-am`), which silently reused .m2 cached upstream JARs and shipped
stale code. The new wrapper HARD-CODES `-am` and verifies jar contents.

USE THE NEW SCRIPT:
    python D:\\AliCPT\\scripts\\build-and-deploy-jar.py check     # diagnostic
    python D:\\AliCPT\\scripts\\build-and-deploy-jar.py build     # Phase A: mvn -pl start -am
    python D:\\AliCPT\\scripts\\build-and-deploy-jar.py deploy    # Phase B: SFTP + docker cp
    python D:\\AliCPT\\scripts\\build-and-deploy-jar.py verify    # /api/health probe
    python D:\\AliCPT\\scripts\\build-and-deploy-jar.py all       # build + deploy + verify

This file is kept for backward-compatibility (shell history may still call it)
but immediately exits with a clear pointer to the new wrapper.

REMOVAL PLAN: this stub can be safely deleted after one release cycle (R6.82+).
Per [[recycle-bin-only]] use send2trash rather than `rm`.
"""
from __future__ import annotations
import sys


def main():
    print('=' * 72)
    print('DEPRECATED R6.81a: rebuild-divs-backend-with-actuator.py')
    print('=' * 72)
    print()
    print('This script has been superseded by:')
    print('  D:\\AliCPT\\scripts\\build-and-deploy-jar.py')
    print()
    print('The original procedure used `mvn -pl start package` WITHOUT `-am`,')
    print('which silently reused stale .m2 cached upstream JARs (the R6.80 bug).')
    print('The new wrapper HARD-CODES `-am` and verifies jar contents.')
    print()
    print('Run one of:')
    print('  python build-and-deploy-jar.py check')
    print('  python build-and-deploy-jar.py build')
    print('  python build-and-deploy-jar.py deploy')
    print('  python build-and-deploy-jar.py verify')
    print('  python build-and-deploy-jar.py all')
    print()
    print('See: docs/changelog/r6_78_v4.65_R6.81a.md for the full R6.81a design.')
    sys.exit(64)  # EX_USAGE — caller invoked a deprecated entry point


if __name__ == '__main__':
    main()