# R6.23 — Component Design Review Template

> **Mandatory** before creating or rewriting any React component in `gw-frontend/src/`.
> Created 2026-09-01 in response to 4-round `MultiBandDataPanel.tsx` rewrite rot.

## Why this exists

`MultiBandDataPanel.tsx` went through 4 rewrites (R6 → R6.1 → R6.1-FINAL → R6.2) and ended up **448 lines, 14 hooks, `void _imageUrlsUnused` suppressing TS errors**. `ImageList.tsx` is now 472 lines with 9 useState. Each round introduced new regressions (WebGL exhaustion, scroll broken, Aladin black). This template blocks future rot.

## 1. State Audit (mandatory)

Fill this table BEFORE writing code.

| State variable | Type | Source | Update frequency | Why can't it be derived? |
|----------------|------|--------|-------------------|---------------------------|
| (e.g. `selectedId`) | `string \| null` | user click | per click | not derivable from URL alone |
| ... | | | | |

**Rule**: If a state variable can be derived from props/URL/other state via `useMemo`, **don't add useState**. Add a column "why can't it be derived" — empty = redesign.

## 2. Hook Budget (mandatory)

**Hard limits** (enforced by `scripts/component-lint.mjs`):

| Hook | Hard limit | When exceeded |
|------|-----------|---------------|
| `useState` total | **5** | Must split into sub-components |
| `useMemo` total | **3** | Most should be plain expressions |
| `useCallback` total | **3** | Most should be inline |
| `useEffect` total | **4** | Each effect = a separate concern |
| File lines | **300** | Split or extract hooks to custom hooks |

If you need more, **the component is doing too much**. Extract to `<SubComponentA>`, `<SubComponentB>`, or a custom hook `useWhatever()`.

## 3. Props Interface (mandatory)

```typescript
interface MyComponentProps {
  // Required
  data: T[]
  onSelect: (id: string) => void

  // Optional with defaults
  size?: 'sm' | 'md' | 'lg'  // default 'md'
  variant?: 'primary' | 'ghost'

  // NEVER include:
  // - Internal state setters
  // - Refs to DOM elements (use forwardRef sparingly)
  // - Callbacks that wrap props 1:1
}
```

## 4. Performance Budget (mandatory)

For each component, declare:

| Metric | Budget | Measurement |
|--------|--------|-------------|
| Initial render time | < 100ms | React DevTools Profiler |
| Re-render time | < 16ms (60fps) | Profiler |
| Memory (heap) | < 5MB | Chrome DevTools Memory |
| DOM nodes | < 500 | DevTools Elements panel |
| iframes mounted | < 2 | `document.querySelectorAll('iframe').length` |
| WebGL contexts | < 2 | `gl.getParameter(gl.MAX_CONTEXT_ID)` check |

**For lists**: native `loading='lazy'` on images. **Never** hand-write IntersectionObserver unless lazy alone fails (rare).

## 5. Anti-Patterns (auto-blocked)

The linter will FAIL the build if it sees:

- ❌ `void <ident>Unused` — variable kept just to silence TS6133
- ❌ `useMemo(() => x + 1, [x])` — primitive math wrapped in useMemo
- ❌ `useCallback(() => fn(arg), [fn])` — wraps a single arg
- ❌ More than 5 `useState` in one file
- ❌ File > 300 lines
- ❌ More than 19 `new Image()` pre-fetches (use `<img loading='lazy'>`)

## 6. Code Smell Triggers (mandatory fix)

| Smell | Action |
|-------|--------|
| `void xxxUnused` | Delete `xxx` entirely |
| `useMemo(() => a + b)` | Remove useMemo, inline |
| `useEffect` triggers `useState` setter for derived | Refactor to `useMemo` |
| `new Image()` > 5 in same component | Use `<img loading='lazy'>` |
| Conditional `useState` (inside `if`) | Move to top level or extract hook |
| Props > 8 fields | Compose from multiple interfaces |

## 7. Review Checklist (filled by reviewer)

- [ ] State Audit table complete; no derivable useState
- [ ] Hook counts under limits
- [ ] File under 300 lines
- [ ] Props interface minimal
- [ ] No `void xxxUnused` anti-patterns
- [ ] No premature `useMemo`/`useCallback`
- [ ] List virtualization decision documented (or use `loading='lazy'` + justify)
- [ ] Performance budget reasonable for list size
- [ ] Regression test added (see scripts/perf-budget.mjs)
- [ ] PR description links to this filled template

## 8. Example: MultiBandDataPanel.tsx regression analysis

The 4-round rewrite of `MultiBandDataPanel.tsx` violates **6** of these rules:
1. ❌ 448 lines (limit: 300)
2. ❌ 14 hooks total (limit: 5 useState, 3 useMemo, 3 useCallback, 4 useEffect — sum 15 limit, but per-type)
3. ❌ `void _imageUrlsUnused` exists in repo
4. ❌ 19 `new Image()` pre-fetches for 19-item list
5. ❌ Premature `useCallback` everywhere
7. ❌ No design review was done before each rewrite

**Fix**: Extract `<BandTile>`, `<ViewerStack>`, `<PreloadManager>` as separate files. Keep `MultiBandDataPanel.tsx` under 300 lines as composition only.

## 9. Migration plan for existing rot

| File | Current | Action | Priority |
|------|---------|--------|----------|
| `MultiBandDataPanel.tsx` | 448 lines / 14 hooks | Split into 3-4 subcomponents | High |
| `ImageList.tsx` | 472 lines / 9 useState | Extract custom hooks, split viewers | High |
| `FireflyViewer.tsx` | 228 lines | OK, but check for premature useCallback | Low |
| `Comments.tsx` | 201 lines | OK, under limits | None |

Each split should land as ONE PR with:
- The new sub-component files
- Updated parent file (under 300 lines)
- The design review template filled
- Regression test snapshot

**No more "4 rounds in a week"**. If you need to rewrite, the template was skipped.
