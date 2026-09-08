import { Card, Tag, Typography, Tooltip } from 'antd'
import LogoFade from '@/components/LogoFade'
import {
  BankOutlined,
  BookOutlined,
  CheckCircleOutlined,
  CloudOutlined,
  CodeOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  EyeOutlined,
  GlobalOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  StarOutlined,
  TeamOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography

const FEATURES = [
  {
    icon: <CloudOutlined />,
    title: 'HiPS-Float True DS9 Quality',
    desc: 'PNG tiles via /pipeline/hips-float. Raw 32-bit FITS + Floyd-Steinberg dither.',
    color: '#00E676',
  },
  {
    icon: <EyeOutlined />,
    title: 'Per-Channel RGB Cut',
    desc: 'Drag any component slider to RGB composite re-renders. Auto Hi-Q for W/K/J/H.',
    color: '#00F0FF',
  },
  {
    icon: <SafetyCertificateOutlined />,
    title: 'Audit Log + PKCS#7 Sign',
    desc: 'Mongo-backed audit with cursor pagination + RSA-2048 signed PDF batch verify.',
    color: '#7C3AED',
  },
  {
    icon: <ExperimentOutlined />,
    title: 'GW x EM Follow-up',
    desc: 'Gravitational-wave events cross-referenced with electromagnetic observations.',
    color: '#FFB800',
  },
  {
    icon: <StarOutlined />,
    title: 'AI Chat + FITS Q&A',
    desc: 'DeepSeek-V4 - 500 req/day - upload FITS for visual Q&A + header context.',
    color: '#FA8C16',
  },
  {
    icon: <RocketOutlined />,
    title: 'Mobile-First UX',
    desc: 'Single-row AI chat, fullscreen viewer, touch-friendly nav. Landing fits 1 viewport.',
    color: '#FF006E',
  },
]

const DATA_INVENTORY = [
  { survey: 'AliCPT-1', bands: '150 GHz', color: '#00F0FF', files: 12 },
  { survey: 'DSS2', bands: 'B/G/R', color: '#00E676', files: 36 },
  { survey: '2MASS', bands: 'J/H/K', color: '#FA8C16', files: 36 },
  { survey: 'allWISE', bands: 'W1/W2/W4', color: '#FF006E', files: 36 },
  { survey: 'LEGACY', bands: 'g/r/i/z', color: '#00E676', files: 48, note: 'pending' },
  { survey: 'NVSS', bands: '1.4 GHz', color: '#7C3AED', files: 12 },
]

const STACK_GROUPS = [
  { label: 'Frontend', items: 'React 18 - TS 5 - Vite 8 - Ant Design 5.22 - Tailwind 3.4' },
  { label: 'Backend', items: 'Spring Boot 3.4 - Java 21 - ES 7.17 - MongoDB 6 - jjwt' },
  { label: 'Pipeline', items: 'Python 3.12 - FastAPI - Astropy - Photutils - NumPy - Matplotlib' },
  { label: 'AI / Viz', items: 'DeepSeek-V4 - IPAC Firefly - Aladin Lite v3 - MCP SDK' },
]

const AI_SERVICES = [
  { name: 'LLM Chat Engine', desc: 'DeepSeek-V4 - SHA-256 cache - 500/day quota - audit log', status: 'live' },
  { name: 'Photometry Compare', desc: 'Multi-FITS flux extraction - aperture photometry', status: 'live' },
  { name: 'Anomaly Detector', desc: 'Statistical + DL - spike / dip / pattern / WCS', status: 'paused' },
  { name: 'Galaxy Morphology', desc: 'Zoobot ConvNeXt-Nano (ONNX) - 5-class classifier', status: 'live' },
]

const CONTACTS = [
  { org: 'NAOC', role: 'National Astronomical Observatories - CAS', icon: <BankOutlined /> },
  { org: 'Zhejiang Lab', role: '\u4e4b\u6c5f\u5b9e\u9a8c\u5ba4 - Intelligent Computing', icon: <ExperimentOutlined /> },
  { org: 'LZU', role: 'Lanzhou University - Atmospheric Sciences', icon: <BookOutlined /> },
  { org: 'UCAS', role: 'University of CAS - Innovation Practice Program', icon: <TeamOutlined /> },
]

const cardStyle = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 14,
} as const

const cardHeaderStyle = { borderColor: 'rgba(255,255,255,0.06)' }
const cardBodyStyle = { padding: '14px 20px' }

function StatusTag({ status }: { status: string }) {
  const cfg: Record<string, { color: string; label: string; icon: any }> = {
    live: { color: 'green', label: 'LIVE', icon: <CheckCircleOutlined /> },
    paused: { color: 'default', label: 'PAUSED', icon: null },
  }
  const c = cfg[status] || { color: 'default', label: status, icon: null }
  return (
    <Tag color={c.color} icon={c.icon} className='font-semibold' style={{ margin: 0 }}>
      {c.label}
    </Tag>
  )
}

export default function SettingsPage() {
  // R6.77: dynamic Access URL (VITE env > window.location.origin > localhost)
  const accessUrl = (import.meta as any).env?.VITE_PUBLIC_BASE_URL
    || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:6002')
  const accessUrlNote = accessUrl.includes('localhost:6002')
    ? 'local dev'
    : accessUrl.includes('alicpt.lhr.life')
      ? 'canonical'
      : 'this server'

  return (
    <div
      className='h-full overflow-auto'
      style={{
        background:
          'radial-gradient(ellipse at top, rgba(0,240,255,0.06) 0%, transparent 60%), radial-gradient(ellipse at bottom right, rgba(124,58,237,0.04) 0%, transparent 50%)',
      }}
    >
      <div className='max-w-3xl mx-auto p-6 space-y-4'>
        {/* ============ Header ============ */}
        <div className='flex items-center gap-4 pb-2'>
          <Tooltip title='AliCPT Logo'>
            <LogoFade size={64} alt='AliCPT Logo' className='!mb-0' />
          </Tooltip>
          <div className='flex-1'>
            <div className='flex items-center gap-2'>
              <Title level={3} className='!mb-0 !text-white/90' style={{ fontWeight: 700 }}>
                AliCPT DIVS
              </Title>
              <Tag color='cyan' className='font-semibold' style={{ margin: 0 }}>
                v4.63+R6.83
              </Tag>
            </div>
            <Text className='text-white/50 text-sm'>Astronomical Data Platform</Text>
          </div>
          <SettingOutlined className='text-aurora-cyan text-xl opacity-60' />
        </div>

        {/* ============ Access ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><GlobalOutlined className='mr-2' />Access</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='flex items-center gap-3'>
            <code
              className='flex-1 truncate'
              style={{
                background: 'rgba(255,255,255,0.05)',
                padding: '6px 12px',
                borderRadius: 6,
                color: '#00F0FF',
                fontSize: 13,
                fontFamily: 'ui-monospace, monospace',
              }}
            >
              {accessUrl}
            </code>
            <Tag color='default' style={{ margin: 0 }}>{accessUrlNote}</Tag>
          </div>
        </Card>

        {/* ============ Recent Features ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><StarOutlined className='mr-2' />Recent Features</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='grid grid-cols-1 sm:grid-cols-2 gap-3'>
            {FEATURES.map((f) => (
              <div key={f.title} className='flex items-start gap-3'>
                <div
                  className='w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0'
                  style={{ background: `${f.color}1A`, color: f.color }}
                >
                  {f.icon}
                </div>
                <div className='min-w-0'>
                  <Text className='text-white/85 font-semibold text-xs block'>{f.title}</Text>
                  <Text className='text-white/50 text-xs'>{f.desc}</Text>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* ============ Data Inventory ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><DatabaseOutlined className='mr-2' />Data Inventory - 180 FITS - 15 bands</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='grid grid-cols-2 sm:grid-cols-3 gap-2'>
            {DATA_INVENTORY.map((d) => (
              <div
                key={d.survey}
                className='flex items-center justify-between rounded-md px-3 py-2'
                style={{ background: 'rgba(255,255,255,0.03)' }}
              >
                <div className='min-w-0'>
                  <Text className='text-white/85 text-xs font-semibold block truncate'>{d.survey}</Text>
                  <Text className='text-white/45 text-xs font-mono'>{d.bands}</Text>
                </div>
                <Tag color={d.color} style={{ margin: 0, fontSize: 10 }}>
                  {d.files}
                </Tag>
              </div>
            ))}
          </div>
          <Text className='text-white/40 text-xs mt-3 block'>
            LEGACY pending re-export - Planck pending ingest - 7 surveys total
          </Text>
        </Card>

        {/* ============ Tech Stack ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><CodeOutlined className='mr-2' />Tech Stack</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3'>
            {STACK_GROUPS.map((g) => (
              <div key={g.label}>
                <Text className='text-aurora-cyan text-xs font-semibold uppercase tracking-wider'>
                  {g.label}
                </Text>
                <Text className='text-white/70 text-xs block mt-0.5' style={{ lineHeight: 1.6 }}>
                  {g.items}
                </Text>
              </div>
            ))}
          </div>
          <Text className='text-white/40 text-xs mt-3 block'>
            7 Docker containers - Nginx HTTPS/TLS 1.3 - HSTS - MCP SDK
          </Text>
        </Card>

        {/* ============ AI Models Status ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><ExperimentOutlined className='mr-2' />AI Models</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3'>
            {AI_SERVICES.map((s) => (
              <div key={s.name} className='flex items-center justify-between'>
                <div className='min-w-0'>
                  <Text className='text-white/85 font-semibold text-xs block'>{s.name}</Text>
                  <Text className='text-white/50 text-xs'>{s.desc}</Text>
                </div>
                <StatusTag status={s.status} />
              </div>
            ))}
          </div>
        </Card>

        {/* ============ Contact & Team ============ */}
        <Card
          title={<span className='text-white/85 font-semibold text-sm'><TeamOutlined className='mr-2' />Contact & Team</span>}
          style={cardStyle} styles={{ header: cardHeaderStyle, body: cardBodyStyle }}
        >
          <div className='grid grid-cols-1 sm:grid-cols-2 gap-3'>
            {CONTACTS.map((c) => (
              <div key={c.org} className='flex items-start gap-3'>
                <div
                  className='w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0'
                  style={{ background: 'rgba(0,240,255,0.10)', color: '#00F0FF' }}
                >
                  {c.icon}
                </div>
                <div className='min-w-0'>
                  <Text className='text-white/85 font-semibold text-sm block'>{c.org}</Text>
                  <Text className='text-white/50 text-xs'>{c.role}</Text>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* ============ Footer ============ */}
        <div className='text-center pt-1 pb-4'>
          <Text className='text-white/35 text-xs'>
            AliCPT DIVS v4.63+R6.83 - Built with Aurora - (c) 2026
          </Text>
        </div>
      </div>
    </div>
  )
}
