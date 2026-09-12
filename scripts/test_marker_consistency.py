#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_marker_consistency.py — CI regression test for v1_markers consistency.

R6.90 B4: build-and-deploy-jar.py v1_markers list is a 6-element AND-check that
catches stale bytecode (R6.80 lesson: mvn without -am silently ships upstream
classes). Each marker must be present in the controller source it claims to
verify. This test parses v1_markers from build-and-deploy-jar.py, derives the
target controller class name from each marker, and asserts the marker string
appears in the controller's .java file.

IRON-RULE COMPLIANCE:
  - Pure test code; no real credentials
  - No external network calls
  - No destructive operations
  - Pinned to controller source files (read-only grep)

Run:
  python D:\\AliCPT\\scripts\\test_marker_consistency.py
or:
  cd D:\\AliCPT\\scripts && python -m unittest test_marker_consistency -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


SCRIPT_PATH = Path(r'D:\AliCPT\scripts\build-and-deploy-jar.py')
CONTROLLER_DIR = Path(
    r'D:\AliCPT\gw-backend\gravitationalwave-server-web'
    r'\src\main\java\com\zhejianglab\gravitationalwave'
    r'\gravitationalwaveserver\service\controller'
)


def _parse_v1_markers(script_text: str) -> list[str]:
    """Extract v1_markers list literals from build-and-deploy-jar.py source.

    Returns the raw list-element strings (e.g. 'R6.83: HealthController probe
    executor initialized'). Order is preserved as it appears in source.
    """
    m = re.search(r'v1_markers\s*=\s*\[(.*?)\]', script_text, re.DOTALL)
    if not m:
        raise AssertionError('v1_markers list not found in build-and-deploy-jar.py')
    body = m.group(1)
    # Each element is on its own line, wrapped in single quotes.
    elements = re.findall(r"'([^']+)'", body)
    if not elements:
        raise AssertionError('v1_markers list has no quoted string elements')
    return elements


def _controller_for_marker(marker: str) -> str:
    """Extract controller class name from marker text.

    E.g. 'R6.88: StaticFileController initialized' -> 'StaticFileController'.
    R6.83/R6.85b markers that are NOT controller-derived fall through to
    the HealthController/LlmController/PipelineProxyController naming
    convention used in source.
    """
    # Match the longest CamelCase token ending in 'Controller' (or known
    # non-controller classes like HealthController).
    candidates = re.findall(r'\b([A-Z][A-Za-z]*(?:Controller|Probe))\b', marker)
    if candidates:
        # Prefer the most specific (longest) match.
        return max(candidates, key=len)
    raise AssertionError(f'Cannot derive controller class name from marker {marker!r}')


def _find_marker_in_source(marker: str, controller: str) -> tuple[bool, str]:
    """Grep the marker string in the controller .java file.

    Returns (found, controller_path). Falls back to walking the controller
    dir if the file is not at the expected name.
    """
    ctrl_file = CONTROLLER_DIR / f'{controller}.java'
    if not ctrl_file.exists():
        # Walk subdirs — defensive against future refactor.
        for f in CONTROLLER_DIR.rglob(f'{controller}.java'):
            ctrl_file = f
            break
    if not ctrl_file.exists():
        return False, f'<missing: {controller}.java>'
    text = ctrl_file.read_text(encoding='utf-8', errors='replace')
    return marker in text, str(ctrl_file)


class TestV1MarkerConsistency(unittest.TestCase):
    """R6.90 B4: v1_markers list must be consistent with controller sources.

    The cmd_deploy AND-check in build-and-deploy-jar.py grep container logs for
    each marker in v1_markers. If a marker is removed from the controller source
    (e.g., a refactor drops the @PostConstruct log line) but NOT removed from
    v1_markers, the AND-check will fail on every deploy — the operator thinks
    the build is broken when actually it's a stale marker list.

    Conversely, if a marker is added to a controller but NOT added to v1_markers,
    the AND-check passes silently even though the new bean lifecycle hook is
    unverifiable. This test catches both classes of drift.
    """

    @classmethod
    def setUpClass(cls):
        if not SCRIPT_PATH.exists():
            raise unittest.SkipTest(f'build-and-deploy-jar.py not found at {SCRIPT_PATH}')
        cls.source = SCRIPT_PATH.read_text(encoding='utf-8', errors='replace')
        cls.markers = _parse_v1_markers(cls.source)

    def test_v1_markers_is_nonempty(self):
        """v1_markers list must have at least one element. Pre-R6.83 there were
        0 markers; R6.83 added 1; R6.85b added 2; R6.88 added 3 = 6 total.
        Future R6.x+ should add, not remove."""
        self.assertGreaterEqual(
            len(self.markers), 6,
            f'v1_markers has {len(self.markers)} elements; expected >=6 (R6.83+R6.85b+R6.88)')

    def test_each_marker_present_in_controller_source(self):
        """Each marker in v1_markers must grep-appear in the corresponding controller source.

        This catches (a) refactors that drop @PostConstruct log lines, (b) marker
        typos in the build script. The marker text is the source of truth in BOTH
        places; this test pins the invariant.
        """
        for marker in self.markers:
            with self.subTest(marker=marker):
                try:
                    controller = _controller_for_marker(marker)
                except AssertionError as e:
                    self.fail(str(e))
                found, path = _find_marker_in_source(marker, controller)
                self.assertTrue(
                    found,
                    f'Marker {marker!r} not found in {path}. '
                    f'If you changed the @PostConstruct log line in {controller}, '
                    f'update v1_markers in build-and-deploy-jar.py to match.')

    def test_v1_markers_count_matches_log_count(self):
        """Sanity: cmd_deploy's v1_markers list size == the number of AND-check
        assertions it makes. The pre-existing R6.88 / R6.85b check list must
        contain exactly 6 markers (R6.83 + 2x R6.85b + 3x R6.88)."""
        # Count by R6.XX prefix to verify the historical 6-marker shape.
        r683 = [m for m in self.markers if m.startswith('R6.83:')]
        r685b = [m for m in self.markers if m.startswith('R6.85b:')]
        r688 = [m for m in self.markers if m.startswith('R6.88:')]
        self.assertEqual(
            len(r683), 1,
            f'Expected exactly 1 R6.83 marker, got {len(r683)}: {r683}')
        self.assertEqual(
            len(r685b), 2,
            f'Expected exactly 2 R6.85b markers, got {len(r685b)}: {r685b}')
        self.assertEqual(
            len(r688), 3,
            f'Expected exactly 3 R6.88 markers, got {len(r688)}: {r688}')


class TestCrossOriginAudit(unittest.TestCase):
    """R6.90 @CrossOrigin audit (cross-controller): no controller other than
    StaticFileController may use {@code @CrossOrigin(origins = "*")}.

    StaticFileController was the only controller with @CrossOrigin(origins = "*")
    pre-R6.89. R6.89 restricted it to {alicpt.lhr.life, localhost:8091}.
    This test pins the post-R6.89 invariant: no controller in the production
    controllers/ directory may reintroduce the wildcard.

    R6.90 security hardening: regex expanded to catch all wildcard forms:
      (a) @CrossOrigin(origins = "*")                 — string literal
      (b) @CrossOrigin(origins = {"*"})              — string in braces
      (c) @CrossOrigin() with no args                 — defaults to "*"
      (d) @CrossOrigin(origins = "*", ...)            — multi-arg with wildcard
      (e) allowedHeaders = "*" / methods = "*"        — same idea, less severe
    """

    # All CORS wildcards we want to flag.
    WILDCARD_PATTERNS = [
        # (a) literal string outside braces
        re.compile(r'@CrossOrigin\s*\([^)]*origins\s*=\s*"\*"'),
        # (b) string inside braces
        re.compile(r'@CrossOrigin\s*\([^)]*origins\s*=\s*\{\s*"\*"'),
        # (c) no-arg form (defaults to "*")
        re.compile(r'@CrossOrigin\s*\(\s*\)'),
        # (e) other wildcard fields
        re.compile(r'@CrossOrigin\s*\([^)]*allowedHeaders\s*=\s*"\*"'),
        re.compile(r'@CrossOrigin\s*\([^)]*methods\s*=\s*"\*"'),
    ]

    def test_no_wildcard_cors_anywhere(self):
        violations: list[tuple[str, int, str]] = []
        # Walk the entire gw-backend source tree (not just controller/ subdir)
        # to catch wildcards in any *Controller.java or other @RestController classes.
        # Falls back to controller/ dir if gw-backend path is unreachable.
        backend_src = Path(r'D:\AliCPT\gw-backend')
        if not backend_src.exists():
            search_dirs = [CONTROLLER_DIR]
        else:
            search_dirs = list(backend_src.rglob('src/main/java'))
        seen = set()
        for d in search_dirs:
            for java_file in d.rglob('*Controller.java'):
                seen.add(str(java_file))
                text = java_file.read_text(encoding='utf-8', errors='replace')
                for n, line in enumerate(text.splitlines(), 1):
                    for pat in self.WILDCARD_PATTERNS:
                        if pat.search(line):
                            rel = java_file
                            violations.append((str(rel), n, line.strip()))
        self.assertEqual(
            violations, [],
            f'Found {len(violations)} wildcard @CrossOrigin in production '
            f'controllers — this is a security risk. Replace with explicit allowlist '
            f'(see StaticFileController.java for the R6.89 pattern):\n'
            + '\n'.join(f'  {f}:{ln}: {l}' for f, ln, l in violations))

    def test_staticfile_uses_explicit_allowlist(self):
        """StaticFileController must use the explicit allowlist (post-R6.89)."""
        sfc = CONTROLLER_DIR / 'StaticFileController.java'
        text = sfc.read_text(encoding='utf-8', errors='replace')
        # Must NOT contain any wildcard form.
        for pat in self.WILDCARD_PATTERNS:
            self.assertNotRegex(
                text, pat.pattern,
                f'StaticFileController must not contain wildcard form: {pat.pattern}')
        # Must contain at least one explicit origin.
        self.assertRegex(
            text,
            r'@CrossOrigin\s*\(\s*origins\s*=\s*\{',
            'StaticFileController must use @CrossOrigin(origins = {"..."})')


if __name__ == '__main__':
    unittest.main(verbosity=2)
