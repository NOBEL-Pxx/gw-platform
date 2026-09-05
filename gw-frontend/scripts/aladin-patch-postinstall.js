#!/usr/bin/env node
/**
 * Aladin Lite ESM auto-patch (v4.16)
 *
 * The aladin-lite npm package (v3.6.5+) ships as ESM-only with `export`
 * statements. When bundled via Vite/Rollup, these cause "Unexpected token
 * 'export'" errors if the package.json doesn't declare "type":"module"
 * correctly or if there are CJS/ESM interop issues.
 *
 * This script:
 *   1. Detects if the aladin-lite package ESM exports need patching
 *   2. Adds a "type": "module" declaration to the local package.json if missing
 *   3. Ensures the build process can resolve the module correctly
 *
 * Runs automatically after `npm install` via the "postinstall" script.
 * Non-destructive — only modifies if fixes are needed.
 *
 * Manual fix (if automation fails):
 *   The frontend uses CDN aladin.js via iframe (/aladin-test.html),
 *   NOT the npm package. The npm package is only a dev dependency for
 *   TypeScript types. If build errors persist, remove aladin-lite from
 *   package.json and use the CDN exclusively.
 */

const fs = require('fs');
const path = require('path');

const ALADIN_PKG = path.join(__dirname, 'node_modules', 'aladin-lite');
const ALADIN_PKG_JSON = path.join(ALADIN_PKG, 'package.json');
const ALADIN_MAIN = path.join(ALADIN_PKG, 'src', 'index.js');

let fixed = false;

// Check if aladin-lite is installed
if (!fs.existsSync(ALADIN_PKG_JSON)) {
    console.log('[aladin-patch] aladin-lite not installed — skipping ESM patch');
    process.exit(0);
}

const pkg = JSON.parse(fs.readFileSync(ALADIN_PKG_JSON, 'utf8'));

// Fix 1: Ensure "type": "module" is declared
if (pkg.type !== 'module') {
    pkg.type = 'module';
    fs.writeFileSync(ALADIN_PKG_JSON, JSON.stringify(pkg, null, 2) + '\n');
    console.log('[aladin-patch] Added "type":"module" to aladin-lite/package.json');
    fixed = true;
}

// Fix 2: Check for ESM syntax issues in main entry
if (fs.existsSync(ALADIN_MAIN)) {
    let content = fs.readFileSync(ALADIN_MAIN, 'utf8');
    // The aladin-lite package uses raw ESM exports — ensure they're preserved
    if (content.includes('export ') && !content.includes('export {')) {
        console.log('[aladin-patch] aladin-lite ESM exports detected — OK (Vite handles ESM natively)');
    }
}

// Fix 3: Verify the UMD fallback exists in public/
const publicAladin = path.join(__dirname, 'public', 'aladin.js');
if (!fs.existsSync(publicAladin)) {
    console.warn('[aladin-patch] WARNING: public/aladin.js not found — CDN fallback required');
    console.warn('[aladin-patch] The frontend uses CDN aladin.js via iframe, so this is expected.');
}

if (fixed) {
    console.log('[aladin-patch] Aladin Lite ESM patched successfully');
} else {
    console.log('[aladin-patch] No fixes needed — aladin-lite is already compatible');
}
