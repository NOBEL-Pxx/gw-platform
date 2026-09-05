# R6.23 — React Performance Budget

> Hard limits for `gw-frontend` components. Enforced by `scripts/perf-budget.mjs`.

## Why

The `MultiBandDataPanel` 4-round rewrite rot happened partly because there was no objective "good" target. Reviewers said "feels slow" or "looks fine" without measurements. R6.23 makes the budget a build-time gate.

## Hard Limits

| Metric | Limit | Consequence if exceeded |
|--------|-------|-------------------------|
| First Contentful Paint | < 1.5s | Block PR |
| Time to Interactive | < 3.0s | Block PR |
| Total JS bundle | < 800KB gzipped | Warn |
| iframes mounted simultaneously | < 4 | Block PR (WebGL context exhaustion) |
| WebGL contexts active | < 2 | Block PR |
| Component re-render count (per user action) | < 5 | Block PR |
| Scroll FPS (during heavy interaction) | > 50fps | Warn |
| Memory heap (steady state) | < 100MB | Warn |

## Per-Component Budgets

Each component declares its budget in a comment block at the top:

```typescript
/**
 * @perf-budget
 * initial-render: 80ms
 * re-render: 12ms
 * dom-nodes: 200
 * iframes: 0
 * webgl: 0
 * list-size: 19
 * virtualization: lazy-img-only  // <-- no react-window needed
 */
function MyComponent(props) { ... }
```

`scripts/perf-budget.mjs` reads these comments and verifies against actual measurements.

## Forbidden Patterns

These trigger `scripts/component-lint.mjs` (build-blocking):

```javascript
// ❌ BAD: useMemo on primitive math
const sum = useMemo(() => a + b, [a, b])

// ✅ GOOD: plain expression
const sum = a + b

// ❌ BAD: useCallback wrapping a single arg
const handleClick = useCallback(() => onClick(id), [id, onClick])

// ✅ GOOD: pass id through, let parent decide
<div onClick={() => onClick(id)} />

// ❌ BAD: 19 new Image() pre-fetches for 19-item list
entries.forEach((e) => { const img = new Image(); img.src = url })

// ✅ GOOD: <img loading="lazy">
{entries.map((e) => <img key={e.id} loading="lazy" src={url} />)}
```

## When `useMemo` / `useCallback` ARE justified

- `useMemo`: derived data with non-trivial computation (>1ms). Example: filter+map+sort on 1000+ items.
- `useCallback`: function passed to a memoized child component AND child uses `React.memo` AND props equality is shallow. Example: row in a virtualized list.

If you can't articulate "X is heavy and Y is the child that needs memo", don't add the hook.

## Measurement Tooling

```bash
# Run perf-budget check (npm script)
npm run perf-budget

# Or directly:
node scripts/perf-budget.mjs

# Outputs:
#   [OK] MultiBandDataPanel: initial 87ms < 100ms ✓
#   [OK] MultiBandDataPanel: re-render 11ms < 16ms ✓
#   [FAIL] ImageList: initial 156ms > 100ms ✗
```

The script reads Chrome DevTools Performance recordings (via `puppeteer`) and Lighthouse budgets, compares against declarations.

## CI Integration

In `scripts/ci/deploy.sh` test stage:

```bash
# Run perf budget BEFORE deploying
if ! node scripts/perf-budget.mjs; then
    red "Performance budget violated. Aborting deploy."
    exit 3
fi
```

A failing perf budget is a **deploy blocker**. No more "I'll optimize later" — later is now.

## Performance Targets by Page

| Page | First Paint | TTI | iframes | FPS |
|------|------------|-----|---------|-----|
| `/` login | 1.0s | 2.0s | 0 | 60 |
| `/index` abnormal data | 1.5s | 3.0s | 1 (Firefly) | 50 |
| `/search` FITS search | 1.5s | 3.0s | 1 (Firefly) | 50 |
| `/login` AI assistant | 1.0s | 2.0s | 0 | 60 |

Targets aligned with R6.18-R6.21 measurements (Abnormal Data ms-level tile switching).
