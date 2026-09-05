import { Card, Descriptions, Tag, Typography, Divider } from 'antd'
import SettingOutlined from '@ant-design/icons/SettingOutlined'
import TeamOutlined from '@ant-design/icons/TeamOutlined'
import BankOutlined from '@ant-design/icons/BankOutlined'
import ExperimentOutlined from '@ant-design/icons/ExperimentOutlined'
import CodeOutlined from '@ant-design/icons/CodeOutlined'
import CheckCircleOutlined from '@ant-design/icons/CheckCircleOutlined'
import StarOutlined from '@ant-design/icons/StarOutlined'
import DatabaseOutlined from '@ant-design/icons/DatabaseOutlined'
import CloudUploadOutlined from '@ant-design/icons/CloudUploadOutlined'
import SafetyCertificateOutlined from '@ant-design/icons/SafetyCertificateOutlined'
import EyeOutlined from '@ant-design/icons/EyeOutlined'
import BookOutlined from '@ant-design/icons/BookOutlined'
import MenuOutlined from '@ant-design/icons/MenuOutlined'

const { Title, Text, Paragraph } = Typography

const TECH_STACK = [
  {
    category: 'Frontend',
    items:
      'React 18 · TypeScript 5 · Ant Design 5.22 · Tailwind CSS 3.4 · Vite 5.4',
  },
  {
    category: 'Backend',
    items:
      'Spring Boot 3.4.1 · Java 21 · Elasticsearch 7.17 · MongoDB 6.0 · Bucket4j · jjwt 0.12.6',
  },
  {
    category: 'Pipeline',
    items:
      'Python 3.12 · FastAPI · Astropy · Photutils · NumPy · SciPy · Matplotlib',
  },
  {
    category: 'AI / LLM',
    items:
      'DeepSeek-V4 · SHA-256 query cache · 500 req/day quota · Audit logging',
  },
  {
    category: 'Visualization',
    items: 'IPAC Firefly · Aladin Lite v3 · Matplotlib · SNR heatmap',
  },
  {
    category: 'Infrastructure',
    items:
      'Docker Compose · Nginx HTTPS/TLS 1.3 · HSTS · MCP SDK · 7 containers',
  },
]

const CONTACTS = [
  {
    role: 'Development Team',
    name: 'AliCPT DIVS Contributors',
    org: 'Lanzhou University',
    icon: <TeamOutlined />,
  },
  {
    role: 'Institution',
    name: 'National Astronomical Observatories',
    org: 'Chinese Academy of Sciences (NAOC)',
    icon: <BankOutlined />,
  },
  {
    role: 'Collaborator',
    name: 'Zhejiang Lab (之江实验室)',
    org: 'Research Institute for Intelligent Computing',
    icon: <BankOutlined />,
  },
  {
    role: 'Program',
    name: 'Innovation Practice Training Program',
    org: 'University of Chinese Academy of Sciences (UCAS)',
    icon: <ExperimentOutlined />,
  },
]

const DATA_INVENTORY = [
  {
    survey: 'AliCPT-1',
    files: 12,
    bands: '150 GHz',
    wavelength: 'mm-wave',
    wavelengthColor: '#00F0FF',
    size: '100 KB',
  },
  {
    survey: 'Planck',
    files: 0,
    bands: '30–857 GHz',
    wavelength: 'mm-wave',
    wavelengthColor: '#FFB800',
    size: '—',
    note: '待导入',
  },
  {
    survey: 'DSS2',
    files: 36,
    bands: 'Blue / Green / Red',
    wavelength: 'optical',
    wavelengthColor: '#00E676',
    size: '78 MB',
  },
  {
    survey: '2MASS',
    files: 36,
    bands: 'J / H / K',
    wavelength: 'near-IR',
    wavelengthColor: '#FA8C16',
    size: '78 MB',
  },
  {
    survey: 'allWISE',
    files: 36,
    bands: 'W1 / W2 / W4',
    wavelength: 'mid-IR',
    wavelengthColor: '#FF006E',
    size: '78 MB',
  },
  {
    survey: 'LEGACY',
    files: 48,
    bands: 'g / r / i / z',
    wavelength: 'optical',
    wavelengthColor: '#00E676',
    size: '104 MB',
    note: '全零 · 需重导出',
  },
  {
    survey: 'NVSS',
    files: 12,
    bands: '1.4 GHz',
    wavelength: 'radio',
    wavelengthColor: '#7C3AED',
    size: '95 MB',
  },
]

export default function SettingsPage() {
  return (
    <div className='h-full overflow-auto' style={{ background: 'transparent' }}>
      <div className='max-w-3xl mx-auto p-6 space-y-5'>
        {/* Page Header */}
        <div className='flex items-center gap-3 mb-2'>
          <SettingOutlined className='text-aurora-cyan text-2xl' />
          <Title
            level={3}
            className='!mb-0 !text-white/90'
            style={{ fontWeight: 700 }}
          >
            Info
          </Title>
          <Tag color='cyan' className='font-semibold'>
            v4.62
          </Tag>
        </div>

        {/* System Information */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              System Information
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <div className='flex justify-center mb-4'>
            {/* R6.33: use small (compressed) variant + eager + fetchpriority=high
                so the Info page logo doesn't lag the page load. */}
            {/* R6.34: high-res WebP (600x600, ~30KB) keeps sharpness; PNG fallback
                for old browsers. width/height set to natural 600x600 so display at
                max 280x140 via object-contain doesn't downscale unnecessarily. */}
            <picture>
              <source
                srcSet='/Logo_for_AliCPT-display.webp'
                type='image/webp'
              />
              <img
                src='/Logo_for_AliCPT.png'
                alt='AliCPT Logo'
                className='object-contain rounded-lg'
                width={600}
                height={600}
                loading='eager'
                fetchPriority='high'
                decoding='async'
                style={{ maxWidth: 280, maxHeight: 140, height: 'auto' }}
              />
            </picture>
          </div>
          <Descriptions
            column={1}
            size='small'
            colon={false}
            labelStyle={{
              color: 'rgba(255,255,255,0.55)',
              fontWeight: 600,
              width: 140,
            }}
            contentStyle={{ color: 'rgba(255,255,255,0.85)', fontWeight: 500 }}
          >
            <Descriptions.Item label='Platform Name'>
              AliCPT DIVS
            </Descriptions.Item>
            <Descriptions.Item label='Subtitle'>
              Astronomical Data Platform
            </Descriptions.Item>
            <Descriptions.Item label='Version'>v4.62</Descriptions.Item>
            <Descriptions.Item label='Build Date'>2026-09-03</Descriptions.Item>
            <Descriptions.Item label='Architecture'>
              7 Docker Containers (Frontend + Backend + Pipeline + Firefly +
              Elasticsearch + MongoDB + MCP Server)
            </Descriptions.Item>
            <Descriptions.Item label='Access URL'>
              <code
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  padding: '2px 8px',
                  borderRadius: 4,
                  color: '#00F0FF',
                }}
              >
                https://alicpt.lhr.life
              </code>
              <Text className='text-white/40 text-xs ml-2'>
                (or localhost:6002)
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label='Design Theme'>
              Aurora Maximalism Dark Theme
            </Descriptions.Item>
          </Descriptions>
        </Card>

        {/* Feature Highlights (v4.62) */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              <StarOutlined className='mr-2' />
              Feature Highlights (v4.62)
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <div className='space-y-3'>
            {[
              {
                icon: <BankOutlined />,
                title: 'NAOC · Zhejiang Lab · LZU Collaboration',
                desc: 'Jointly developed by National Astronomical Observatories (CAS), Zhejiang Lab (之江实验室), and Lanzhou University (兰州大学).',
                color: '#FFB800',
              },
              {
                icon: <SafetyCertificateOutlined />,
                title: 'OpenAPI Documentation',
                desc: 'Interactive Swagger UI at /pipeline/docs (FastAPI) + /api/swagger-ui.html (SpringDoc).',
                color: '#00E676',
              },
              {
                icon: <SettingOutlined />,
                title: 'AI Config Admin Panel',
                desc: 'Visual config editor for system prompts, classification thresholds, and band configs at /admin/config.',
                color: '#00F0FF',
              },
              {
                icon: <MenuOutlined />,
                title: 'Mobile Navigation Dropdown',
                desc: 'Touch-friendly dropdown nav on mobile devices. Smooth page switching without horizontal scroll.',
                color: '#7C3AED',
              },
              {
                icon: <EyeOutlined />,
                title: 'Mobile FITS Fullscreen Viewer',
                desc: 'Fullscreen Aladin/Firefly with prominent exit button. Optimized mobile viewer experience.',
                color: '#00F0FF',
              },
              {
                icon: <SettingOutlined />,
                title: 'Mobile UX Improvements',
                desc: 'Single-row AI Chat header, optimized switch. Fullscreen overlay via Portal. No-scroll landing page.',
                color: '#FA8C16',
              },
              {
                icon: <StarOutlined />,
                title: 'Responsive Landing Page & Mobile AI Chat',
                desc: 'Landing fits one viewport, AI Chat single-row header with proper switch sizing, fullscreen overlay cleanup.',
                color: '#FFB800',
              },
              {
                icon: <StarOutlined />,
                title: 'Fullscreen Toggle + Square Thumbnails',
                desc: 'Fullscreen toggle visible on all screen sizes (desktop + mobile). Thumbnails use absolute positioning in square containers — no more stretching on mobile browsers.',
                color: '#00F0FF',
              },
              {
                icon: <CloudUploadOutlined />,
                title: 'FITS Upload & Vision Q&A',
                desc: 'Upload FITS images and ask visual questions. AI analyzes image + header context.',
                color: '#7C3AED',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.27k: HiPS-Float True DS9 Quality',
                desc: 'PNG fallback for HiPS tiles (no JPEG blocks). Backend /pipeline/hips-float reads raw 32-bit FITS + Floyd-Steinberg dither. ~175KB/tile vs ~30KB JPG. Toggle Std/Hi-Q in the strip.',
                color: '#00E676',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.28: Per-Channel RGB Cut',
                desc: '2MASS KHJ / allWISE W4W2W1 RGB composites now use per-channel cut+stretch+dither (DS9 standard). Drag any component-band contrast slider → RGB composite re-renders. Auto Hi-Q for W1/W2/W3/W4 + J/H/K (blocky auto-fixed).',
                color: '#00F0FF',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.29: Visible Strip Scrollbar + 429 Toast',
                desc: 'Native horizontal scrollbar always visible (8px cyan) — no more hidden macOS scrollbar. LLM 429 errors show friendly message instead of generic "429 - Request failed".',
                color: '#FA8C16',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.30: Per-Tile Hi-Q Toggle + Progress',
                desc: 'Click Hi-Q/Std badge on any tile to force Std mode for that tile (e.g. when Hi-Q returns noise for faint data). Panel header shows live "5/8 loaded · 2 loading" counter with color coding.',
                color: '#00E676',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.44: Font Backend Dashboard + CI Gate',
                desc: 'observability.py SQLite persists font errors + A/B samples at /pipeline/observability/*. subset-fonts.py --verify gates PRs (md5 drift check) via .github/workflows/font-subset.yml. prebuild npm hook auto-regenerates.',
                color: '#00E676',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.44: Per-Page Font Subsets (50-51KB)',
                desc: '5 pages (landing/home/index/settings/assistant) each ship a 50-51KB woff2 with only the chars that page uses. R6.43: 40KB; R6.44: 50-51KB after growth + global basic chars.',
                color: '#FF006E',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.45: Sentry SDK (DSN-gated)',
                desc: '@sentry/react lazy-loaded only if VITE_SENTRY_DSN is set. Currently no DSN → backend observability is the source of truth. Drop a DSN in .env and Sentry initializes automatically (10% sample rate).',
                color: '#7C3AED',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.45: Observability Dashboard UI',
                desc: 'New /admin/observability page visualizes font error counts by family/weight + A/B test winner (median + p95) with auto-refresh. Shows Sentry enabled/disabled state.',
                color: '#00F0FF',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.45: A/B Winner Auto-Switch',
                desc: 'useFontABTest pre-fetches /pipeline/observability/ab-dashboard on first mount. New users are auto-assigned to the winning group; existing users keep their stable assignment.',
                color: '#FA8C16',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.32: allWISE RGB Reacts to Component Sliders',
                desc: 'allWISE RGB composite (W4W2W1) now auto-Hi-Q + re-renders when W1/W2/W4 sliders move. Per-channel cut via /pipeline/merge-rgb?mode=hips with per-channel r_q_low/g_q_low/b_q_low.',
                color: '#FA8C16',
              },
              {
                icon: <ExperimentOutlined />,
                title: 'R6.29b: Hi-Q Preload Timeout',
                desc: 'Hi-Q URLs get 10s preload timeout, Std URLs 3s. Contrast bands (W4/K/J/H) complete loading during splash — no more "slow on first click".',
                color: '#7C3AED',
              },
              {
                icon: <BookOutlined />,
                title: 'Data Provenance & DOI',
                desc: 'Register DOIs, link observations, trace provenance chains at /admin/provenance.',
                color: '#FF006E',
              },
              {
                icon: <EyeOutlined />,
                title: 'Batch Export (Anomaly + Photometry)',
                desc: 'Export anomaly classification and photometric results as CSV/JSON via pipeline APIs.',
                color: '#FA8C16',
              },
            ].map((item) => (
              <div key={item.title} className='flex items-start gap-3'>
                <div
                  className='w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0'
                  style={{ background: `${item.color}18`, color: item.color }}
                >
                  {item.icon}
                </div>
                <div>
                  <Text className='text-white/85 font-semibold text-sm block'>
                    {item.title}
                  </Text>
                  <Text className='text-white/50 text-xs'>{item.desc}</Text>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Data Inventory */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              <DatabaseOutlined className='mr-2' />
              Data Inventory
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          {/* Header Row */}
          <div
            className='flex items-center gap-3 pb-2 mb-2'
            style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
          >
            <span
              className='text-white/50 text-xs font-semibold uppercase tracking-wider'
              style={{ width: 90 }}
            >
              Survey
            </span>
            <span
              className='text-white/50 text-xs font-semibold uppercase tracking-wider'
              style={{ width: 48 }}
            >
              Files
            </span>
            <span
              className='text-white/50 text-xs font-semibold uppercase tracking-wider'
              style={{ width: 120 }}
            >
              Bands
            </span>
            <span
              className='text-white/50 text-xs font-semibold uppercase tracking-wider'
              style={{ width: 72 }}
            >
              Wavelength
            </span>
            <span
              className='text-white/50 text-xs font-semibold uppercase tracking-wider'
              style={{ width: 56 }}
            >
              Size
            </span>
          </div>

          {/* Data Rows */}
          <div className='space-y-1'>
            {DATA_INVENTORY.map((item) => (
              <div
                key={item.survey}
                className='flex items-center gap-3 py-2 rounded'
                style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
              >
                <span style={{ width: 90 }}>
                  <Text className='text-white/85 font-semibold text-xs'>
                    {item.survey}
                  </Text>
                  {'note' in item && (
                    <Tag
                      color='error'
                      style={{
                        fontSize: 10,
                        lineHeight: '16px',
                        marginLeft: 4,
                      }}
                    >
                      {item.note}
                    </Tag>
                  )}
                </span>
                <span style={{ width: 48 }}>
                  <Text className='text-white/75 text-xs'>{item.files}</Text>
                </span>
                <span style={{ width: 120 }}>
                  <Text
                    className='text-white/70 text-xs'
                    style={{ fontFamily: 'monospace' }}
                  >
                    {item.bands}
                  </Text>
                </span>
                <span style={{ width: 72 }}>
                  <Tag
                    color={item.wavelengthColor}
                    style={{ fontSize: 11, lineHeight: '18px', margin: 0 }}
                  >
                    {item.wavelength}
                  </Tag>
                </span>
                <span style={{ width: 56 }}>
                  <Text className='text-white/75 text-xs'>{item.size}</Text>
                </span>
              </div>
            ))}
          </div>

          <Divider
            style={{ borderColor: 'rgba(255,255,255,0.06)', margin: '8px 0' }}
          />

          {/* Summary Row */}
          <div className='flex items-center gap-3 py-1'>
            <span style={{ width: 90 }}>
              <Tag color='cyan' style={{ fontWeight: 700 }}>
                TOTAL
              </Tag>
            </span>
            <span style={{ width: 48 }}>
              <Text className='text-white/90 text-xs font-bold'>180</Text>
            </span>
            <span style={{ width: 120 }}>
              <Text className='text-white/70 text-xs'>15 bands</Text>
            </span>
            <span style={{ width: 72 }}>
              <Text className='text-white/70 text-xs'>7 surveys</Text>
            </span>
            <span style={{ width: 56 }}>
              <Text className='text-white/70 text-xs'>FITS</Text>
            </span>
          </div>
          <Paragraph className='!mb-0 !mt-2 text-xs text-white/40'>
            LEGACY survey data is all-zero pending re-export. 180 FITS files
            across 15 configurable bands and 7 surveys total.
          </Paragraph>
        </Card>

        {/* Technology Stack */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              <CodeOutlined className='mr-2' />
              Technology Stack
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <div className='space-y-3'>
            {TECH_STACK.map((t) => (
              <div key={t.category}>
                <Text className='text-white/50 text-xs font-semibold uppercase tracking-wider'>
                  {t.category}
                </Text>
                <Paragraph className='!mb-0 !mt-1 text-sm text-white/75'>
                  {t.items}
                </Paragraph>
              </div>
            ))}
          </div>
        </Card>

        {/* AI / LLM Status */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              AI Models Status
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <div className='space-y-3'>
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  LLM Chat Engine
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  DeepSeek-V4 · SHA-256 cache · 500 req/day · Audit logging
                </Paragraph>
              </div>
              <Tag
                color='green'
                icon={<CheckCircleOutlined />}
                className='font-semibold'
              >
                LIVE
              </Tag>
            </div>
            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  Photometry Comparison
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  Multi-FITS flux stat extraction · Aperture photometry
                </Paragraph>
              </div>
              <Tag
                color='green'
                icon={<CheckCircleOutlined />}
                className='font-semibold'
              >
                LIVE
              </Tag>
            </div>
            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  DL Anomaly Detector
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  Statistical classifier + DL enhancement · 4 detectors
                  (spike/dip/pattern-break/WCS) · v4.62: temporarily disabled
                </Paragraph>
              </div>
              <Tag color='default' className='font-semibold'>
                PAUSED
              </Tag>
            </div>

            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  Galaxy Morphology Classifier
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  Zoobot ConvNeXt-Nano (ONNX) ·
                  spiral/elliptical/merger/edge-on/irregular
                </Paragraph>
              </div>
              <Tag color='green' className='font-semibold'>
                LIVE
              </Tag>
            </div>
            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  Source Type Classifier
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  Star/Galaxy/Quasar · Photometric + morphological features
                </Paragraph>
              </div>
              <Tag color='green' className='font-semibold'>
                LIVE
              </Tag>
            </div>
            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  Scientific Pipeline Agents
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  LLM-driven autonomous scientific workflows
                </Paragraph>
              </div>
              <Tag color='purple' className='font-semibold'>
                PLANNED
              </Tag>
            </div>
            <Divider
              style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '8px 0' }}
            />
            <div className='flex items-center justify-between'>
              <div>
                <Text className='text-white/85 font-semibold text-sm'>
                  Multi-Messenger Correlator
                </Text>
                <Paragraph className='!mb-0 text-xs text-white/50'>
                  GW events × EM follow-up cross-reference
                </Paragraph>
              </div>
              <Tag color='purple' className='font-semibold'>
                PLANNED
              </Tag>
            </div>
          </div>
        </Card>

        {/* DL Model License Status (v4.62) */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              DL Model License Status
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <Descriptions
            column={1}
            size='small'
            colon={false}
            labelStyle={{
              color: 'rgba(255,255,255,0.55)',
              fontWeight: 600,
              width: 140,
            }}
            contentStyle={{ color: 'rgba(255,255,255,0.85)', fontWeight: 500 }}
          >
            <Descriptions.Item label='Active License'>
              <Tag color='cyan' className='font-semibold'>
                Check /pipeline/dl/status
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label='GPL Models'>
              <Tag color='green'>Excludable at build time</Tag>
            </Descriptions.Item>
            <Descriptions.Item label='Distribution'>
              <Text className='text-white/75 text-xs'>
                Rebuild with{' '}
                <code
                  style={{
                    background: 'rgba(255,255,255,0.06)',
                    padding: '1px 6px',
                    borderRadius: 3,
                  }}
                >
                  --build-arg EXCLUDE_GPL_MODELS=true
                </code>{' '}
                for MIT-only deployment. When GPL models are excluded,
                morphology classification degrades gracefully to lightweight
                feature-based classifiers (40-60% accuracy vs 60-75% with
                Zoobot).
              </Text>
            </Descriptions.Item>
          </Descriptions>
          <Divider
            style={{ borderColor: 'rgba(255,255,255,0.05)', margin: '12px 0' }}
          />
          <div className='space-y-2'>
            <div className='flex items-center justify-between'>
              <Text className='text-white/70 text-xs'>Zoobot Encoder</Text>
              <Tag color='warning' style={{ fontSize: 11 }}>
                GPL-3.0
              </Tag>
            </div>
            <div className='flex items-center justify-between'>
              <Text className='text-white/70 text-xs'>Source Classifier</Text>
              <Tag color='green' style={{ fontSize: 11 }}>
                MIT
              </Tag>
            </div>
            <div className='flex items-center justify-between'>
              <Text className='text-white/70 text-xs'>Anomaly Autoencoder</Text>
              <Tag color='green' style={{ fontSize: 11 }}>
                MIT
              </Tag>
            </div>
            <div className='flex items-center justify-between'>
              <Text className='text-white/70 text-xs'>
                Lightweight Fallbacks
              </Text>
              <Tag color='green' style={{ fontSize: 11 }}>
                MIT
              </Tag>
            </div>
          </div>
          <Paragraph className='!mb-0 !mt-3 text-xs text-white/40'>
            v4.62: Active license is reported at runtime via{' '}
            <code
              style={{
                background: 'rgba(255,255,255,0.04)',
                padding: '1px 4px',
                borderRadius: 2,
              }}
            >
              /pipeline/dl/status
            </code>{' '}
            endpoint. Users and auditors can verify the current deployment's
            license status without guessing.
          </Paragraph>
        </Card>

        {/* Contact & Team */}
        <Card
          title={
            <span className='text-white/85 font-bold text-sm'>
              <TeamOutlined className='mr-2' />
              Contact & Team
            </span>
          }
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 16,
          }}
          styles={{
            header: { borderColor: 'rgba(255,255,255,0.06)' },
            body: { padding: '16px 20px' },
          }}
        >
          <div className='space-y-4'>
            {CONTACTS.map((c) => (
              <div key={c.name} className='flex items-start gap-3'>
                <div
                  className='w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0'
                  style={{
                    background: 'rgba(0,240,255,0.10)',
                    color: '#00F0FF',
                  }}
                >
                  {c.icon}
                </div>
                <div>
                  <Text className='text-white/85 font-semibold text-sm block'>
                    {c.role}
                  </Text>
                  <Text className='text-white/70 text-sm'>{c.name}</Text>
                  <br />
                  <Text className='text-white/45 text-xs'>{c.org}</Text>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Footer */}
        <div className='text-center pt-2 pb-6'>
          <Text className='text-white/35 text-xs'>
            AliCPT DIVS v4.62 · Built with Aurora Maximalism · © 2026
          </Text>
        </div>
      </div>
    </div>
  )
}
