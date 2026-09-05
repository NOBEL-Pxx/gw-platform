import { useState, useMemo } from 'react'
import { Card, Empty, Segmented, Tag, Typography } from 'antd'
import LineChartOutlined from '@ant-design/icons/LineChartOutlined'
import DotChartOutlined from '@ant-design/icons/DotChartOutlined'
import CalendarOutlined from '@ant-design/icons/CalendarOutlined'
import ExperimentOutlined from '@ant-design/icons/ExperimentOutlined'

const { Text, Title, Paragraph } = Typography

// v4.32.1 — force fresh bundle deploy (2026-07-30T07:17:00Z)
const BUILD_TAG = 'v4.32.1-tod-fix'

// v4.32: AliCPT Time-Ordered Data (TOD) Viewer
// Data not yet available — placeholder UI with expected structure.
//
// AliCPT-1 observes at 150 GHz with ~20,000 TES bolometers.
// TOD is the raw time-stream: detector response vs time,
// typically sampled at 100 Hz over hours-long scans.
// This viewer will display:
//   - Per-detector time series
//   - Power spectral density (PSD)
//   - Scan-synchronous signal extraction
//   - Noise equivalent temperature (NET) estimation

interface TODSession {
  id: string
  date: string
  duration_hours: number
  n_detectors: number
  sampling_hz: number
  status: 'available' | 'pending' | 'processing'
  notes?: string
}

const MOCK_SESSIONS: TODSession[] = [
  {
    id: 'ALICPT-2026-001',
    date: '2026-01-15',
    duration_hours: 2.5,
    n_detectors: 20480,
    sampling_hz: 100,
    status: 'pending',
    notes: '待导入',
  },
  {
    id: 'ALICPT-2026-002',
    date: '2026-02-03',
    duration_hours: 4.0,
    n_detectors: 20480,
    sampling_hz: 100,
    status: 'pending',
    notes: '待导入',
  },
  {
    id: 'ALICPT-2026-003',
    date: '2026-03-22',
    duration_hours: 6.0,
    n_detectors: 20480,
    sampling_hz: 100,
    status: 'pending',
    notes: '待导入',
  },
]

const CHART_PLACEHOLDER = (
  <div
    style={{
      width: '100%',
      height: 280,
      background: 'rgba(0,240,255,0.03)',
      border: '1px dashed rgba(0,240,255,0.15)',
      borderRadius: 12,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    }}
  >
    <LineChartOutlined
      style={{ fontSize: 40, color: 'rgba(0,240,255,0.25)' }}
    />
    <Text className='text-white/40 text-sm'>TOD Time Series</Text>
    <Text className='text-white/25 text-xs'>
      Data pending — will render detector timestream here
    </Text>
  </div>
)

function TODSessionCard({ session }: { session: TODSession }) {
  return (
    <Card
      size='small'
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 12,
        marginBottom: 12,
      }}
      styles={{ body: { padding: '14px 16px' } }}
    >
      <div className='flex items-center justify-between mb-3'>
        <div className='flex items-center gap-2'>
          <CalendarOutlined style={{ color: '#00F0FF', fontSize: 16 }} />
          <Text className='text-white/85 font-semibold text-sm'>
            {session.id}
          </Text>
        </div>
        <Tag
          color={
            session.status === 'available'
              ? 'green'
              : session.status === 'processing'
                ? 'blue'
                : 'default'
          }
        >
          {session.status.toUpperCase()}
        </Tag>
      </div>

      <div className='grid grid-cols-2 md:grid-cols-4 gap-3 mb-3'>
        {[
          ['Date', session.date],
          ['Duration', `${session.duration_hours}h`],
          ['Detectors', session.n_detectors.toLocaleString()],
          ['Sampling', `${session.sampling_hz} Hz`],
        ].map(([label, value]) => (
          <div key={label as string}>
            <Text className='text-white/40 text-xs block'>{label}</Text>
            <Text className='text-white/75 text-sm font-semibold'>{value}</Text>
          </div>
        ))}
      </div>

      {session.notes && (
        <Text className='text-white/35 text-xs italic'>{session.notes}</Text>
      )}

      {/* Time-series chart placeholder */}
      {CHART_PLACEHOLDER}

      {/* Quick stats row */}
      <div className='flex gap-3 mt-3'>
        {['PSD', 'NET', 'SSS', 'Glitch'].map((stat) => (
          <div
            key={stat}
            className='flex-1 rounded-lg text-center py-2'
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.05)',
            }}
          >
            <Text className='text-white/30 text-xs block'>{stat}</Text>
            <Text className='text-white/20 text-xs'>—</Text>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function TODPage() {
  const [filterStatus, setFilterStatus] = useState<string>('all')

  const filteredSessions = useMemo(() => {
    if (filterStatus === 'all') return MOCK_SESSIONS
    return MOCK_SESSIONS.filter((s) => s.status === filterStatus)
  }, [filterStatus])

  return (
    <div className='h-full overflow-auto' style={{ background: 'transparent' }}>
      <div className='max-w-4xl mx-auto p-6 space-y-4'>
        {/* Header */}
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-3'>
            <DotChartOutlined className='text-aurora-cyan text-2xl' />
            <div>
              <Title
                level={3}
                className='!mb-0 !text-white/90'
                style={{ fontWeight: 700 }}
              >
                AliCPT TOD Viewer
              </Title>
              <Text className='text-white/40 text-xs'>
                Time-Ordered Data — bolometer timestreams from AliCPT-1 (150
                GHz, 20,480 detectors)
              </Text>
            </div>
          </div>
          <Tag color='warning' className='font-semibold'>
            DATA PENDING
          </Tag>
        </div>

        {/* Info banner */}
        <Card
          size='small'
          style={{
            background: 'rgba(0,240,255,0.04)',
            border: '1px solid rgba(0,240,255,0.12)',
            borderRadius: 12,
          }}
          styles={{ body: { padding: '12px 16px' } }}
        >
          <div className='flex items-start gap-3'>
            <ExperimentOutlined
              style={{ color: '#00F0FF', fontSize: 18, marginTop: 2 }}
            />
            <div>
              <Text className='text-white/75 text-sm font-semibold block'>
                AliCPT & Planck CMB Time-Ordered Data
              </Text>
              <Paragraph
                className='!mb-0 !mt-1 text-xs text-white/45'
                style={{ lineHeight: 1.6 }}
              >
                TOD is the fundamental raw data product of CMB experiments — the
                detector-by-detector time stream recorded during sky scans.
                AliCPT-1 observes at 150 GHz with ~20,000 transition-edge sensor
                (TES) bolometers sampling at 100 Hz. Planck covered 30–857 GHz
                across 9 frequency bands. Data will be imported as it becomes
                available from the collaboration.
              </Paragraph>
            </div>
          </div>
        </Card>

        {/* Session list */}
        <div className='flex items-center justify-between'>
          <Text className='text-white/60 text-sm font-semibold'>
            Observation Sessions ({filteredSessions.length})
          </Text>
          <Segmented
            size='small'
            value={filterStatus}
            onChange={(v) => setFilterStatus(v as string)}
            options={[
              { label: 'All', value: 'all' },
              { label: 'Pending', value: 'pending' },
              { label: 'Processing', value: 'processing' },
              { label: 'Available', value: 'available' },
            ]}
          />
        </div>

        {filteredSessions.length > 0 ? (
          filteredSessions.map((s) => <TODSessionCard key={s.id} session={s} />)
        ) : (
          <Empty description='No matching sessions' />
        )}

        {/* Footer note */}
        <div className='text-center pt-4 pb-6'>
          <Text className='text-white/25 text-xs'>
            AliCPT TOD Viewer v4.32 · Data import pending · Planck
            multi-frequency support ready · {BUILD_TAG}
          </Text>
        </div>
      </div>
    </div>
  )
}
