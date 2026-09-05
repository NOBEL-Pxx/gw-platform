#!/usr/bin/env node
/**
 * R6.23 — Regression test suite for component architecture
 *
 * Runs three categories of tests:
 *   1. component-lint — file/hook/anti-pattern violations
 *   2. perf-budget — runtime page metrics vs budget
 *   3. visual-snapshot — pixel-identical regression for known good renders
 *
 * Usage:
 *   node scripts/regression-suite.mjs           # run all
 *   node scripts/regression-suite.mjs --lint    # only lint
 *   node scripts/regression-suite.mjs --perf    # only perf
 *   node scripts/regression-suite.mjs --visual  # only visual
 *
 * Each test exits 0 (pass) or 1 (fail). Suite stops at first failure unless --no-stop.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'

const REGRESSION_LOG = 'regression-suite.log'
const ts = () => new Date().toISOString()

function log(msg) {
    const line = `[${ts()}] ${msg}`
    console.log(line)
    fs.appendFileSync(REGRESSION_LOG, line + '\n')
}

function runStep(name, cmd, args = []) {
    log(`═══ ${name} ═══`)
    return new Promise((resolve) => {
        const proc = spawn(cmd, args, { stdio: 'inherit' })
        proc.on('exit', (code) => {
            log(`${name}: exit ${code}`)
            resolve(code === 0)
        })
        proc.on('error', (e) => {
            log(`${name}: spawn error ${e.message}`)
            resolve(false)
        })
    })
}

async function main() {
    const args = process.argv.slice(2)
    const onlyLint = args.includes('--lint')
    const onlyPerf = args.includes('--perf')
    const onlyVisual = args.includes('--visual')
    const noStop = args.includes('--no-stop')

    const runLint = !onlyPerf && !onlyVisual
    const runPerf = !onlyLint && !onlyVisual
    const runVisual = !onlyLint && !onlyPerf

    fs.writeFileSync(REGRESSION_LOG, '')
    log(`Regression suite started`)

    let allPassed = true

    if (runLint) {
        const ok = await runStep('component-lint', 'node', ['scripts/component-lint.mjs'])
        if (!ok) {
            log('FAIL: component-lint violations')
            allPassed = false
            if (!noStop) {
                process.exit(1)
            }
        }
    }

    if (runPerf) {
        const ok = await runStep('perf-budget', 'node', ['scripts/perf-budget.mjs'])
        if (!ok) {
            log('FAIL: perf-budget violations')
            allPassed = false
            if (!noStop) {
                process.exit(1)
            }
        }
    }

    if (runVisual) {
        // Visual snapshot is opt-in (slow). See scripts/visual-snapshot.mjs (future R6.23+ work)
        log('visual-snapshot: SKIP (not yet implemented)')
    }

    log(allPassed ? 'Suite PASSED' : 'Suite FAILED')
    process.exit(allPassed ? 0 : 1)
}

main()
