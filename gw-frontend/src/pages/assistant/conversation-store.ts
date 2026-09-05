/**
 * v4.36: Conversation Persistence & Management (Fix #2, #4)
 *
 * Features:
 * - localStorage save/restore of conversations
 * - Multiple named conversations
 * - Export as Markdown
 * - Search within conversations
 * - Auto-save after each message
 */

export interface ConvMessage {
  id: string
  role: 'a' | 'u'
  text: string
  model?: string
  timestamp: number
}

export interface Conversation {
  id: string
  title: string
  messages: ConvMessage[]
  createdAt: number
  updatedAt: number
  messageCount: number
}

function getUserId(): string {
  try {
    const token = localStorage.getItem('gw_auth_token')
    if (!token) return 'guest'
    // Parse JWT payload to get userId
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.userId || payload.sub || 'guest'
  } catch {
    return 'guest'
  }
}

function getStorageKey(): string {
  return 'gw-conversations-' + getUserId()
}

function getActiveConvKey(): string {
  return 'gw-active-conversation-' + getUserId()
}
const MAX_CONVERSATIONS = 20
const MAX_MESSAGES_PER_CONV = 200

/** Generate a unique conversation ID */
function genConvId(): string {
  return (
    'conv-' +
    Date.now().toString(36) +
    '-' +
    Math.random().toString(36).slice(2, 8)
  )
}

/** Generate a title from first user message */
export function titleFromMessage(text: string): string {
  const cleaned = text.replace(/[\n\r]/g, ' ').trim()
  return cleaned.length > 50 ? cleaned.slice(0, 47) + '...' : cleaned
}

/** Load all saved conversations from localStorage */
export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(getStorageKey())
    if (!raw) return []
    const data = JSON.parse(raw)
    if (!Array.isArray(data)) return []
    return data.slice(0, MAX_CONVERSATIONS)
  } catch {
    return []
  }
}

/** Save conversations to localStorage */
function saveConversations(convs: Conversation[]): void {
  try {
    // Keep only the most recent MAX_CONVERSATIONS
    const trimmed = convs.slice(0, MAX_CONVERSATIONS)
    localStorage.setItem(getStorageKey(), JSON.stringify(trimmed))
  } catch (e) {
    console.warn('[ConversationStore] Failed to save:', e)
  }
}

/** Get the active conversation ID */
export function getActiveConvId(): string | null {
  try {
    return localStorage.getItem(getActiveConvKey())
  } catch {
    return null
  }
}

/** Set the active conversation ID */
export function setActiveConvId(id: string | null): void {
  try {
    if (id) {
      localStorage.setItem(getActiveConvKey(), id)
    } else {
      localStorage.removeItem(getActiveConvKey())
    }
  } catch {
    /* ignore */
  }
}

/** Create a new conversation */
export function createConversation(title?: string): Conversation {
  const conv: Conversation = {
    id: genConvId(),
    title: title || 'New Conversation',
    messages: [
      {
        id: 'welcome-' + Date.now(),
        role: 'a',
        text: '/**\n * GravitationalWave AI Assistant v4.36\n * Powered by DeepSeek-V4\n *\n * Quick commands:\n *   DSS2     — Show DSS2 observations\n *   Errors   — List error reports\n *   Detail   — Show error detail\n *   Pipeline — NVSS pipeline status\n */',
        timestamp: Date.now(),
      },
    ],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messageCount: 1,
  }
  return conv
}

/** Save a conversation (create or update) */
export function saveConversation(conv: Conversation): void {
  const convs = loadConversations()
  const idx = convs.findIndex((c) => c.id === conv.id)
  const updated: Conversation = {
    ...conv,
    updatedAt: Date.now(),
    messageCount: conv.messages.length,
  }
  // Limit messages
  if (updated.messages.length > MAX_MESSAGES_PER_CONV) {
    updated.messages = updated.messages.slice(-MAX_MESSAGES_PER_CONV)
  }
  if (idx >= 0) {
    convs[idx] = updated
  } else {
    convs.unshift(updated)
  }
  saveConversations(convs)
  setActiveConvId(updated.id)
}

/** Delete a conversation by ID */
export function deleteConversation(id: string): void {
  const convs = loadConversations().filter((c) => c.id !== id)
  saveConversations(convs)
  if (getActiveConvId() === id) {
    setActiveConvId(null)
  }
}

/** Load the active conversation, or create a new one */
export function loadActiveConversation(): Conversation {
  const activeId = getActiveConvId()
  if (activeId) {
    const convs = loadConversations()
    const found = convs.find((c) => c.id === activeId)
    if (found) return found
  }
  return createConversation()
}

/** Search messages across all conversations */
export function searchConversations(
  query: string,
): Array<{ conv: Conversation; matches: ConvMessage[] }> {
  const convs = loadConversations()
  const lower = query.toLowerCase()
  const results: Array<{ conv: Conversation; matches: ConvMessage[] }> = []

  for (const conv of convs) {
    const matches = conv.messages.filter((m) =>
      m.text.toLowerCase().includes(lower),
    )
    if (matches.length > 0) {
      results.push({ conv, matches })
    }
  }
  return results
}

/** Export a conversation as Markdown string */
export function exportAsMarkdown(conv: Conversation): string {
  const lines: string[] = [
    `# ${conv.title}`,
    `> Created: ${new Date(conv.createdAt).toISOString()}`,
    `> Updated: ${new Date(conv.updatedAt).toISOString()}`,
    `> Messages: ${conv.messageCount}`,
    '',
    '---',
    '',
  ]

  for (const msg of conv.messages) {
    const role = msg.role === 'a' ? '**AI**' : '**User**'
    const time = new Date(msg.timestamp).toLocaleString()
    lines.push(`### ${role} — ${time}`)
    lines.push('')
    lines.push(msg.text)
    lines.push('')
  }

  return lines.join('\n')
}

/** Trigger a file download in the browser */
export function downloadFile(
  content: string,
  filename: string,
  mimeType: string = 'text/markdown',
): void {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** Export conversation as Markdown and trigger download */
export function exportConversation(conv: Conversation): void {
  const md = exportAsMarkdown(conv)
  const filename = `gw-conversation-${conv.id.slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.md`
  downloadFile(md, filename)
}

/** Get storage usage stats */
export function getStorageStats(): {
  conversationCount: number
  totalMessages: number
  estimatedSizeKB: number
} {
  const convs = loadConversations()
  const totalMessages = convs.reduce((sum, c) => sum + c.messages.length, 0)
  const raw = localStorage.getItem(getStorageKey()) || ''
  const estimatedSizeKB = Math.round((raw.length * 2) / 1024) // UTF-16 → bytes → KB
  return {
    conversationCount: convs.length,
    totalMessages,
    estimatedSizeKB,
  }
}
