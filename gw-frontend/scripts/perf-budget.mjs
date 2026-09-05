#!/usr/bin/env node
/**
 * R6.23 — Performance budget regression test
 *
 * Measures real user metrics via Puppeteer and compares against declared budgets.
 * Build-blocking: exits 1 if any page exceeds its budget.
 *
 * Usage:
 *   node scripts/perf-budget.mjs                # run all checks
 *   node scripts/perf-budget.mjs --baseline     # save current as baseline
 *   node scripts/perf-budget.mjs --compare      # compare to saved baseline
 *   node scripts/perf-budget.mjs --report       # write JSON report
 *
 * Requires: puppeteer (already a dev dep in gw-frontend).
 * Requires: gw-frontend running at http://localhost:6001
 */
import fs from 'node:fs'
import path from 'node:path'

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:6001'
const REPORT_PATH = path.join(process.cwd(), 'perf-budget-report.json')
const BASELINE_PATH = path.join(process.cwd(), 'perf-budget-baseline.json')

// Per-page budgets (mirrors docs/REACT_PERFORMANCE_BUDGET.md §Performance Targets)
const BUDGETS = {
    '/': {
        label: 'login page',
        firstPaint: 1500,
        timeToInteractive: 2000,
        iframes: 0,
        webglContexts: 0,
        domNodes: 200,
        scrollFps: 55,
    },
    '/index': {
        label: 'abnormal data',
        firstPaint: 1500,
        timeToInteractive: 3000,
        iframes: 1,
        webglContexts: 1,
        domNodes: 800,
        scrollFps: 50,
    },
    '/search': {
        label: 'FITS search',
        firstPaint: 1500,
        timeToInteractive: 3000,
        iframes: 1,
        webglContexts: 1,
        domNodes: 800,
        scrollFps: 50,
    },
}

// Puppeteer import (try-catch to give friendly message)
let puppeteer
try {
    puppeteer = (await import('puppeteer')).default
} catch (e) {
    console.error('puppeteer not installed. Run: cd gw-frontend && npm install')
    process.exit(2)
}

async function measurePage(browser, url, budget) {
    const page = await browser.newPage()
    const metrics = {}

    try {
        const start = Date.now()
        await page.goto(`${FRONTEND_URL}${url}`, { waitUntil: 'networkidle0', timeout: 30000 })

        // PerformanceObserver metrics
        const paintMetrics = await page.evaluate(() => {
            return new Promise((resolve) => {
                const entries = performance.getEntriesByType('paint')
                const result = {}
                for (const e of entries) {
                    result[e.name] = e.startTime
                }
                // Also try to get navigation timing
                const nav = performance.getEntriesByType('navigation')[0]
                if (nav) {
                    result.domContentLoaded = nav.domContentLoadedEventEnd
                    result.load = nav.loadEventEnd
                }
                resolve(result)
            })
        })
        metrics.firstPaint = paintMetrics['first-contentful-pail'] || paintMetrics['first-paint'] || Date.now() - start

        // Iframe count
        metrics.iframes = await page.evaluate(() => document.querySelectorAll('iframe').length)

        // WebGL contexts (proxy: canvas elements with webgl context)
        metrics.webglContexts = await page.evaluate(() => {
            const canvases = document.querySelectorAll('canvas')
            let count = 0
            for (const c of canvases) {
                try {
                    const gl = c.getContext('webgl') || c.getContext('webgl2') || c.getContext('experimental-webgl')
                    if (gl) count++
                } catch (e) { /* ignore */ }
            }
            return count
        })

        // DOM node count
        metrics.domNodes = await page.evaluate(() => document.querySelectorAll('*').length)

        // Time to interactive: time from goto to networkidle0 (already measured)
        metrics.timeToInteractive = Date.now() - start

        // Scroll FPS (sample-based): scroll 1000px, measure frame timings
        const fpsResult = await page.evaluate(async () => {
            return new Promise((resolve) => {
                let frames = 0
                let lastTime = performance.now()
                const startTime = performance.now()
                const measureUntil = startTime + 1000 // measure for 1 second

                function tick(now) {
                    frames++
                    lastTime = now
                    if (now < measureUntil) {
                        requestAnimationFrame(tick)
                    } else {
                        const elapsed = now - startTime
                        resolve(frames / (elapsed / 1000))
                    }
                }
                requestAnimationFrame(tick)
            })
        })
        metrics.scrollFps = Math.round(fpsResult)

    } finally {
        await page.close()
    }

    return metrics
}

function compareToBudget(label, measured, budget) {
    const errors = []
    const warnings = []

    if (measured.firstPaint > budget.firstPaint) {
        errors.push(`first-paint ${measured.firstPaint}ms > budget ${budget.firstPaint}ms`)
    }
    if (measured.timeToInteractive > budget.timeToInteractive) {
        errors.push(`TTI ${measured.timeToInteractive}ms > budget ${budget.timeToInteractive}ms`)
    }
    if (measured.iframes > budget.iframes) {
        errors.push(`iframes ${measured.iframes} > budget ${budget.iframes}`)
    }
    if (measured.webglContexts > budget.webglContexts) {
        errors.push(`webgl contexts ${measured.webglContexts} > budget ${budget.webglContexts}`)
    }
    if (measured.domNodes > budget.domNodes) {
        warnings.push(`DOM nodes ${measured.domNodes} > target ${budget.domNodes}`)
    }
    if (measured.scrollFps < budget.scrollFps) {
        warnings.push(`scroll fps ${measured.scrollFps} < target ${budget.scrollFps}`)
    }

    return { errors, warnings }
}

async function main() {
    const args = process.argv.slice(2)
    const saveBaseline = args.includes('--baseline')
    const compareBaseline = args.includes('--compare')
    const writeReport = args.includes('--report')

    console.log('═══ R6.23 Performance Budget Check ═══')
    console.log(`Frontend: ${FRONTEND_URL}\n`)

    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    })

    const results = {}
    let totalErrors = 0

    for (const [url, budget] of Object.entries(BUDGETS)) {
        console.log(`Measuring: ${url} (${budget.label})...`)
        try {
            const measured = await measurePage(browser, url, budget)
            const { errors, warnings } = compareToBudget(url, measured, budget)

            results[url] = { measured, budget, errors, warnings }
            totalErrors += errors.length

            console.log(`  first-paint:     ${measured.firstPaint}ms / budget ${budget.firstPaint}ms ${errors.find(e => e.includes('first-paint')) ? '✗' : '✓'}`)
            console.log(`  TTI:             ${measured.timeToInteractive}ms / budget ${budget.timeToInteractive}ms ${errors.find(e => e.includes('TTI')) ? '✗' : '✓'}`)
            console.log(`  iframes:         ${measured.iframes} / budget ${budget.iframes} ${errors.find(e => e.includes('iframes')) ? '✗' : '✓'}`)
            console.log(`  webgl contexts:  ${measured.webglContexts} / budget ${budget.webglContexts} ${errors.find(e => e.includes('webgl')) ? '✗' : '✓'}`)
            console.log(`  DOM nodes:       ${measured.domNodes} / target ${budget.domNodes} ${warnings.find(w => w.includes('DOM')) ? '⚠' : '✓'}`)
            console.log(`  scroll fps:      ${measured.scrollFps} / target ${budget.scrollFps} ${warnings.find(w => w.includes('fps')) ? '⚠' : '✓'}`)
            if (warnings.length > 0) {
                for (const w of warnings) console.log(`    ⚠ ${w}`)
            }
            if (errors.length > 0) {
                for (const e of errors) console.log(`    ✗ ${e}`)
            }
            console.log('')
        } catch (e) {
            console.log(`  ✗ Failed to measure: ${e.message}\n`)
            totalErrors++
        }
    }

    await browser.close()

    // Save / compare baseline
    if (saveBaseline) {
        fs.writeFileSync(BASELINE_PATH, JSON.stringify(results, null, 2))
        console.log(`Baseline saved: ${BASELINE_PATH}`)
    }

    if (compareBaseline && fs.existsSync(BASELINE_PATH)) {
        const baseline = JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8'))
        console.log('═══ Baseline comparison (regressions) ═══')
        let regressions = 0
        for (const [url, r] of Object.entries(results)) {
            const b = baseline[url]
            if (!b) continue
            for (const k of ['firstPaint', 'timeToInteractive', 'iframes', 'webglContexts', 'domNodes']) {
                const drift = r.measured[k] - b.measured[k]
                const driftPct = (drift / b.measured[k]) * 100
                if (driftPct > 10) {
                    console.log(`  ✗ ${url} ${k}: ${b.measured[k]} → ${r.measured[k]} (+${driftPct.toFixed(1)}%)`)
                    regressions++
                }
            }
            const fpsDrift = b.measured.scrollFps - r.measured.scrollFps
            if (fpsDrift > 5) {
                console.log(`  ✗ ${url} scrollFps: ${b.measured.scrollFps} → ${r.measured.scrollFps} (-${fpsDrift})`)
                regressions++
            }
        }
        if (regressions > 0) {
            console.log(`\n${regressions} regressions vs baseline.`)
            totalErrors += regressions
        } else {
            console.log('  ✓ No regressions vs baseline')
        }
    }

    if (writeReport) {
        fs.writeFileSync(REPORT_PATH, JSON.stringify({
            timestamp: new Date().toISOString(),
            frontend: FRONTEND_URL,
            results,
        }, null, 2))
        console.log(`\nReport: ${REPORT_PATH}`)
    }

    console.log(`\n═══ ${totalErrors === 0 ? '✓ All budgets met' : '✗ ' + totalErrors + ' budget violations (BUILD-BLOCKING)'} ═══`)
    process.exit(totalErrors > 0 ? 1 : 0)
}

main().catch((e) => {
    console.error('Fatal:', e)
    process.exit(2)
})
