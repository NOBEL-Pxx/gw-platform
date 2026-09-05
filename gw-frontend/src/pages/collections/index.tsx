import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  List,
  Tag,
  Tooltip,
  message as antMsg,
} from 'antd'
import AlertOutlined from '@ant-design/icons/AlertOutlined'
import SendOutlined from '@ant-design/icons/SendOutlined'
import CopyOutlined from '@ant-design/icons/CopyOutlined'
import { getErrorReports, postComment } from '@/service'
import { useAuth } from '@/contexts/AuthContext'
import { ErrorReportItem } from '@/types/api'

export default function AlertPage() {
  const { user } = useAuth()
  const [reports, setReports] = useState<ErrorReportItem[]>([])
  const [loading, setLoading] = useState(true)
  const [sendingId, setSendingId] = useState<string | null>(null)

  const fetchReports = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getErrorReports({ page: 1, page_size: 50 })
      setReports(res.data?.list || [])
    } catch {
      /* handled by interceptor */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchReports()
  }, [fetchReports])

  const fmt = (v: unknown): string =>
    Array.isArray(v) ? v.join(', ') : String(v ?? '-')

  const buildAlertText = (item: ErrorReportItem) =>
    [
      '⚠️ AliCPT DIVS 异常告警',
      `Error ID: ${item.error_id}`,
      `异常类型: ${fmt(item.anomaly_type)}`,
      `波段: ${item.band || '-'}`,
      `望远镜: ${item.telescope || '-'}`,
      `RA: ${fmt(item.rafield)}`,
      `Dec: ${fmt(item.decfield)}`,
      `时间: ${item.start_date || '-'} ~ ${item.end_date || '-'}`,
    ].join('\n')

  const handleSend = async (item: ErrorReportItem) => {
    if (!user) {
      antMsg.warning('Login to send alerts')
      return
    }
    const text = buildAlertText(item)
    setSendingId(item.error_id)
    try {
      let copied = false
      try {
        await navigator.clipboard.writeText(text)
        copied = true
      } catch {
        /* clipboard unavailable — fall through to comment record */
      }
      // v4.DIVS: dual-broadcast — private "alert" + public "public-alert"
      await postComment({
        grawaveId: item.error_id,
        content: text,
        userId: user.userId,
        category: 'alert',
      })
      await postComment({
        grawaveId: item.error_id,
        content: text,
        userId: user.userId,
        category: 'public-alert',
      })
      antMsg.success(
        copied
          ? 'Alert sent (private + public)'
          : 'Alert sent (private + public)',
      )
    } catch {
      antMsg.error('Failed to send alert')
    } finally {
      setSendingId(null)
    }
  }

  if (!user) {
    return (
      <div className='flex items-center justify-center h-full'>
        <Empty description='Login to send alerts' />
      </div>
    )
  }

  return (
    <div className='p-6 max-w-5xl mx-auto'>
      <div className='mb-4'>
        <h1 className='text-2xl font-bold text-white/90 flex items-center gap-2'>
          <AlertOutlined className='text-aurora-cyan' /> Alert
        </h1>
        <p className='text-white/50 text-sm'>
          Send key abnormal data to the team with one click
        </p>
      </div>

      {loading ? (
        <div className='text-center py-12 text-white/40'>Loading...</div>
      ) : reports.length === 0 ? (
        <Empty description='No abnormal data reports yet.' className='mt-12' />
      ) : (
        <List
          grid={{ gutter: 16, xs: 1, sm: 1, lg: 2 }}
          dataSource={reports}
          renderItem={(item: ErrorReportItem) => (
            <List.Item>
              <Card
                className='!border-white/10 !bg-white/[0.03]'
                title={
                  <span className='text-white/85 font-mono text-sm'>
                    {item.error_id}
                  </span>
                }
                extra={<Tag color='red'>Abnormal</Tag>}
              >
                <div className='space-y-1 text-sm text-white/55'>
                  <div>
                    Type:{' '}
                    <span className='text-white/85'>
                      {fmt(item.anomaly_type)}
                    </span>
                  </div>
                  <div>
                    Band:{' '}
                    <span className='text-white/85'>{item.band || '-'}</span>
                  </div>
                  <div>
                    Telescope:{' '}
                    <span className='text-white/85'>
                      {item.telescope || '-'}
                    </span>
                  </div>
                  <div>
                    Time:{' '}
                    <span className='text-white/85'>
                      {item.start_date || '-'} ~ {item.end_date || '-'}
                    </span>
                  </div>
                </div>
                <div className='mt-3 flex gap-2'>
                  <Button
                    type='primary'
                    size='small'
                    icon={<SendOutlined />}
                    loading={sendingId === item.error_id}
                    onClick={() => handleSend(item)}
                  >
                    Send Alert
                  </Button>
                  <Tooltip title='Copy alert text'>
                    <Button
                      size='small'
                      icon={<CopyOutlined />}
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(
                            buildAlertText(item),
                          )
                          antMsg.success('Copied')
                        } catch {
                          antMsg.warning('Clipboard unavailable')
                        }
                      }}
                    />
                  </Tooltip>
                </div>
              </Card>
            </List.Item>
          )}
        />
      )}
    </div>
  )
}
