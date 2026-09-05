import axios, { AxiosError } from 'axios'

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('gw_auth_token')
  return token ? { Authorization: 'Bearer ' + token } : {}
}

const BACKEND_LLM_URL = '/pipeline/llm/chat'

interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

// System prompt is managed server-side by the Python pipeline (server.py)
// Frontend sends raw user/assistant messages only.

export async function chatWithDeepSeek(
  messages: ChatMessage[],
  model?: string, // v4.DIVS: optional model override (e.g. 'deepseek-v4-flash-vision-exp')
): Promise<string> {
  try {
    const response = await axios.post(
      BACKEND_LLM_URL,
      { messages, ...(model ? { model } : {}) },
      {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        timeout: 90000,
      },
    )

    const data = response.data
    // Python pipeline returns flat {content, model} or {error: "message"}
    if (data?.error) {
      const errMsg =
        typeof data.error === 'string'
          ? data.error
          : data.error.msg || 'LLM service error'
      throw new Error(errMsg)
    }

    const content = data?.content
    if (!content) {
      throw new Error('Empty response from LLM service')
    }
    return content
  } catch (error: unknown) {
    const err = error as AxiosError<{ error?: string | { msg: string } }>
    if (err.response?.status === 401) {
      throw new Error(
        'LLM API authentication failed. Please check server configuration.',
      )
    }
    if (err.response?.status === 429) {
      throw new Error(
        'LLM API rate limit exceeded. Please wait a moment and try again.',
      )
    }
    if (err.response?.status === 502 || err.response?.status === 504) {
      throw new Error(
        'LLM backend is temporarily unavailable. Please try again later.',
      )
    }
    if (err.response?.data?.error) {
      const backendErr =
        typeof err.response.data.error === 'string'
          ? err.response.data.error
          : err.response.data.error.msg
      throw new Error(backendErr || 'LLM service error')
    }
    throw new Error(err.message || 'Failed to connect to LLM service')
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// AI Agent v4.33 — tool-using agent capabilities
// ═══════════════════════════════════════════════════════════════════════════

export interface AgentToolCall {
  step: number
  type: 'tool_call' | 'response' | 'error'
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_result?: Record<string, unknown>
  content?: string
  elapsed_ms?: number
}

export interface AgentResponse {
  success: boolean
  content: string
  error?: string
  model: string
  total_rounds: number
  total_time_ms: number
  tool_calls_count: number
  steps: AgentToolCall[]
  quota_remaining?: number
  available_tools?: string[]
}

const AGENT_URL = '/pipeline/agent/chat'

export async function chatWithAgent(
  messages: ChatMessage[],
  options?: { max_tool_rounds?: number; temperature?: number },
): Promise<AgentResponse> {
  try {
    const response = await axios.post(
      AGENT_URL,
      {
        messages,
        max_tool_rounds: options?.max_tool_rounds ?? 10,
        temperature: options?.temperature ?? 0.3,
      },
      {
        headers: { 'Content-Type': 'application/json' },
        timeout: 300000, // 5 min — agent loops can take time
      },
    )

    const data = response.data as AgentResponse

    if (!data?.success) {
      throw new Error(data?.error || 'Agent execution failed')
    }
    return data
  } catch (error: unknown) {
    const err = error as AxiosError<{ error?: string }>
    if (err.response?.status === 401) {
      throw new Error(
        'Agent API authentication failed. Check server configuration.',
      )
    }
    if (err.response?.status === 429) {
      throw new Error('Agent API quota exceeded. Try again later.')
    }
    if (err.response?.status === 502 || err.response?.status === 504) {
      throw new Error('Agent backend temporarily unavailable.')
    }
    if (err.response?.data?.error) {
      throw new Error(
        typeof err.response.data.error === 'string'
          ? err.response.data.error
          : 'Agent service error',
      )
    }
    throw new Error(err.message || 'Failed to connect to Agent service')
  }
}

export async function getAgentStatus(): Promise<{
  configured: boolean
  model: string
  tool_count: number
  available_tools: string[]
}> {
  try {
    const resp = await axios.get('/pipeline/agent/status', { timeout: 5000 })
    return resp.data
  } catch (e) {
    console.warn('[Agent Status] Failed:', e)
    return { configured: false, model: '', tool_count: 0, available_tools: [] }
  }
}

export async function getLlmStatus(): Promise<{
  configured: boolean
  label: string
}> {
  try {
    const response = await axios.get('/pipeline/llm/status', {
      timeout: 5000,
      headers: getAuthHeaders(),
    })
    // Python pipeline returns flat {configured: boolean, model: string}
    const data = response.data
    if (data?.configured) {
      return { configured: true, label: `Connected (${data.model})` }
    }
    return { configured: false, label: 'Not configured' }
  } catch (e) {
    console.warn('[LLM Status] Failed to reach backend:', e)
    return { configured: false, label: 'Backend unreachable' }
  }
}

export interface LlmUsage {
  configured: boolean
  model: string
  quota: {
    daily_limit: number
    daily_used: number
    daily_remaining: number
    pct_used: number
  }
}

export async function getLlmUsage(): Promise<LlmUsage | null> {
  try {
    const response = await axios.get('/pipeline/llm/usage', {
      timeout: 5000,
      headers: getAuthHeaders(),
    })
    return response.data as LlmUsage
  } catch (e) {
    console.warn('[LLM Usage] Failed to reach backend:', e)
    return null
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// v4.34: Streaming + Session + Friendly errors
// ═══════════════════════════════════════════════════════════════════════════

// Generate or retrieve persistent session ID
function getSessionId(): string {
  let sid = localStorage.getItem('gw-session-id')
  if (!sid) {
    sid =
      'gw-' +
      Date.now().toString(36) +
      '-' +
      Math.random().toString(36).slice(2, 8)
    localStorage.setItem('gw-session-id', sid)
  }
  return sid
}

// Axios instance with session header
const agentAxios = axios.create({
  headers: { 'Content-Type': 'application/json' },
  timeout: 300000,
})
agentAxios.interceptors.request.use((config) => {
  config.headers['X-Session-ID'] = getSessionId()
  return config
})

export interface VerificationCheck {
  category: string
  claimed: string
  match: string
  status: 'verified' | 'discrepancy' | 'unverified'
  actual?: unknown
  deviation_pct?: number
  note?: string
}

export interface AgentVerification {
  verified: boolean
  total_checks: number
  passed: number
  discrepancy_count: number
  checks: VerificationCheck[]
  summary: string
  ground_truth_summary?: Record<string, unknown>
}

// v4.34: Updated AgentResponse with verification
export interface AgentResponseV434 extends AgentResponse {
  verification?: AgentVerification
  content_safety?: {
    safe: boolean
    score: number
    flags: Array<{ type: string; detail: string }>
  }
}

// v4.34: Streaming agent chat via SSE
// v4.35: Reconnect configuration (Fix #4)
const MAX_RECONNECT_RETRIES = 3
const HEARTBEAT_TIMEOUT_MS = 45000 // 3x heartbeat interval

export async function chatWithAgentStream(
  messages: ChatMessage[],
  onEvent: (event: string, data: Record<string, unknown>) => void,
  options?: { max_tool_rounds?: number; temperature?: number },
): Promise<AgentResponseV434> {
  const url = '/pipeline/agent/chat/stream'
  let retries = 0

  while (true) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': getSessionId(),
          ...(localStorage.getItem('gw_auth_token')
            ? {
                Authorization:
                  'Bearer ' + localStorage.getItem('gw_auth_token'),
              }
            : {}),
        },
        body: JSON.stringify({
          messages,
          max_tool_rounds: options?.max_tool_rounds ?? 10,
          temperature: options?.temperature ?? 0.3,
        }),
      })
      console.log(
        '[Agent Stream] Response status:',
        response.status,
        'type:',
        response.type,
      )

      if (!response.ok) {
        const errText = await response.text()
        console.error(
          '[Agent Stream] HTTP',
          response.status,
          errText?.substring(0, 200),
        )
        throw new Error(mapErrorCode(response.status, errText))
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('Streaming not supported')

      const decoder = new TextDecoder()
      let buffer = ''
      let finalResult: AgentResponseV434 | null = null

      // v4.35: Heartbeat watchdog — reconnect if no data for 45s
      let lastEventTime = Date.now()
      const heartbeatWatchdog = setInterval(() => {
        if (Date.now() - lastEventTime > HEARTBEAT_TIMEOUT_MS) {
          console.warn('[SSE] Heartbeat timeout — closing stream for reconnect')
          reader?.cancel()
        }
      }, 10000)

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          lastEventTime = Date.now()
          buffer += decoder.decode(value, { stream: true })

          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let currentEvent = ''
          for (const line of lines) {
            // v4.35: Handle heartbeat comments
            if (line.startsWith(': heartbeat') || line === ':') {
              continue
            }
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (currentEvent === 'heartbeat') {
                  // Internal heartbeat event — skip callback
                  continue
                }
                onEvent(currentEvent, data)
                if (currentEvent === 'done' && data.result) {
                  finalResult = data.result as AgentResponseV434
                }
              } catch {
                // Skip malformed SSE data
              }
            }
          }
        }
      } finally {
        clearInterval(heartbeatWatchdog)
      }

      if (!finalResult) {
        throw new Error('Stream ended without final result')
      }
      return finalResult
    } catch (err: unknown) {
      retries++
      if (retries <= MAX_RECONNECT_RETRIES) {
        const delay = Math.pow(2, retries - 1) * 1000
        console.warn(
          `[SSE] Stream error, reconnecting in ${delay}ms (attempt ${retries}/${MAX_RECONNECT_RETRIES})...`,
        )
        onEvent('reconnecting', {
          attempt: retries,
          maxRetries: MAX_RECONNECT_RETRIES,
          delayMs: delay,
        })
        await new Promise((r) => setTimeout(r, delay))
        continue
      }
      // R6.57: with `err: unknown`, narrow to Error shape before reading .message
      const underlyingMsg =
        err instanceof Error && err.message ? err.message : String(err)
      // Preserve the real error, don't mask it with "code: 0"
      throw new Error(
        underlyingMsg ||
          `AI stream failed after ${MAX_RECONNECT_RETRIES} retries`,
      )
    }
  }
}

// v4.34: Research-friendly error messages (Fix #13)
function mapErrorCode(status: number, _body?: string): string {
  const messages: Record<number, string> = {
    400: 'Request format error. Please check your input and try again.',
    401: 'Authentication failed. Please contact the platform administrator to check the API key configuration.',
    429: 'API request quota exhausted (daily limit reached). Please retry after UTC midnight, or switch to offline mode.',
    502: 'AI service temporarily unreachable. The platform will automatically use local keyword matching.',
    503: 'AI service not configured. Please configure the API key in Settings first.',
    504: 'AI response timed out (>5 minutes). Please try simplifying your question or reducing the data query scope.',
  }
  return (
    messages[status] ||
    `Service error (code: ${status}). Please try again or contact the administrator.`
  )
}

// v4.34: Updated chatWithAgent with session support + verification
export async function chatWithAgentV434(
  messages: ChatMessage[],
  options?: { max_tool_rounds?: number; temperature?: number },
): Promise<AgentResponseV434> {
  try {
    const response = await agentAxios.post(
      '/pipeline/agent/chat',
      {
        messages,
        max_tool_rounds: options?.max_tool_rounds ?? 10,
        temperature: options?.temperature ?? 0.3,
      },
      {
        timeout: 300000, // 5 min
      },
    )

    const data = response.data as AgentResponseV434

    if (!data?.success) {
      throw new Error(data?.error || 'Agent execution failed')
    }
    return data
  } catch (error: unknown) {
    const err = error as AxiosError<{ error?: string }>
    const status = err.response?.status || 0
    throw new Error(mapErrorCode(status))
  }
}
