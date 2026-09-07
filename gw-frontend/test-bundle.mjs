import { Window } from 'happy-dom';
import { readFileSync } from 'fs';
import path from 'path';

const win = new Window({ url: 'http://localhost/index' });

// Set up document body
win.document.body.innerHTML = '<div id="root"></div>';

// Patch console to capture errors
const errors = [];
const origErr = win.console.error;
win.console.error = (...args) => {
  errors.push(args.map(a => a?.message || a?.toString() || String(a)).join(' '));
  origErr(...args);
};

const buildDir = 'D:/AliCPT/gw-frontend/build/assets';

// Stub fetch via window
win.fetch = async () => ({
  ok: true, status: 200, json: async () => ({}), text: async () => '',
  headers: new Map(),
});

const chunks = [
  'rolldown-runtime-B0Z9INg1.js',
  'vendor-DxBftEqG.js',
  'service-BkfQKJNP.js',
  'CommentsTrigger-BaoCAu19.js',
  'index-DG_KjhMF.js',
];

for (const chunk of chunks) {
  try {
    const code = readFileSync(path.join(buildDir, chunk), 'utf-8');
    // Strip imports (happy-dom script tag doesn't support ES modules natively in this context)
    // Use Function eval inside window context
    const stripped = code.replace(/^import\s.*?;\s*$/gm, '');
    win.eval(stripped);
    console.log(`[OK] loaded ${chunk}`);
  } catch (e) {
    console.log(`[FAIL] ${chunk}: ${e.message}`);
  }
}

await new Promise(r => setTimeout(r, 3000));

console.log('\n=== ERRORS from bundle ===');
errors.slice(0, 10).forEach((e, i) => console.log(`[${i}] ${e.substring(0, 500)}`));
