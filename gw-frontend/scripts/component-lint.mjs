#!/usr/bin/env node
/**
 * R6.23 — Component complexity lint (build-blocking)
 *
 * Usage:
 *   node scripts/component-lint.mjs                    # scan src/
 *   node scripts/component-lint.mjs src/path/file.tsx  # scan specific file
 *   node scripts/component-lint.mjs --report           # write report JSON
 *
 * Exit codes:
 *   0 = pass
 *   1 = violations (build-blocking)
 *   2 = script error
 */
import fs from 'node:fs'
import path from 'node:path'

const ROOT = process.cwd()
const SRC_DIR = path.join(ROOT, 'src')
const REPORT_PATH = path.join(ROOT, 'component-lint-report.json')

// Limits (mirror docs/COMPONENT_DESIGN_REVIEW.md §2)
const LIMITS = {
    lines: 300,
    useState: 5,
    useMemo: 3,
    useCallback: 3,
    useEffect: 4,
    newImage: 5,
}

const violations = []
const warnings = []
const passed = []

function scanFile(filepath) {
    const content = fs.readFileSync(filepath, 'utf8')
    const lines = content.split('\n')

    // Skip non-component files (types, utils, constants)
    if (filepath.endsWith('.d.ts') || filepath.includes('/types/') || filepath.includes('/util/')) {
        return
    }

    const rel = path.relative(ROOT, filepath)

    // Rule 1: File size
    if (lines.length > LIMITS.lines) {
        violations.push({
            file: rel,
            rule: 'file-size',
            message: `File is ${lines.length} lines (limit ${LIMITS.lines}). Split into sub-components.`,
            value: lines.length,
            limit: LIMITS.lines,
        })
    } else {
        passed.push({ file: rel, rule: 'file-size', value: lines.length })
    }

    // Rule 2-5: Hook counts
    const hookCounts = {
        useState: (content.match(/\buseState\s*\(/g) || []).length,
        useMemo: (content.match(/\buseMemo\s*\(/g) || []).length,
        useCallback: (content.match(/\buseCallback\s*\(/g) || []).length,
        useEffect: (content.match(/\buseEffect\s*\(/g) || []).length,
    }

    for (const [hook, count] of Object.entries(hookCounts)) {
        const limit = LIMITS[hook]
        if (count > limit) {
            violations.push({
                file: rel,
                rule: `hook-count-${hook}`,
                message: `${count} \`${hook}\``,
                value: count,
                limit,
            })
        } else {
            passed.push({ file: rel, rule: `hook-count-${hook}`, value: count })
        }
    }

    // Rule 6: new Image() pre-fetch count
    const newImageCount = (content.match(/\bnew\s+Image\s*\(/g) || []).length
    if (newImageCount > LIMITS.newImage) {
        violations.push({
            file: rel,
            rule: 'new-image-prefetch',
            message: `${newImageCount} \`new Image()\` pre-fetches (limit ${LIMITS.newImage}). Use \`<img loading="lazy">\` instead.`,
            value: newImageCount,
            limit: LIMITS.newImage,
        })
    } else if (newImageCount > 0) {
        passed.push({ file: rel, rule: 'new-image-prefetch', value: newImageCount })
    }

    // Rule 7: void <ident>Unused (the explicit anti-pattern)
    const unusedPattern = /\bvoid\s+([a-zA-Z_$][\w$]*Unused)\b/g
    const unusedMatches = [...content.matchAll(unusedPattern)]
    if (unusedMatches.length > 0) {
        violations.push({
            file: rel,
            rule: 'void-unused',
            message: `Found \`void ${unusedMatches[0][1]}\` pattern. Delete the unused variable entirely — it's masking a real refactor need.`,
            value: unusedMatches.length,
            limit: 0,
        })
    }

    // Rule 8 (warning only): useMemo on primitive math
    const primMathPattern = /useMemo\s*\(\s*\(\s*\)\s*=>\s*([\w.]+)\s*([+\-*/%])\s*[\w.]+\s*,/g
    const primMathMatches = [...content.matchAll(primMathPattern)]
    if (primMathMatches.length > 0) {
        warnings.push({
            file: rel,
            rule: 'premature-usememo',
            message: `${primMathMatches.length} \`useMemo(() => a + b)\` patterns. Inline these — useMemo is for non-trivial derived data only.`,
        })
    }
}

function walkDir(dir) {
    const files = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            if (entry.name === 'node_modules' || entry.name === 'dist') continue
            files.push(...walkDir(full))
        } else if (/\.(ts|tsx)$/.test(entry.name)) {
            files.push(full)
        }
    }
    return files
}

function main() {
    const args = process.argv.slice(2)
    const writeReport = args.includes('--report')

    let files
    if (args.filter((a) => !a.startsWith('--')).length > 0) {
        files = args.filter((a) => !a.startsWith('--')).map((a) => path.resolve(a))
    } else {
        files = walkDir(SRC_DIR)
    }

    if (files.length === 0) {
        console.error('No files to scan. Run from project root, or pass file paths.')
        process.exit(2)
    }

    console.log(`Scanning ${files.length} files...\n`)
    for (const f of files) scanFile(f)

    // Report
    console.log('═══ Component Complexity Lint (R6.23) ═══')
    console.log(`Limits: lines<${LIMITS.lines}, useState<${LIMITS.useState}, useMemo<${LIMITS.useMemo}, useCallback<${LIMITS.useCallback}, useEffect<${LIMITS.useEffect}, newImage<${LIMITS.newImage}\n`)

    if (violations.length === 0) {
        console.log(`✓ ${passed.length} checks passed`)
    } else {
        console.log(`✗ ${violations.length} VIOLATIONS (build-blocking):`)
        for (const v of violations) {
            console.log(`  [${v.rule}] ${v.file}`)
            console.log(`    ${v.message}`)
            console.log(`    value=${v.value} limit=${v.limit}\n`)
        }
    }

    if (warnings.length > 0) {
        console.log(`\n⚠ ${warnings.length} WARNINGS:`)
        for (const w of warnings) {
            console.log(`  [${w.rule}] ${w.file}: ${w.message}`)
        }
    }

    if (writeReport) {
        fs.writeFileSync(REPORT_PATH, JSON.stringify({
            timestamp: new Date().toISOString(),
            limits: LIMITS,
            violations,
            warnings,
            passed,
        }, null, 2))
        console.log(`\nReport written: ${REPORT_PATH}`)
    }

    process.exit(violations.length > 0 ? 1 : 0)
}

main()
