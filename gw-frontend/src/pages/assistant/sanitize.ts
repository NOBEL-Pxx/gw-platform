/**
 * v4.36: XSS Sanitization Utility (Fix #3)
 * Escapes HTML entities in LLM-rendered content to prevent XSS injection.
 * Also handles safe markdown-like formatting for code blocks and inline code.
 */

const ENTITY_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#x27;',
  '/': '&#x2F;',
  '`': '&#x60;',
}

/** Escape all HTML entities — use for any user or LLM-generated content before rendering */
export function escapeHtml(str: string): string {
  return str.replace(/[&<>"'/`]/g, (char) => ENTITY_MAP[char] || char)
}

/**
 * Sanitize and format AI response text for safe rendering.
 * - Escapes HTML entities
 * - Detects and wraps code blocks in safe <pre><code> tags
 * - Detects inline code in safe <code> tags
 * - Preserves line breaks
 */
export function sanitizeAndFormat(text: string): string {
  // First pass: extract code blocks to protect them
  const codeBlocks: string[] = []
  let processed = text.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_match, _lang, code) => {
      const idx = codeBlocks.length
      codeBlocks.push(escapeHtml(code))
      return `__CODE_BLOCK_${idx}__`
    },
  )

  // Process inline code
  processed = processed.replace(/`([^`]+)`/g, (_match, code) => {
    const idx = codeBlocks.length
    codeBlocks.push(escapeHtml(code))
    return `__INLINE_CODE_${idx}__`
  })

  // Escape remaining HTML
  processed = escapeHtml(processed)

  // Restore code blocks with safe HTML
  processed = processed.replace(/__CODE_BLOCK_(\d+)__/g, (_m, idx) => {
    return `<pre class="code-block"><code>${codeBlocks[parseInt(idx)]}</code></pre>`
  })
  processed = processed.replace(/__INLINE_CODE_(\d+)__/g, (_m, idx) => {
    return `<code class="inline-code">${codeBlocks[parseInt(idx)]}</code>`
  })

  // Convert newlines to <br> for safe display (since we use dangerouslySetInnerHTML)
  // Actually, let CSS handle whitespace: pre-wrap instead
  return processed
}

/**
 * Lightweight sanitize for plain text — just escape HTML.
 * Use for user messages and simple AI responses.
 */
export function sanitizeText(text: string): string {
  return escapeHtml(text)
}

/**
 * Detect potential XSS payloads in a string.
 * Returns true if suspicious patterns are found.
 * Logs a warning but doesn't block — sanitization handles the safety.
 */
export function detectXssAttempt(text: string): boolean {
  const patterns = [
    /<script[\s>]/i,
    /javascript\s*:/i,
    /on\w+\s*=\s*["']/i,
    /<iframe[\s>]/i,
    /<object[\s>]/i,
    /<embed[\s>]/i,
    /<link[\s>]/i,
    /<meta[\s>]/i,
    /expression\s*\(/i,
    /url\s*\(\s*data\s*:/i,
  ]
  return patterns.some((p) => p.test(text))
}
