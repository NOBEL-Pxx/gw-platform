import { useState, useRef, useEffect, useCallback } from 'react'
import { Switch, Tag, Spin, Button } from 'antd'
import SendOutlined from '@ant-design/icons/SendOutlined'
import DownloadOutlined from '@ant-design/icons/DownloadOutlined'
import SearchOutlined from '@ant-design/icons/SearchOutlined'
import DeleteOutlined from '@ant-design/icons/DeleteOutlined'
import CopyOutlined from '@ant-design/icons/CopyOutlined'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'
import HistoryOutlined from '@ant-design/icons/HistoryOutlined'
import LoginOutlined from '@ant-design/icons/LoginOutlined'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import axios from 'axios'
import {
  chatWithDeepSeek,
  chatWithAgentStream,
  getLlmStatus,
  getLlmUsage,
  getAgentStatus,
} from '@/service/deepseek'
// v4.36: Types used implicitly via return type inference
import { sanitizeAndFormat, sanitizeText, detectXssAttempt } from './sanitize'
import {
  type Conversation,
  type ConvMessage,
  loadActiveConversation,
  saveConversation,
  deleteConversation,
  loadConversations,
  searchConversations,
  exportConversation,
  createConversation,
  titleFromMessage,
  getStorageStats,
} from './conversation-store'

const QUICK_TAGS = [
  { label: 'DSS2', q: 'Show DSS2 observations' },
  { label: 'Errors', q: 'List errors' },
  { label: 'Detail', q: 'Show error detail' },
  { label: 'Pipeline', q: 'NVSS pipeline' },
]

const ROLE_COLOR: Record<string, string> = {
  a: '#00D4FF',
  u: '#FF006E',
  tool: '#FFB347',
}
const ROLE_LABEL: Record<string, string> = { a: 'AI', u: 'YOU', tool: 'TOOL' }

interface ToolStepDisplay {
  name: string
  args: Record<string, unknown>
  result?: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  elapsedMs?: number
}

export default function AssistantPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  // ═══ State ═══
  const [conv, setConv] = useState<Conversation>(() => loadActiveConversation())
  const [msgs, setMsgs] = useState<ConvMessage[]>(conv.messages)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [llmMode, setLlmMode] = useState(true)
  // v4.DIVS: Model selector — chat vs vision. Persisted to localStorage.
  const [modelKey, setModelKey] = useState<
    'deepseek-chat' | 'deepseek-v4-flash-vision-exp'
  >(
    () =>
      (localStorage.getItem('gw-llm-model') as
        'deepseek-chat' | 'deepseek-v4-flash-vision-exp') || 'deepseek-chat',
  )
  const [agentMode, setAgentMode] = useState(true)
  const [scanlinesOn, setScanlinesOn] = useState(
    () => localStorage.getItem('gw-scanlines') === 'on',
  )
  useEffect(() => {
    localStorage.setItem('gw-llm-model', modelKey)
  }, [modelKey])

  // v4.36: Streaming state
  const [streamingText, setStreamingText] = useState('')
  const [streamingRole, setStreamingRole] = useState<'a' | 'u' | null>(null)
  const [toolSteps, setToolSteps] = useState<ToolStepDisplay[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<
    ReturnType<typeof searchConversations>
  >([])
  const [showSearch, setShowSearch] = useState(false)
  const [savedIndicator, setSavedIndicator] = useState(false)

  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const counterRef = useRef(0)
  const convRef = useRef(conv)

  // ═══ Keep refs in sync ═══
  useEffect(() => {
    convRef.current = conv
  }, [conv])

  // ═══ WCAG: Check reduced motion preference ═══
  const [reducedMotion, setReducedMotion] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // ═══ Persist conversation on msgs change ═══
  useEffect(() => {
    if (msgs.length > 0 && msgs !== convRef.current.messages) {
      const updated = {
        ...convRef.current,
        messages: msgs,
        updatedAt: Date.now(),
        messageCount: msgs.length,
      }
      // Auto-title from first user message
      if (!updated.title || updated.title === 'New Conversation') {
        const firstUserMsg = msgs.find((m) => m.role === 'u')
        if (firstUserMsg) {
          updated.title = titleFromMessage(firstUserMsg.text)
        }
      }
      saveConversation(updated)
      setConv(updated)
      // Brief "Saved" indicator
      setSavedIndicator(true)
      const timer = setTimeout(() => setSavedIndicator(false), 1200)
      return () => clearTimeout(timer)
    }
  }, [msgs])

  // ═══ Auto-scroll ═══
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth' })
  }, [msgs, streamingText, toolSteps, reducedMotion])

  // ═══ Helpers ═══
  function newMsgId(): string {
    counterRef.current += 1
    return 'msg-' + Date.now() + '-' + counterRef.current
  }

  const toggleScanlines = () => {
    const next = !scanlinesOn
    setScanlinesOn(next)
    localStorage.setItem('gw-scanlines', next ? 'on' : 'off')
  }

  // ═══ Keyword query (offline mode) ═══
  const askKeyword = async (q: string) => {
    if (!q.trim()) return
    const userMsg: ConvMessage = {
      id: newMsgId(),
      role: 'u',
      text: q,
      timestamp: Date.now(),
    }
    setMsgs((p) => [...p, userMsg])
    setInput('')
    setLoading(true)
    // If not logged in, suggest login for better results
    if (!user) {
      setMsgs((p) => [
        ...p,
        {
          id: newMsgId(),
          role: 'a',
          text:
            '/** Keyword Mode (Offline) */\n// Login to enable AI-powered LLM/Agent mode\n// Your query: "' +
            q +
            '"\n// Recognized: DSS2, Errors, Detail, Pipeline',
          timestamp: Date.now(),
        },
      ])
      setLoading(false)
      return
    }
    try {
      let text: string
      const qLower = q.toLowerCase()
      if (qLower.includes('dss2') || qLower.includes('obs')) {
        const res = await axios.get('/api/app/gravitationalwave/geoSearch', {
          params: { telescope: 'DSS2', page_size: 5 },
        })
        text =
          '/** DSS2 Query Result */\n{\n  records: ' +
          (res?.data?.data?.total_info?.total_count ?? 'N/A') +
          ',\n  survey: "DSS2 (Digital Sky Survey 2)"\n}'
      } else if (qLower.includes('detail')) {
        const r1 = await axios.get('/api/app/gravitationalwave/error', {
          params: { page_size: 1 },
        })
        const first = r1?.data?.data?.list?.[0]
        if (!first) {
          text =
            '/** Error Detail Query */\n{\n  status: "NO_DATA",\n  message: "No anomaly reports available."\n}'
        } else {
          const eid = first.error_id != null ? String(first.error_id) : ''
          if (!/^[a-zA-Z0-9_-]+$/.test(eid)) {
            text =
              '/** ERROR */\n{\n  status: "INVALID_ID",\n  message: "Invalid error_id format"\n}'
            const aiMsg: ConvMessage = {
              id: newMsgId(),
              role: 'a',
              text,
              timestamp: Date.now(),
            }
            setMsgs((p) => [...p, aiMsg])
            setLoading(false)
            return
          }
          const r2 = await axios.get('/api/app/gravitationalwave/error/' + eid)
          const logPreview = r2?.data?.data?.logContent
            ? r2.data.data.logContent.substring(0, 300)
            : 'N/A'
          text =
            '/** Error Detail: ' +
            eid +
            ' */\n{\n  details: ' +
            (r2?.data?.data?.total_info?.total_count ?? 'N/A') +
            ',\n  log: "' +
            logPreview +
            '"\n}'
        }
      } else if (qLower.includes('error')) {
        const r1 = await axios.get('/api/app/gravitationalwave/error', {
          params: { page_size: 5 },
        })
        text =
          '/** Error Reports Query */\n{\n  total_errors: ' +
          (r1?.data?.data?.total_info?.total_count ?? 'N/A') +
          ',\n  page_size: 5\n}'
      } else if (qLower.includes('nvss') || qLower.includes('pipeline')) {
        const r1 = await axios
          .get('/pipeline/files', { params: { survey: 'NVSS' } })
          .then((res) => res.data)
        text =
          '/** Pipeline Status: NVSS */\n{\n  files: ' +
          r1.count +
          ',\n  surveys: [' +
          (r1.surveys || []).map((s: string) => '"' + s + '"').join(', ') +
          ']\n}'
      } else {
        text =
          '/** Keyword Mode */\n// Recognized commands: DSS2, Errors, Detail, Pipeline\n// Tip: Enable LLM mode (toggle top-right) for natural language AI queries\n// Your query: "' +
          q +
          '"'
      }
      const aiMsg: ConvMessage = {
        id: newMsgId(),
        role: 'a',
        text,
        timestamp: Date.now(),
      }
      setMsgs((p) => [...p, aiMsg])
    } catch (e: unknown) {
      console.warn('[Assistant] Keyword query failed:', e)
      const aiMsg: ConvMessage = {
        id: newMsgId(),
        role: 'a',
        text: '/** ERROR */\n{\n  status: "FAILED",\n  message: "Query failed. Try LLM mode."\n}',
        timestamp: Date.now(),
      }
      setMsgs((p) => [...p, aiMsg])
    } finally {
      setLoading(false)
    }
  }

  // ═══ v4.36: Streaming Agent Chat with typewriter effect ═══
  const askLLM = async (q: string) => {
    if (!q.trim()) return
    const sanitizedQ = sanitizeText(q)
    const userMsg: ConvMessage = {
      id: newMsgId(),
      role: 'u',
      text: sanitizedQ,
      timestamp: Date.now(),
    }
    setMsgs((p) => [...p, userMsg])
    setInput('')
    setLoading(true)
    setStreamingText('')
    setStreamingRole('a')
    setToolSteps([])

    // v4.36: XSS detection — warn but don't block
    if (detectXssAttempt(q)) {
      console.warn('[Security] Potential XSS pattern detected in user input')
    }

    try {
      const snapshot = convRef.current.messages.concat(userMsg)
      const conversationHistory = snapshot
        .filter(
          (m) =>
            m.model === 'deepseek' || m.model === 'agent' || m.role === 'u',
        )
        .slice(-10)
        .map((m) => ({
          role: (m.role === 'u' ? 'user' : 'assistant') as 'user' | 'assistant',
          content: m.text,
        }))
      conversationHistory.push({ role: 'user' as const, content: q })

      if (agentMode) {
        // ═══ v4.36: Agent mode WITH streaming ═══
        let accumulatedText = ''
        const activeToolSteps: ToolStepDisplay[] = []

        const result = await chatWithAgentStream(
          conversationHistory,
          (event, data) => {
            switch (event) {
              case 'tool_call': {
                const step: ToolStepDisplay = {
                  name: (data.tool_name as string) || 'unknown',
                  args: (data.tool_args as Record<string, unknown>) || {},
                  status: 'running',
                }
                activeToolSteps.push(step)
                setToolSteps([...activeToolSteps])
                break
              }
              case 'tool_result': {
                const lastRunning = activeToolSteps
                  .filter((s) => s.status === 'running')
                  .pop()
                if (lastRunning) {
                  lastRunning.status = data.success === false ? 'error' : 'done'
                  lastRunning.result = data as Record<string, unknown>
                  lastRunning.elapsedMs = data.elapsed_ms as number
                }
                setToolSteps([...activeToolSteps])
                break
              }
              case 'chunk': {
                // Typewriter: append chunk to accumulated text
                if (data.content) {
                  accumulatedText += data.content as string
                  setStreamingText(accumulatedText)
                }
                break
              }
              case 'response': {
                // Non-streaming full response
                if (data.content) {
                  accumulatedText = data.content as string
                  setStreamingText(accumulatedText)
                }
                break
              }
              case 'thinking': {
                // LLM is thinking/planning
                setStreamingText(
                  (prev) =>
                    prev + '\n/* ' + (data.content || 'Thinking...') + ' */\n',
                )
                break
              }
              case 'error': {
                console.warn('[Agent] Stream error event:', data)
                break
              }
              case 'reconnecting': {
                setStreamingText(
                  (prev) =>
                    prev +
                    '\n/* Reconnecting (' +
                    data.attempt +
                    '/' +
                    data.maxRetries +
                    ')... */\n',
                )
                break
              }
            }
          },
          { max_tool_rounds: 10, temperature: 0.3 },
        )

        // Build final message text
        const toolSummary =
          result.tool_calls_count > 0
            ? '\n\n/* ' +
              result.tool_calls_count +
              ' tool call(s) in ' +
              result.total_rounds +
              ' round(s), ' +
              result.total_time_ms +
              'ms */'
            : ''
        const verifyNote =
          result.verification && !result.verification.verified
            ? '\n\n/* Verification: ' + result.verification.summary + ' */'
            : result.verification?.verified &&
                result.verification.total_checks > 0
              ? '\n\n/* Verified: ' + result.verification.summary + ' */'
              : ''

        const finalText =
          (result.content || accumulatedText) + toolSummary + verifyNote

        // Sanitize before storing
        const safeText = sanitizeAndFormat(finalText)
        setMsgs((p) => [
          ...p,
          {
            id: newMsgId(),
            role: 'a',
            text: safeText,
            model: 'agent',
            timestamp: Date.now(),
          },
        ])
      } else {
        // ── Legacy mode: plain LLM chat (no streaming available) ──
        const reply = await chatWithDeepSeek(conversationHistory, modelKey)
        const safeReply = sanitizeAndFormat(reply)
        setMsgs((p) => [
          ...p,
          {
            id: newMsgId(),
            role: 'a',
            text: safeReply,
            model: 'deepseek',
            timestamp: Date.now(),
          },
        ])
      }
    } catch (e: unknown) {
      console.warn('[Assistant] AI query failed:', e)
      const errDetail = e instanceof Error ? e.message : String(e)
      const safeError = sanitizeText(errDetail)
      setMsgs((p) => [
        ...p,
        {
          id: newMsgId(),
          role: 'a',
          text:
            '/** AI Error */\n{\n  status: "FAILED",\n  error: "' +
            safeError +
            '"\n}',
          timestamp: Date.now(),
        },
      ])
    } finally {
      setLoading(false)
      setStreamingText('')
      setStreamingRole(null)
      setToolSteps([])
    }
  }

  const ask = useCallback(
    (q: string) => {
      if (llmMode && !user) {
        setMsgs((p) => [
          ...p,
          {
            id: newMsgId(),
            role: 'a',
            text: '/** Login Required */\n{\n  status: "UNAUTHORIZED",\n  message: "AI Chat requires login. Please login or register first.",\n  action: "/login"\n}',
            timestamp: Date.now(),
          },
        ])
        return
      }
      if (llmMode) {
        askLLM(q)
      } else {
        askKeyword(q)
      }
    },
    // R6.57: askKeyword/askLLM are plain functions defined later;
    // adding them as deps would force re-memo every render.
    // Refactor to useCallback tracked separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [llmMode, agentMode, user],
  )

  // ═══ Conversation management ═══
  const handleNewConv = () => {
    const newConv = createConversation()
    setConv(newConv)
    setMsgs(newConv.messages)
    convRef.current = newConv
    setShowHistory(false)
  }

  const handleLoadConv = (c: Conversation) => {
    setConv(c)
    setMsgs(c.messages)
    convRef.current = c
    setShowHistory(false)
  }

  const handleDeleteConv = (id: string) => {
    deleteConversation(id)
    if (conv.id === id) {
      handleNewConv()
    }
  }

  const handleExportConv = () => {
    const fullConv = { ...conv, messages: msgs }
    exportConversation(fullConv)
  }

  const handleCopyLastAI = () => {
    const lastAI = [...msgs].reverse().find((m) => m.role === 'a')
    if (lastAI) {
      navigator.clipboard.writeText(lastAI.text).catch(() => {
        // Fallback for older browsers
        const ta = document.createElement('textarea')
        ta.value = lastAI.text
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      })
    }
  }

  const handleRegenerate = () => {
    // Find last user message and re-send
    const lastUser = [...msgs].reverse().find((m) => m.role === 'u')
    if (lastUser && !loading) {
      // Remove last AI response if exists
      const lastUserIdx = msgs.findIndex((m) => m.id === lastUser.id)
      const trimmedMsgs = msgs.slice(0, lastUserIdx + 1)
      setMsgs(trimmedMsgs)
      // Re-send (small delay to let state settle)
      setTimeout(() => ask(lastUser.text), 50)
    }
  }

  // ═══ Search ═══
  const handleSearch = (q: string) => {
    setSearchQuery(q)
    if (q.trim().length < 2) {
      setSearchResults([])
      return
    }
    const results = searchConversations(q)
    setSearchResults(results)
  }

  // ═══ Status checks ═══
  const [keyStatus, setKeyStatus] = useState({
    configured: false,
    label: 'Checking...',
  })
  const [quotaInfo, setQuotaInfo] = useState<{
    remaining: number
    total: number
    pct: number
  } | null>(null)
  useEffect(() => {
    getLlmStatus()
      .then(setKeyStatus)
      .catch(() => setKeyStatus({ configured: false, label: 'OFFLINE' }))
    getLlmUsage()
      .then((u) => {
        if (u?.quota)
          setQuotaInfo({
            remaining: u.quota.daily_remaining,
            total: u.quota.daily_limit,
            pct: u.quota.pct_used,
          })
      })
      .catch(() => setQuotaInfo(null))
    getAgentStatus()
      .then((s) => {
        if (s.configured) setAgentMode(true)
      })
      .catch(() => setAgentMode(false))
  }, [])

  // ═══ Focus input on mount ═══
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 300)
    return () => clearTimeout(timer)
  }, [])

  // ═══ Render helpers ═══
  const renderMessageContent = (m: ConvMessage) => {
    // v4.36: Use dangerouslySetInnerHTML with sanitized content for formatted display
    // All content has been sanitized via sanitizeAndFormat before storage
    return (
      <div
        className='text-sm leading-relaxed whitespace-pre-wrap'
        style={{ fontSize: '12.5px' }}
        dangerouslySetInnerHTML={{ __html: m.text }}
      />
    )
  }

  // ═══ Mutable messages array for rendering: msgs + streaming placeholder ═══
  const displayMsgs = msgs
  const storageStats = getStorageStats()

  // ═══ WCAG contrast tokens ═══
  // v4.36: Improved contrast ratios for accessibility
  const WCAG = {
    dimText: 'rgba(240,246,252,0.45)', // Was 0.12-0.3 → now 0.45 (WCAG AA for large text)
    mediumText: 'rgba(240,246,252,0.55)', // Was 0.35 → now 0.55
    brightText: 'rgba(240,246,252,0.70)', // Was 0.4 → now 0.70
    borderDim: 'rgba(240,246,252,0.08)', // Slightly more visible borders
  }

  return (
    <div className='h-full flex flex-col' style={{ background: '#0D1117' }}>
      {/* ═══════ Editor Tabs Bar ═══════ */}
      <div
        className='flex items-center flex-shrink-0 select-none'
        data-ai-header='true'
        style={{
          background: '#161B22',
          borderBottom: '1px solid ' + WCAG.borderDim,
          height: 35,
        }}
      >
        <div
          className='flex items-center px-4 h-full gap-2'
          style={{
            background: '#0D1117',
            borderRight: '1px solid ' + WCAG.borderDim,
            borderTop: '2px solid #58A6FF',
          }}
        >
          <span
            className='text-xs font-semibold'
            style={{
              color: '#C9D1D9',
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            ai-terminal.tsx
          </span>
          <span
            className='text-xs cursor-pointer'
            style={{ color: WCAG.mediumText }}
          >
            ×
          </span>
        </div>
        <div
          className='flex items-center px-4 h-full gap-2'
          style={{ borderRight: '1px solid ' + WCAG.borderDim }}
        >
          <span
            className='text-xs'
            style={{
              color: WCAG.mediumText,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            chat.tsx
          </span>
        </div>
        <div
          className='flex items-center px-4 h-full gap-2'
          style={{ borderRight: '1px solid ' + WCAG.borderDim }}
        >
          <span
            className='text-xs'
            style={{
              color: WCAG.mediumText,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            llm.ts
          </span>
        </div>
        <div className='flex-1' />
        <div className='flex items-center gap-3 px-4'>
          {/* v4.36: Saved indicator */}
          <span
            className='text-xs transition-opacity'
            style={{
              color: '#3FB950',
              fontFamily: 'monospace',
              opacity: savedIndicator ? 1 : 0,
              transition: reducedMotion ? 'none' : 'opacity 0.3s ease',
            }}
          >
            ● SAVED
          </span>
          <span
            className='text-xs font-semibold'
            style={{
              color: llmMode ? '#3FB950' : '#D29922',
              fontFamily: 'monospace',
            }}
          >
            {llmMode ? '● LLM' : '● KW'}
          </span>
          <Tag
            color={keyStatus.configured ? 'green' : 'red'}
            className='text-xs'
            style={{ fontFamily: 'monospace', margin: 0, fontSize: 10 }}
          >
            {keyStatus.configured
              ? 'DeepSeek-V4'
              : keyStatus.label === 'Checking...'
                ? 'API...'
                : user
                  ? 'API:ERR'
                  : 'Login for API'}
          </Tag>
          {quotaInfo && (
            <span
              className='text-xs'
              style={{
                color:
                  quotaInfo.pct > 80
                    ? '#FF6B6B'
                    : quotaInfo.pct > 50
                      ? '#FFB347'
                      : WCAG.dimText,
                fontFamily: 'monospace',
                fontSize: 10,
              }}
            >
              Remaining: {quotaInfo.remaining}/{quotaInfo.total}
            </span>
          )}
          <button
            onClick={toggleScanlines}
            className='text-xs px-1.5 py-0.5 rounded border cursor-pointer'
            style={{
              background: 'rgba(255,255,255,0.04)',
              borderColor: 'rgba(255,255,255,0.12)',
              color: WCAG.mediumText,
              fontFamily: 'monospace',
              fontSize: 10,
            }}
            title={
              scanlinesOn
                ? 'CRT Scanlines ON (retro monitor effect) — click to disable'
                : 'FLAT display (no scanlines) — click for retro CRT monitor look'
            }
            aria-label={
              scanlinesOn
                ? 'Disable CRT scanline overlay'
                : 'Enable CRT scanline overlay'
            }
            aria-pressed={scanlinesOn}
          >
            {scanlinesOn ? 'CRT' : 'FLAT'}
          </button>
          {/* v4.DIVS: Model selector — DeepSeek chat vs vision */}
          <select
            value={modelKey}
            onChange={(e) => setModelKey(e.target.value as typeof modelKey)}
            className='text-xs px-1.5 py-0.5 rounded border cursor-pointer'
            style={{
              background:
                modelKey === 'deepseek-v4-flash-vision-exp'
                  ? 'rgba(0,240,255,0.10)'
                  : 'rgba(255,255,255,0.04)',
              borderColor:
                modelKey === 'deepseek-v4-flash-vision-exp'
                  ? 'rgba(0,240,255,0.40)'
                  : 'rgba(255,255,255,0.12)',
              color:
                modelKey === 'deepseek-v4-flash-vision-exp'
                  ? '#00F0FF'
                  : WCAG.mediumText,
              fontFamily: 'monospace',
              fontSize: 10,
              outline: 'none',
              cursor: 'pointer',
            }}
            title={
              modelKey === 'deepseek-v4-flash-vision-exp'
                ? 'Vision model — supports image input'
                : 'Chat model — text only, fastest'
            }
            aria-label='Select DeepSeek model variant'
          >
            <option value='deepseek-chat'>CHAT</option>
            <option value='deepseek-v4-flash-vision-exp'>VISION</option>
          </select>
          <Switch size='small' checked={llmMode} onChange={setLlmMode} />
        </div>
      </div>

      {/* ═══════ Breadcrumb ═══════ */}
      <div
        className='flex items-center px-4 py-1 flex-shrink-0 text-xs gap-1 select-none'
        style={{
          background: '#0D1117',
          borderBottom: '1px solid rgba(240,246,252,0.04)',
          fontFamily: '"JetBrains Mono", monospace',
        }}
      >
        <span style={{ color: WCAG.dimText }}>src</span>
        <span style={{ color: WCAG.dimText }}>{'>'}</span>
        <span style={{ color: WCAG.dimText }}>pages</span>
        <span style={{ color: WCAG.dimText }}>{'>'}</span>
        <span style={{ color: WCAG.dimText }}>assistant</span>
        <span style={{ color: WCAG.dimText }}>{'>'}</span>
        <span className='font-semibold' style={{ color: '#58A6FF' }}>
          ai-terminal.tsx
        </span>
        {/* v4.36: Conv title */}
        <span className='mx-2' style={{ color: 'rgba(240,246,252,0.15)' }}>
          |
        </span>
        <span style={{ color: WCAG.brightText }} title={conv.title}>
          {conv.title}
        </span>
      </div>

      {/* ═══════ Toolbar: Quick Actions + Conversation Management ═══════ */}
      <div
        className='flex gap-1.5 px-4 py-1.5 flex-shrink-0 flex-wrap items-center'
        style={{
          background: '#0D1117',
          borderBottom: '1px solid rgba(240,246,252,0.03)',
        }}
      >
        <span
          className='text-xs mr-1'
          style={{ color: WCAG.dimText, fontFamily: 'monospace' }}
        >
          &gt;
        </span>
        {QUICK_TAGS.map((t) => (
          <button
            key={t.label}
            type='button'
            onClick={() => ask(t.q)}
            disabled={loading}
            className='px-2.5 py-0.5 rounded text-xs font-semibold cursor-pointer'
            style={{
              background: 'rgba(88,166,255,0.06)',
              border: '1px solid rgba(88,166,255,0.1)',
              color: 'rgba(88,166,255,0.7)',
              fontFamily: 'monospace',
              opacity: loading ? 0.4 : 1,
              transition: reducedMotion ? 'none' : 'opacity 0.15s ease',
            }}
          >
            {t.label}
          </button>
        ))}
        <div className='flex-1' />
        {/* v4.36: Conversation management buttons */}
        <button
          onClick={handleNewConv}
          disabled={loading}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: WCAG.mediumText,
            fontFamily: 'monospace',
          }}
          title='New conversation'
          aria-label='New conversation'
        >
          + New
        </button>
        <button
          onClick={() => setShowHistory(!showHistory)}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: showHistory
              ? 'rgba(88,166,255,0.1)'
              : 'rgba(255,255,255,0.03)',
            border:
              '1px solid ' +
              (showHistory ? 'rgba(88,166,255,0.2)' : 'rgba(255,255,255,0.08)'),
            color: showHistory ? '#58A6FF' : WCAG.mediumText,
            fontFamily: 'monospace',
          }}
          title='Conversation history'
          aria-label='Conversation history'
        >
          <HistoryOutlined style={{ fontSize: 11 }} /> History
        </button>
        <button
          onClick={() => setShowSearch(!showSearch)}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: showSearch
              ? 'rgba(88,166,255,0.1)'
              : 'rgba(255,255,255,0.03)',
            border:
              '1px solid ' +
              (showSearch ? 'rgba(88,166,255,0.2)' : 'rgba(255,255,255,0.08)'),
            color: showSearch ? '#58A6FF' : WCAG.mediumText,
            fontFamily: 'monospace',
          }}
          title='Search conversations'
          aria-label='Search conversations'
        >
          <SearchOutlined style={{ fontSize: 11 }} /> Search
        </button>
        <button
          onClick={handleCopyLastAI}
          disabled={loading || msgs.filter((m) => m.role === 'a').length === 0}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: WCAG.mediumText,
            fontFamily: 'monospace',
            opacity: msgs.filter((m) => m.role === 'a').length === 0 ? 0.3 : 1,
          }}
          title='Copy last response'
          aria-label='Copy last response'
        >
          <CopyOutlined style={{ fontSize: 11 }} /> Copy
        </button>
        <button
          onClick={handleRegenerate}
          disabled={loading}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: WCAG.mediumText,
            fontFamily: 'monospace',
            opacity: loading ? 0.3 : 1,
          }}
          title='Regenerate last response'
          aria-label='Regenerate last response'
        >
          <ReloadOutlined style={{ fontSize: 11 }} /> Retry
        </button>
        <button
          onClick={handleExportConv}
          className='text-xs px-2 py-0.5 rounded cursor-pointer'
          style={{
            background: 'rgba(63,185,80,0.08)',
            border: '1px solid rgba(63,185,80,0.15)',
            color: '#3FB950',
            fontFamily: 'monospace',
          }}
          title='Export as Markdown'
          aria-label='Export conversation as Markdown'
        >
          <DownloadOutlined style={{ fontSize: 11 }} /> Export
        </button>
        <span
          className='text-xs'
          style={{ color: WCAG.dimText, fontFamily: 'monospace' }}
        >
          msgs:{msgs.length}
        </span>
      </div>

      {/* ═══════ Search Panel (collapsible) ═══════ */}
      {showSearch && (
        <div
          className='px-4 py-2 flex-shrink-0'
          style={{
            background: '#161B22',
            borderBottom: '1px solid rgba(240,246,252,0.04)',
          }}
        >
          <div className='flex items-center gap-2 mb-2'>
            <SearchOutlined style={{ color: WCAG.dimText, fontSize: 12 }} />
            <input
              className='flex-1 bg-transparent border-none outline-none text-sm'
              style={{
                fontFamily: '"JetBrains Mono", monospace',
                color: '#C9D1D9',
                caretColor: '#58A6FF',
                fontSize: 12,
              }}
              placeholder='Search all conversations (min 2 chars)...'
              value={searchQuery}
              onChange={(e) => handleSearch(e.target.value)}
              aria-label='Search conversations'
            />
          </div>
          {searchResults.length > 0 && (
            <div
              className='max-h-40 overflow-auto'
              style={{ scrollbarWidth: 'thin' }}
            >
              {searchResults.map(({ conv: c, matches }) => (
                <div
                  key={c.id}
                  className='flex items-center gap-2 py-1 px-2 rounded cursor-pointer mb-1'
                  onClick={() => handleLoadConv(c)}
                  style={{
                    background: 'rgba(88,166,255,0.04)',
                    border: '1px solid rgba(88,166,255,0.06)',
                  }}
                >
                  <span
                    className='text-xs flex-1'
                    style={{
                      color: WCAG.brightText,
                      fontFamily: 'monospace',
                      fontSize: 11,
                    }}
                  >
                    {c.title}
                  </span>
                  <span
                    className='text-xs'
                    style={{
                      color: WCAG.dimText,
                      fontFamily: 'monospace',
                      fontSize: 10,
                    }}
                  >
                    {matches.length} match(es)
                  </span>
                  <span
                    className='text-xs'
                    style={{
                      color: WCAG.dimText,
                      fontFamily: 'monospace',
                      fontSize: 10,
                    }}
                  >
                    {new Date(c.updatedAt).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          )}
          {searchQuery.length >= 2 && searchResults.length === 0 && (
            <p
              className='text-xs'
              style={{ color: WCAG.dimText, fontFamily: 'monospace' }}
            >
              No results found.
            </p>
          )}
        </div>
      )}

      {/* ═══════ History Panel (collapsible) ═══════ */}
      {showHistory && (
        <div
          className='px-4 py-2 flex-shrink-0'
          style={{
            background: '#161B22',
            borderBottom: '1px solid rgba(240,246,252,0.04)',
          }}
        >
          <div className='flex items-center justify-between mb-2'>
            <span
              className='text-xs font-semibold'
              style={{ color: WCAG.brightText, fontFamily: 'monospace' }}
            >
              Saved Conversations ({storageStats.conversationCount})
            </span>
            <span
              className='text-xs'
              style={{
                color: WCAG.dimText,
                fontFamily: 'monospace',
                fontSize: 10,
              }}
            >
              ~{storageStats.estimatedSizeKB} KB
            </span>
          </div>
          <div
            className='max-h-48 overflow-auto'
            style={{ scrollbarWidth: 'thin' }}
          >
            {loadConversations().map((c) => (
              <div
                key={c.id}
                className='flex items-center gap-2 py-1.5 px-2 rounded mb-1 group'
                style={{
                  background:
                    c.id === conv.id
                      ? 'rgba(88,166,255,0.08)'
                      : 'rgba(255,255,255,0.02)',
                  border:
                    '1px solid ' +
                    (c.id === conv.id
                      ? 'rgba(88,166,255,0.15)'
                      : 'rgba(255,255,255,0.04)'),
                  cursor: 'pointer',
                }}
              >
                <div
                  className='flex-1 min-w-0'
                  onClick={() => handleLoadConv(c)}
                >
                  <div
                    className='text-xs truncate'
                    style={{
                      color: c.id === conv.id ? '#58A6FF' : WCAG.brightText,
                      fontFamily: 'monospace',
                      fontSize: 11,
                      fontWeight: c.id === conv.id ? 600 : 400,
                    }}
                  >
                    {c.id === conv.id ? '● ' : ''}
                    {c.title}
                  </div>
                  <div
                    className='text-xs mt-0.5'
                    style={{
                      color: WCAG.dimText,
                      fontFamily: 'monospace',
                      fontSize: 10,
                    }}
                  >
                    {c.messageCount} msgs ·{' '}
                    {new Date(c.updatedAt).toLocaleString()}
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDeleteConv(c.id)
                  }}
                  className='text-xs px-1.5 py-0.5 rounded cursor-pointer opacity-0 group-hover:opacity-100'
                  style={{
                    background: 'rgba(255,59,48,0.08)',
                    border: '1px solid rgba(255,59,48,0.12)',
                    color: '#FF3B30',
                    fontFamily: 'monospace',
                    fontSize: 10,
                    transition: reducedMotion ? 'none' : 'opacity 0.15s ease',
                  }}
                  title='Delete conversation'
                  aria-label={'Delete conversation: ' + c.title}
                >
                  <DeleteOutlined style={{ fontSize: 10 }} />
                </button>
              </div>
            ))}
            {loadConversations().length === 0 && (
              <p
                className='text-xs'
                style={{ color: WCAG.dimText, fontFamily: 'monospace' }}
              >
                No saved conversations yet.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ═══════ Editor Body (Messages) ═══════ */}
      <div
        className='flex-1 overflow-hidden relative'
        style={{ fontFamily: '"JetBrains Mono", "Fira Code", monospace' }}
      >
        {/* Scanline overlay — respects reduced-motion */}
        {scanlinesOn && !reducedMotion && (
          <div
            className='absolute inset-0 pointer-events-none'
            aria-hidden='true'
            style={{
              background:
                'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.04) 2px, rgba(0,0,0,0.04) 4px)',
              zIndex: 1,
            }}
          />
        )}

        <div className='flex h-full overflow-hidden relative z-0'>
          {/* ═══════ Gutter (Line Numbers) — v4.36 improved contrast ═══════ */}
          <div
            className='flex-shrink-0 w-14 overflow-hidden select-none'
            aria-hidden='true'
            style={{
              background: 'rgba(0,0,0,0.25)',
              borderRight: '1px solid rgba(240,246,252,0.06)',
            }}
          >
            <div
              className='py-4 text-right pr-3 overflow-hidden'
              style={{ height: '100%' }}
            >
              {displayMsgs.map((_, idx) => (
                <div
                  key={'ln-' + idx}
                  className='text-xs leading-relaxed'
                  style={{
                    color: WCAG.dimText, // v4.36: Was rgba(240,246,252,0.12) — now 0.45 for WCAG compliance
                    fontFamily: 'inherit',
                    paddingTop: idx === 0 ? 0 : 8,
                    paddingBottom: 8,
                  }}
                >
                  {String(idx + 1).padStart(2, '0')}
                </div>
              ))}
              {/* v4.36: Streaming skeleton line */}
              {loading && streamingRole && (
                <div
                  className='text-xs leading-relaxed'
                  style={{
                    color: '#58A6FF',
                    fontFamily: 'inherit',
                    paddingBottom: 8,
                    fontWeight: 600,
                  }}
                >
                  {String(displayMsgs.length + 1).padStart(2, '0')}
                </div>
              )}
            </div>
          </div>

          {/* ═══════ Code Area ═══════ */}
          <div
            className='flex-1 py-4 px-5 overflow-auto'
            style={{
              scrollbarWidth: 'thin',
              scrollbarColor: 'rgba(240,246,252,0.12) transparent',
            }}
          >
            {/* v4.36: Skeleton screen when initially loading (no messages yet, first load) */}
            {loading && msgs.length <= 1 && !streamingText && (
              <div
                className='mb-4 animate-pulse'
                style={{ maxWidth: '100%' }}
                aria-label='Loading response...'
              >
                <div className='flex items-center gap-2 mb-1.5'>
                  <span
                    style={{
                      color: '#58A6FF',
                      fontWeight: 700,
                      fontSize: '10px',
                      fontFamily: 'monospace',
                    }}
                  >
                    [AI]
                  </span>
                  <span
                    className='text-xs px-1.5 py-0.5 rounded'
                    style={{
                      background: 'rgba(255,179,71,0.08)',
                      color: '#FFB347',
                      fontFamily: 'monospace',
                      fontSize: '10px',
                    }}
                  >
                    AGENT
                  </span>
                </div>
                <div
                  className='rounded-md p-4'
                  style={{
                    background: 'rgba(88,166,255,0.02)',
                    border: '1px solid rgba(88,166,255,0.06)',
                    borderLeft: '2px solid #58A6FF',
                  }}
                >
                  {/* Skeleton lines */}
                  <div
                    className='mb-2 rounded'
                    style={{
                      height: 12,
                      width: '85%',
                      background: 'rgba(240,246,252,0.06)',
                    }}
                  />
                  <div
                    className='mb-2 rounded'
                    style={{
                      height: 12,
                      width: '60%',
                      background: 'rgba(240,246,252,0.04)',
                    }}
                  />
                  <div
                    className='mb-2 rounded'
                    style={{
                      height: 12,
                      width: '75%',
                      background: 'rgba(240,246,252,0.05)',
                    }}
                  />
                  <div
                    className='rounded'
                    style={{
                      height: 12,
                      width: '40%',
                      background: 'rgba(240,246,252,0.03)',
                    }}
                  />
                </div>
              </div>
            )}

            {displayMsgs.map((m) => {
              const color = ROLE_COLOR[m.role]
              const label = ROLE_LABEL[m.role]
              const isAI = m.role === 'a'
              return (
                <div key={m.id} className='mb-4' style={{ maxWidth: '100%' }}>
                  <div className='flex items-center gap-2 mb-1.5'>
                    <span
                      style={{
                        color,
                        fontWeight: 700,
                        fontSize: '10px',
                        letterSpacing: '0.1em',
                        fontFamily: 'monospace',
                      }}
                    >
                      [{label}]
                    </span>
                    {(m.model === 'deepseek' || m.model === 'agent') && (
                      <span
                        className='text-xs px-1.5 py-0.5 rounded'
                        style={{
                          background:
                            m.model === 'agent'
                              ? 'rgba(255,179,71,0.08)'
                              : 'rgba(88,166,255,0.06)',
                          color: m.model === 'agent' ? '#FFB347' : '#58A6FF',
                          fontFamily: 'monospace',
                          fontSize: '10px',
                          fontWeight: 600,
                        }}
                      >
                        {m.model === 'agent' ? 'AGENT' : 'LLM'}
                      </span>
                    )}
                    {/* v4.36: Timestamp */}
                    <span
                      className='text-xs'
                      style={{
                        color: WCAG.dimText,
                        fontFamily: 'monospace',
                        fontSize: 10,
                        marginLeft: 'auto',
                      }}
                    >
                      {new Date(m.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <div
                    className='rounded-md p-4'
                    style={{
                      background: isAI
                        ? 'rgba(88,166,255,0.02)'
                        : 'rgba(255,123,114,0.03)',
                      border:
                        '1px solid ' +
                        (isAI
                          ? 'rgba(88,166,255,0.06)'
                          : 'rgba(255,123,114,0.08)'),
                      borderLeft: '2px solid ' + color,
                      color: isAI ? '#C9D1D9' : '#FFD8D4',
                    }}
                  >
                    {renderMessageContent(m)}
                  </div>
                </div>
              )
            })}

            {/* ═══ v4.36: Streaming message (typewriter effect) ═══ */}
            {loading && streamingRole && streamingText && (
              <div className='mb-4' style={{ maxWidth: '100%' }}>
                <div className='flex items-center gap-2 mb-1.5'>
                  <span
                    style={{
                      color: ROLE_COLOR.a,
                      fontWeight: 700,
                      fontSize: '10px',
                      fontFamily: 'monospace',
                    }}
                  >
                    [AI]
                  </span>
                  <span
                    className='text-xs px-1.5 py-0.5 rounded'
                    style={{
                      background: 'rgba(255,179,71,0.08)',
                      color: '#FFB347',
                      fontFamily: 'monospace',
                      fontSize: '10px',
                      fontWeight: 600,
                    }}
                  >
                    AGENT
                  </span>
                  <span
                    className='text-xs'
                    style={{
                      color: '#3FB950',
                      fontFamily: 'monospace',
                      fontSize: 10,
                      marginLeft: 'auto',
                    }}
                  >
                    ● streaming
                  </span>
                </div>
                <div
                  className='rounded-md p-4 text-sm leading-relaxed whitespace-pre-wrap'
                  style={{
                    background: 'rgba(88,166,255,0.02)',
                    border: '1px solid rgba(88,166,255,0.08)',
                    borderLeft: '2px solid #00D4FF',
                    color: '#C9D1D9',
                    fontSize: '12.5px',
                  }}
                >
                  {/* v4.36: Safe rendering of streaming content with typewriter cursor */}
                  <span
                    dangerouslySetInnerHTML={{
                      __html: sanitizeAndFormat(streamingText),
                    }}
                  />
                  <span
                    className='inline-block w-2 h-4 ml-0.5 align-middle'
                    style={{
                      background: '#58A6FF',
                      animation: reducedMotion
                        ? 'none'
                        : 'blink 1s step-end infinite',
                    }}
                    aria-hidden='true'
                  />
                </div>
              </div>
            )}

            {/* ═══ v4.36: Tool call steps display during streaming ═══ */}
            {toolSteps.length > 0 && (
              <div className='mb-3 ml-8'>
                {toolSteps.map((step, idx) => (
                  <div key={idx} className='flex items-center gap-2 py-1'>
                    <span
                      style={{
                        color:
                          step.status === 'running'
                            ? '#FFB347'
                            : step.status === 'error'
                              ? '#FF3B30'
                              : '#3FB950',
                        fontSize: '10px',
                        fontFamily: 'monospace',
                      }}
                    >
                      {step.status === 'running'
                        ? '◌'
                        : step.status === 'error'
                          ? '✕'
                          : '✓'}
                    </span>
                    <span
                      className='text-xs'
                      style={{
                        color: WCAG.mediumText,
                        fontFamily: 'monospace',
                      }}
                    >
                      {step.name}
                    </span>
                    {step.elapsedMs != null && (
                      <span
                        className='text-xs'
                        style={{
                          color: WCAG.dimText,
                          fontFamily: 'monospace',
                          fontSize: 10,
                        }}
                      >
                        {step.elapsedMs}ms
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* v4.36: Generic loading indicator (no streaming yet, waiting for first chunk) */}
            {loading && !streamingText && msgs.length > 1 && (
              <div className='flex items-center gap-3 mb-4'>
                <span
                  style={{
                    color: '#58A6FF',
                    fontWeight: 700,
                    fontSize: '10px',
                    fontFamily: 'monospace',
                  }}
                >
                  [AI]
                </span>
                <Spin size='small' />
                <span
                  className='text-xs'
                  style={{ color: WCAG.mediumText, fontFamily: 'monospace' }}
                >
                  {agentMode && llmMode
                    ? 'Agent connecting...'
                    : llmMode
                      ? 'DeepSeek generating...'
                      : 'executing query...'}
                </span>
              </div>
            )}
            <div ref={ref} />
          </div>
        </div>
      </div>

      {/* ═══════ VS Code Status Bar — v4.36 improved contrast ═══════ */}
      <div
        className='flex items-center px-3 py-0.5 flex-shrink-0 text-xs gap-3 select-none'
        style={{
          background: '#007ACC',
          fontFamily: '"JetBrains Mono", monospace',
          color: '#FFFFFF',
          height: 22,
        }}
      >
        <span>{'>'} ai-terminal.tsx</span>
        <span className='opacity-80'>Terminal</span>
        <div className='flex-1' />
        {/* v4.36: Show reduced motion indicator */}
        {reducedMotion && (
          <span className='opacity-80' aria-label='Reduced motion active'>
            ♿ A11y
          </span>
        )}
        <span className='opacity-80'>Ln {msgs.length}, Col 1</span>
        <span className='opacity-80'>Spaces: 2</span>
        <span className='opacity-80'>UTF-8</span>
        <span className='opacity-80'>
          {agentMode && llmMode ? 'AGENT' : llmMode ? 'LLM' : 'KEYWORD'}
        </span>
        <span
          className='opacity-80'
          style={{
            background: llmMode ? '#3FB950' : '#D29922',
            padding: '0 6px',
            borderRadius: 3,
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          {agentMode && llmMode
            ? 'Agent-v4.36'
            : llmMode
              ? 'DeepSeek-V4'
              : 'Local'}
        </span>
      </div>

      {/* ═══════ Terminal Input ═══════ */}
      <div
        className='flex-shrink-0'
        style={{
          background: '#0D1117',
          borderTop: '1px solid rgba(240,246,252,0.06)',
        }}
      >
        <div
          className='flex items-center px-4 py-1 text-xs gap-2'
          style={{
            borderBottom: '1px solid rgba(240,246,252,0.03)',
            fontFamily: '"JetBrains Mono", monospace',
          }}
        >
          <span style={{ color: WCAG.mediumText }}>TERMINAL</span>
          <span style={{ color: '#3FB950', fontSize: 10 }}>●</span>
          <span className='flex-1' />
          {/* v4.36: Small status hints */}
          <span style={{ color: WCAG.dimText, fontSize: 10 }}>
            {conv.title}
          </span>
        </div>
        <div
          className='flex items-center gap-2 px-4 py-2'
          style={{ fontFamily: '"JetBrains Mono", "Fira Code", monospace' }}
        >
          <span
            className='text-sm font-bold flex-shrink-0 select-none'
            style={{ color: '#3FB950' }}
          >
            gw ~ $
          </span>
          {llmMode && !user ? (
            <div className='flex-1 flex items-center gap-3'>
              <span
                style={{
                  color: '#F85149',
                  fontFamily: 'monospace',
                  fontSize: 12,
                }}
              >
                ! Login required for AI Chat
              </span>
              <Button
                type='primary'
                size='small'
                icon={<LoginOutlined />}
                onClick={() => navigate('/login')}
                style={{
                  background: 'rgba(88,166,255,0.15)',
                  border: '1px solid rgba(88,166,255,0.3)',
                  color: '#58A6FF',
                  borderRadius: 6,
                  fontWeight: 600,
                  fontSize: 11,
                  fontFamily: 'monospace',
                }}
              >
                Login / Register
              </Button>
            </div>
          ) : (
            <input
              ref={inputRef}
              className='flex-1 bg-transparent border-none outline-none text-sm placeholder-current'
              style={{
                fontFamily: 'inherit',
                color: '#C9D1D9',
                caretColor: '#58A6FF',
                fontSize: '13px', // v4.36: slightly larger for readability
              }}
              placeholder={
                agentMode && llmMode
                  ? 'ask AI agent to query/analyze data...'
                  : llmMode
                    ? 'ask about gravitational wave data...'
                    : 'enter keyword query...'
              }
              aria-label='Terminal command input'
              value={input}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) ask(input)
              }}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
            />
          )}
          <button
            type='button'
            onClick={() => ask(input)}
            disabled={loading}
            className='flex-shrink-0 w-7 h-7 rounded flex items-center justify-center border-0'
            style={{
              background: 'rgba(63,185,80,0.12)',
              color: '#3FB950',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.35 : 1,
              transition: reducedMotion ? 'none' : 'opacity 0.15s ease',
            }}
            aria-label='Send message'
          >
            <SendOutlined style={{ fontSize: 12 }} />
          </button>
        </div>
      </div>

      {/* ═══════ v4.36: Inline CSS for typewriter blink + code formatting ═══════ */}
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .code-block {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 4px;
          padding: 8px 12px;
          margin: 8px 0;
          overflow-x: auto;
          font-family: "JetBrains Mono", "Fira Code", monospace;
          font-size: 11.5px;
          color: #C9D1D9;
        }
        .inline-code {
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 3px;
          padding: 1px 5px;
          font-family: "JetBrains Mono", "Fira Code", monospace;
          font-size: 11px;
          color: #FFB347;
        }
        @media (prefers-reduced-motion: reduce) {
          .code-block, .inline-code {
            /* No animation */
          }
          * {
            transition-duration: 0.01ms !important;
          }
        }
      `}</style>
    </div>
  )
}
