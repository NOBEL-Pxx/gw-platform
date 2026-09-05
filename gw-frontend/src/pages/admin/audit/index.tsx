import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import axios from 'axios'

interface AuditEntry {
  _id: string
  timestamp: string
  session_id: string
  action: string
  input_length: number
  compliance_level: string
  user_role: string
  ip_hash: string
}

interface AuditStats {
  success: boolean
  today_requests?: number
  blocked_injections?: number
  active_users?: number
  pending_alerts?: number
  role_breakdown?: Record<string, number>
}

interface Alert {
  _id: string
  level: string
  type: string
  detail: string
  timestamp: string
  acknowledged: boolean
}

const token = () => localStorage.getItem('gw_auth_token') || ''

const auditApi = axios.create({
  timeout: 10000,
  headers: { common: { Authorization: `Bearer ${token()}` } },
})
auditApi.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem('gw_auth_token') || ''}`
  return config
})

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleString()
  } catch {
    return ts
  }
}

export default function AdminAuditPage() {
  const { user } = useAuth()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [stats, setStats] = useState<AuditStats>({ success: false })
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [filterAction, setFilterAction] = useState('')

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await auditApi.get('/pipeline/admin/audit/stats')
      setStats(data)
    } catch (e) {
      console.warn('Stats fetch failed', e)
    }
  }, [])

  const fetchAlerts = useCallback(async () => {
    try {
      const { data } = await auditApi.get('/pipeline/admin/audit/alerts')
      setAlerts(data.alerts || [])
    } catch (e) {
      console.warn('Alerts fetch failed', e)
    }
  }, [])

  const fetchLogs = useCallback(
    async (p: number) => {
      setLoading(true)
      try {
        const params: Record<string, unknown> = { page: p, page_size: 50 }
        if (filterAction) params.action = filterAction
        const { data } = await auditApi.get('/pipeline/admin/audit/logs', {
          params,
        })
        setEntries(data.entries || [])
        setTotal(data.total || 0)
      } catch (e) {
        console.warn('Logs fetch failed', e)
      }
      setLoading(false)
    },
    [filterAction],
  )

  useEffect(() => {
    fetchStats()
    fetchAlerts()
  }, [fetchStats, fetchAlerts])

  useEffect(() => {
    fetchLogs(page)
  }, [page, fetchLogs])

  if (user?.role !== 'admin') {
    return (
      <div
        style={{
          padding: 60,
          textAlign: 'center',
          color: '#E4002B',
          fontFamily: 'monospace',
        }}
      >
        <h2 style={{ fontSize: 24, marginBottom: 12 }}>Access Denied</h2>
        <p style={{ color: '#8899aa' }}>
          Admin role required. Your role: {user?.role || 'anonymous'}
        </p>
      </div>
    )
  }

  const totalPages = Math.ceil(total / 50)

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#000000',
        color: '#00E676',
        fontFamily: "'IBM Plex Mono', 'JetBrains Mono', monospace",
        padding: 32,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 32,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 700,
              margin: 0,
              letterSpacing: 2,
            }}
          >
            AUDIT • LOGS
          </h1>
          <p style={{ color: '#888', fontSize: 12, margin: '4px 0 0' }}>
            v4.35 Compliance Dashboard — {user?.username || 'admin'}@gw-pipeline
          </p>
        </div>
        <div style={{ fontSize: 11, color: '#555', textAlign: 'right' }}>
          UTC {new Date().toISOString().slice(0, 19).replace('T', ' ')}
        </div>
      </div>

      {/* Stats Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
          marginBottom: 32,
        }}
      >
        {[
          {
            label: 'Today Requests',
            value: stats.today_requests ?? '—',
            color: '#00E676',
          },
          {
            label: 'Blocked Injections',
            value: stats.blocked_injections ?? '—',
            color: '#FF3B30',
          },
          {
            label: 'Active Users',
            value: stats.active_users ?? '—',
            color: '#FFB800',
          },
          {
            label: 'Pending Alerts',
            value: stats.pending_alerts ?? '—',
            color: stats.pending_alerts ? '#FF3B30' : '#00E676',
          },
        ].map((card) => (
          <div
            key={card.label}
            style={{
              border: '1px solid #1a1a1a',
              padding: '20px 16px',
              background: '#0a0a0a',
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: '#666',
                marginBottom: 8,
                textTransform: 'uppercase',
                letterSpacing: 1,
              }}
            >
              {card.label}
            </div>
            <div
              style={{
                fontSize: 36,
                fontWeight: 700,
                color: card.color,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {card.value}
            </div>
          </div>
        ))}
      </div>

      {/* Alerts Panel */}
      {alerts.filter((a) => !a.acknowledged).length > 0 && (
        <div
          style={{
            marginBottom: 32,
            border: '1px solid #FF3B30',
            background: '#1a0000',
            padding: 16,
          }}
        >
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: '#FF3B30',
              marginBottom: 12,
              textTransform: 'uppercase',
              letterSpacing: 2,
            }}
          >
            ⚠ Active Alerts ({alerts.filter((a) => !a.acknowledged).length})
          </div>
          {alerts
            .filter((a) => !a.acknowledged)
            .map((alert) => (
              <div
                key={alert._id}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid #1a0000',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '2px 8px',
                      marginRight: 8,
                      background:
                        alert.level === 'CRITICAL' ? '#FF3B30' : '#FFB800',
                      color: '#000',
                      fontSize: 10,
                      fontWeight: 700,
                    }}
                  >
                    {alert.level}
                  </span>
                  <span style={{ color: '#aaa', fontSize: 12 }}>
                    {alert.type}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: '#666',
                    maxWidth: '50%',
                    textAlign: 'right',
                  }}
                >
                  {alert.detail}
                </div>
                <div style={{ fontSize: 10, color: '#444' }}>
                  {formatTime(alert.timestamp)}
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <select
          value={filterAction}
          onChange={(e) => {
            setFilterAction(e.target.value)
            setPage(1)
          }}
          style={{
            background: '#0a0a0a',
            color: '#00E676',
            border: '1px solid #1a1a1a',
            padding: '6px 12px',
            fontFamily: 'inherit',
            fontSize: 12,
          }}
        >
          <option value=''>All Actions</option>
          <option value='agent_chat'>agent_chat</option>
          <option value='injection_blocked'>injection_blocked</option>
          <option value='quota_exceeded'>quota_exceeded</option>
          <option value='llm_chat'>llm_chat</option>
        </select>
        <button
          onClick={() => {
            fetchStats()
            fetchAlerts()
            fetchLogs(page)
          }}
          style={{
            background: '#0a0a0a',
            color: '#00E676',
            border: '1px solid #1a1a1a',
            padding: '6px 16px',
            fontFamily: 'inherit',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          ↻ Refresh
        </button>
      </div>

      {/* Log Table */}
      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 11,
            border: '1px solid #1a1a1a',
          }}
        >
          <thead>
            <tr style={{ background: '#0a0a0a', textAlign: 'left' }}>
              {[
                'Time',
                'Session',
                'Action',
                'Role',
                'Compliance',
                'IP Hash',
                'Input Len',
              ].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: '10px 12px',
                    borderBottom: '1px solid #1a1a1a',
                    color: '#666',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td
                  colSpan={7}
                  style={{ padding: 40, textAlign: 'center', color: '#444' }}
                >
                  Loading...
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  style={{ padding: 40, textAlign: 'center', color: '#444' }}
                >
                  No audit entries found
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <tr
                  key={entry._id}
                  style={{ borderBottom: '1px solid #0a0a0a' }}
                >
                  <td
                    style={{
                      padding: '8px 12px',
                      color: '#888',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {formatTime(entry.timestamp)}
                  </td>
                  <td
                    style={{
                      padding: '8px 12px',
                      color: '#555',
                      fontFamily: 'monospace',
                    }}
                  >
                    {entry.session_id?.slice(0, 12) || '—'}...
                  </td>
                  <td style={{ padding: '8px 12px' }}>
                    <span
                      style={{
                        color:
                          entry.action === 'injection_blocked'
                            ? '#FF3B30'
                            : '#00E676',
                      }}
                    >
                      {entry.action}
                    </span>
                  </td>
                  <td style={{ padding: '8px 12px', color: '#aaa' }}>
                    {entry.user_role || '—'}
                  </td>
                  <td style={{ padding: '8px 12px' }}>
                    <span
                      style={{
                        padding: '1px 6px',
                        background:
                          entry.compliance_level === 'strict'
                            ? '#FF3B3022'
                            : entry.compliance_level === 'moderate'
                              ? '#FFB80022'
                              : '#00E67622',
                        color:
                          entry.compliance_level === 'strict'
                            ? '#FF3B30'
                            : entry.compliance_level === 'moderate'
                              ? '#FFB800'
                              : '#00E676',
                        fontSize: 10,
                      }}
                    >
                      {entry.compliance_level}
                    </span>
                  </td>
                  <td
                    style={{
                      padding: '8px 12px',
                      color: '#555',
                      fontFamily: 'monospace',
                      fontSize: 10,
                    }}
                  >
                    {entry.ip_hash || '—'}
                  </td>
                  <td
                    style={{
                      padding: '8px 12px',
                      color: '#888',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {entry.input_length}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            gap: 8,
            marginTop: 16,
          }}
        >
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            style={{
              background: '#0a0a0a',
              color: page <= 1 ? '#333' : '#00E676',
              border: '1px solid #1a1a1a',
              padding: '6px 16px',
              fontFamily: 'inherit',
              cursor: page <= 1 ? 'default' : 'pointer',
            }}
          >
            Prev
          </button>
          <span style={{ color: '#666', alignSelf: 'center', fontSize: 12 }}>
            {page} / {totalPages} ({total} total)
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            style={{
              background: '#0a0a0a',
              color: page >= totalPages ? '#333' : '#00E676',
              border: '1px solid #1a1a1a',
              padding: '6px 16px',
              fontFamily: 'inherit',
              cursor: page >= totalPages ? 'default' : 'pointer',
            }}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
