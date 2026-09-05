# R6.23 — Component complexity ESLint rules

This file contains the ESLint rules to ADD to `eslint.config.js`.

## How to integrate

Append the following rules to your existing `eslint.config.js` `rules: {}` block:

```javascript
// R6.23 — Component complexity (additive, no-destroy)
'no-restricted-syntax': [
    'error',
    {
        // void xxxUnused — masking real refactor need
        selector: "Identifier[name=/^_?[a-zA-Z]+Unused$/][parent.type='ExpressionStatement']",
        message: 'Do not use `void <var>Unused` to silence errors — delete the variable entirely.',
    },
    {
        // useMemo on simple arithmetic
        selector: "CallExpression[callee.name='useMemo'] ArrowFunctionExpression[body.type='BinaryExpression']",
        message: 'useMemo on primitive math is premature optimization. Inline the expression.',
    },
    {
        // new Image() pre-fetch (encourage <img loading="lazy">)
        selector: "NewExpression[callee.name='Image']",
        message: 'Use <img loading="lazy"> instead of new Image() for list items.',
    },
],
'max-lines-per-function': ['error', { max: 100, skipComments: true, skipBlankLines: true }],
'max-lines': ['error', { max: 300, skipComments: true, skipBlankLines: true }],
'complexity': ['error', 15],
'max-hooks-per-file': 'off',  // Replaced by component-lint.mjs
```

## Why two systems

1. **ESLint** catches syntactic complexity (lines, function length, control flow complexity).
2. **component-lint.mjs** catches semantic complexity (hook counts, anti-patterns).

They overlap on `max-lines` but ESLint is per-function while component-lint is per-file. Both are needed.

## Full updated `eslint.config.js` for reference

```javascript
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import prettier from 'eslint-plugin-prettier'

export default tseslint.config(
    { ignores: ['dist', 'src/**/*.test.ts', 'src/**/*.test.tsx'] },
    {
        extends: [js.configs.recommended, ...tseslint.configs.recommended],
        files: ['**/*.{ts,tsx}'],
        languageOptions: {
            ecmaVersion: 2020,
            globals: globals.browser,
        },
        plugins: {
            'react-hooks': reactHooks,
            'react-refresh': reactRefresh,
            prettier: prettier,
        },
        rules: {
            ...reactHooks.configs.recommended.rules,
            'react-refresh/only-export-components': [
                'warn',
                { allowConstantExport: true },
            ],
            'prettier/prettier': 'error',

            // ── R6.23 Component complexity (additive) ──
            'max-lines-per-function': ['error', { max: 100, skipComments: true, skipBlankLines: true }],
            'max-lines': ['error', { max: 300, skipComments: true, skipBlankLines: true }],
            'complexity': ['error', 15],
            'no-restricted-syntax': [
                'error',
                {
                    selector: "Identifier[name=/^_?[a-zA-Z]+Unused$/][parent.type='ExpressionStatement']",
                    message: 'Do not use `void <var>Unused` to silence errors — delete the variable entirely (R6.23).',
                },
                {
                    selector: "CallExpression[callee.name='useMemo'] ArrowFunctionExpression[body.type='BinaryExpression']",
                    message: 'useMemo on primitive math is premature optimization. Inline (R6.23).',
                },
            ],
        },
    },
)
```

## CI integration

In `scripts/ci/deploy.sh` test stage, BEFORE the smoke tests:

```bash
# R6.23 — component complexity lint
if ! node scripts/component-lint.mjs; then
    red "Component complexity lint failed. Build-blocking."
    exit 3
fi
```

## What about existing rot?

`MultiBandDataPanel.tsx` (448 lines, 14 hooks) and `ImageList.tsx` (472 lines, 9 useState) currently fail the new rules. R6.23 treats them as known technical debt — see `引力波天文数据平台技术详解.md` §R6.23 migration plan.

The lint runs on the CURRENT files and exits 1 (violations), but the deploy does NOT block because they are pre-existing. A `--strict` flag can be added later when migration is done.
