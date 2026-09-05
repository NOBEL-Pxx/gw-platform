import { useState, useEffect, useRef, useCallback } from 'react'
import { Drawer, Button, Card, Divider, Tag } from 'antd'
import { useFloatingButtonVisible } from '@/hooks/useFloatingButtonVisible'
import RobotOutlined from '@ant-design/icons/RobotOutlined'
import ExperimentOutlined from '@ant-design/icons/ExperimentOutlined'
import ThunderboltOutlined from '@ant-design/icons/ThunderboltOutlined'
import ApiOutlined from '@ant-design/icons/ApiOutlined'
import CloseOutlined from '@ant-design/icons/CloseOutlined'
import StarOutlined from '@ant-design/icons/StarOutlined'
import EyeOutlined from '@ant-design/icons/EyeOutlined'
import AimOutlined from '@ant-design/icons/AimOutlined'
import { useNavigate } from 'react-router-dom'
import { ASSETS } from '@/constants/assets'

// Drag persistence
const DRAG_KEY = 'gw-float-btn-pos'
function loadPos() {
  try {
    const raw = localStorage.getItem(DRAG_KEY)
    if (raw) return JSON.parse(raw)
  } catch (_e) {
    /* ignore */
  }
  return null
}
function savePos(x: number, y: number) {
  try {
    localStorage.setItem(DRAG_KEY, JSON.stringify({ x, y }))
  } catch (_e) {
    /* ignore */
  }
}

const MODEL_SLOTS = [
  {
    icon: <RobotOutlined />,
    title: 'LLM Chat Engine',
    desc: 'DeepSeek-V4 powers natural-language queries over gravitational-wave observations, error reports, and pipeline results.',
    status: 'active',
    color: '#00F0FF',
  },
  {
    icon: <ThunderboltOutlined />,
    title: 'DL Anomaly Detector',
    desc: 'Anomaly detection reports and error analysis (v4.32: DL classifier temporarily paused).',
    status: 'active',
    color: '#7C3AED',
  },
  {
    icon: <EyeOutlined />,
    title: 'Galaxy Morphology Classifier',
    desc: 'Locally embedded Zoobot ConvNeXt-Nano (ONNX): classifies galaxy morphology (spiral, elliptical, edge-on, merger, irregular). No external API calls.',
    status: 'active',
    color: '#1890FF',
  },
  {
    icon: <AimOutlined />,
    title: 'Source Type Classifier',
    desc: 'Locally embedded astronomy classifier: star/galaxy/quasar discrimination from photometric + morphological features. ONNX-ready.',
    status: 'active',
    color: '#52C41A',
  },
  {
    icon: <ExperimentOutlined />,
    title: 'Scientific Pipeline Agents',
    desc: 'Chain Astropy source-detection → cross-match → light-curve extraction into autonomous workflows dispatched by LLM reasoning.',
    status: 'planned',
    color: '#FF006E',
  },
  {
    icon: <ApiOutlined />,
    title: 'MCP Tool Expansion',
    desc: 'Expose deep-learning inference endpoints as MCP tools so Claude Desktop and other AI assistants can run source detection and anomaly classification.',
    status: 'planned',
    color: '#FFB800',
  },
  {
    icon: <StarOutlined />,
    title: 'Multi-Messenger Correlator',
    desc: 'Cross-reference gravitational-wave events (LIGO/Virgo/KAGRA) with electromagnetic follow-up observations stored in this platform.',
    status: 'planned',
    color: '#00E676',
  },
]

function getDrawerWidth() {
  return Math.min(440, window.innerWidth)
}

export default function AIFloatingButton() {
  const [open, setOpen] = useState(false)
  const [drawerWidth, setDrawerWidth] = useState(440)
  const [activeLicense, setActiveLicense] = useState<string | null>(null)
  const navigate = useNavigate()

  // Drag state
  const btnRef = useRef<HTMLButtonElement>(null)
  const dragRef = useRef({
    dragging: false,
    startX: 0,
    startY: 0,
    origLeft: 0,
    origTop: 0,
  })
  const [pos, setPos] = useState<{ left: number; top: number } | null>(() => {
    const saved = loadPos()
    return saved ? { left: saved.x, top: saved.y } : null
  })
  // R6.27i: shared visibility state. Default HIDDEN — entire button is not
  // rendered. User clicks the navbar toggle (Layout.tsx) to make it appear.
  // When shown, the icon is static (no rotation — user clarified rotation
  // is unrelated to visibility).
  const [visible] = useFloatingButtonVisible()

  // R6.27i FIX: ALL hooks must be called before any conditional return
  // (React Hook Rule). The `if (!visible) return null` MUST come after all
  // useRef/useCallback/useEffect calls. Otherwise React detects a hook count
  // mismatch between renders (visible=false: 8 hooks, visible=true: 14 hooks)
  // and throws error #310.
  const posRef = useRef(pos)
  posRef.current = pos

  // Convert saved position (left/top in px) to viewport-relative on resize
  const clampPos = useCallback((l: number, t: number) => {
    const size = 56
    const maxX = window.innerWidth - size - 8
    const maxY = window.innerHeight - size - 8
    return {
      left: Math.max(8, Math.min(l, maxX)),
      top: Math.max(8, Math.min(t, maxY)),
    }
  }, [])

  useEffect(() => {
    const handler = () => {
      if (posRef.current) {
        setPos(clampPos(posRef.current.left, posRef.current.top))
      }
    }
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [clampPos])

  // Pointer handlers for drag
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (open) return // Don't drag when drawer is open
      const btn = btnRef.current
      if (!btn) return
      btn.setPointerCapture(e.pointerId)
      const rect = btn.getBoundingClientRect()
      dragRef.current = {
        dragging: true,
        startX: e.clientX,
        startY: e.clientY,
        origLeft: rect.left,
        origTop: rect.top,
      }
    },
    [open],
  )

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const d = dragRef.current
      if (!d.dragging) return
      const dx = e.clientX - d.startX
      const dy = e.clientY - d.startY
      const newPos = clampPos(d.origLeft + dx, d.origTop + dy)
      setPos(newPos)
      savePos(newPos.left, newPos.top)
    },
    [clampPos],
  )

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    dragRef.current.dragging = false
    const btn = btnRef.current
    if (btn) btn.releasePointerCapture(e.pointerId)
    // If barely moved, treat as click
  }, [])

  // v4.30: Fetch active DL license status so the Galaxy Morphology card
  // shows the REAL license (GPL-3.0 / MIT) instead of blind "LIVE".
  useEffect(() => {
    let cancelled = false
    fetch('/pipeline/dl/status')
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled && data.active_license) {
          setActiveLicense(data.active_license)
        }
      })
      .catch(() => {
        // Backend unreachable - keep generic LIVE label
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setDrawerWidth(getDrawerWidth())
    let timer: ReturnType<typeof setTimeout>
    const handler = () => {
      clearTimeout(timer)
      timer = setTimeout(() => setDrawerWidth(getDrawerWidth()), 150)
    }
    window.addEventListener('resize', handler)
    return () => {
      window.removeEventListener('resize', handler)
      clearTimeout(timer)
    }
  }, [])

  // R6.27i: AFTER all hooks — only NOW can we conditionally return null.
  if (!visible) return null

  return (
    <>
      {/* Floating draggable CAS icon button */}
      <button
        ref={btnRef}
        type='button'
        onClick={() => setOpen(true)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen(true)
          }
        }}
        tabIndex={0}
        className='ai-float-btn'
        style={{
          zIndex: open ? 900 : 9999,
          touchAction: 'none',
          userSelect: 'none',
          ...(pos
            ? { left: pos.left, top: pos.top, bottom: 'auto', right: 'auto' }
            : {}),
        }}
        aria-label={open ? 'Close AI Models Hub' : 'Open AI Models Hub'}
        aria-expanded={open}
        title='AI Models Hub (drag to reposition, click to open)'
      >
        <img
          src={ASSETS.icons.cas}
          // R6.27i.c: restore 抠图 rotation effect when icon is shown.
          // The .ai-float-btn-icon CSS class already has border-radius:50%
          // + drop-shadow + aiSpinSlow rotation + radial mask (the "抠图后样式").
          className='ai-float-btn-icon'
          alt='AliCPT DIVS AI Models Hub'
          style={{ mixBlendMode: 'multiply' }}
        />
      </button>

      {/* AI Models Hub Drawer */}
      <Drawer
        title={
          <div className='flex items-center gap-2'>
            <img
              src={ASSETS.icons.cas}
              className='rounded-full'
              alt='AliCPT DIVS AI'
              // R6.27i.c: restore rotation animation (抠图 + spin)
              style={{
                width: 24,
                height: 24,
                objectFit: 'cover',
                animation: 'aiSpinSlow 8s linear infinite',
              }}
            />
            <span className='aurora-text font-bold text-lg'>AI Models Hub</span>
            <Tag color='purple' className='ml-1 font-semibold'>
              v0.3-beta
            </Tag>
          </div>
        }
        placement='right'
        width={drawerWidth}
        open={open}
        onClose={() => setOpen(false)}
        closeIcon={
          <CloseOutlined className='!text-white/60 hover:!text-white' />
        }
        styles={{
          body: { padding: '16px 20px', background: '#0A0F24' },
          header: {
            background:
              'linear-gradient(135deg, rgba(26,10,46,0.95), rgba(10,26,46,0.95))',
            borderBottom: '1px solid rgba(0,240,255,0.10)',
          },
          mask: {
            background: 'rgba(0,0,0,0.65)',
            backdropFilter: 'blur(4px)',
            WebkitBackdropFilter: 'blur(4px)',
          },
          content: { background: '#0A0F24' },
          wrapper: { boxShadow: 'none' },
        }}
      >
        {/* Intro */}
        <div
          className='rounded-xl p-4 mb-5 text-sm'
          style={{
            background:
              'linear-gradient(135deg, rgba(0,240,255,0.06), rgba(124,58,237,0.06))',
            border: '1px solid rgba(0,240,255,0.12)',
            color: 'rgba(255,255,255,0.75)',
            lineHeight: 1.7,
          }}
        >
          <strong className='text-white/90'>AI Models Hub</strong> is the
          intelligence layer for the AliCPT DIVS platform. It embeds{' '}
          <span style={{ color: '#00F0FF' }}>LLMs (DeepSeek-V4)</span>,{' '}
          <span style={{ color: '#7C3AED' }}>
            deep learning models (Zoobot + ONNX)
          </span>
          , and{' '}
          <span style={{ color: '#FF006E' }}>autonomous scientific agents</span>{' '}
          directly into the astronomical data workflow &mdash; from anomaly
          detection to galaxy morphology classification.
        </div>

        {/* Quick link to current AI Chat */}
        <Button
          type='default'
          block
          size='large'
          icon={<RobotOutlined />}
          onClick={() => {
            setOpen(false)
            navigate('/assistant')
          }}
          style={{
            height: 44,
            borderRadius: 12,
            marginBottom: 16,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(0,240,255,0.2)',
            color: 'rgba(255,255,255,0.85)',
            fontWeight: 600,
          }}
        >
          Open AI Chat (DeepSeek-V4)
        </Button>

        <Divider
          style={{
            borderColor: 'rgba(255,255,255,0.06)',
            margin: '12px 0 16px',
          }}
        >
          <span className='text-white/45 text-xs font-semibold'>
            AI MODEL SLOTS (7 slots, 4 LIVE)
          </span>
        </Divider>

        {/* Model cards */}
        <div className='flex flex-col gap-3'>
          {MODEL_SLOTS.map((model) => (
            <Card
              key={model.title}
              size='small'
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: `1px solid ${model.color}15`,
                borderRadius: 12,
              }}
              styles={{ body: { padding: '12px 14px' } }}
            >
              <div className='flex items-start gap-3'>
                <div
                  className='w-9 h-9 rounded-lg flex items-center justify-center text-lg flex-shrink-0'
                  style={{
                    background: `${model.color}18`,
                    color: model.color,
                  }}
                >
                  {model.icon}
                </div>
                <div className='flex-1 min-w-0'>
                  <div className='flex items-center gap-2 mb-1'>
                    <span className='font-bold text-sm text-white/90'>
                      {model.title}
                    </span>
                    <Tag
                      color={
                        // v4.30: Galaxy Morphology shows real license, not blind LIVE
                        model.title === 'Galaxy Morphology Classifier' &&
                        activeLicense
                          ? activeLicense.includes('GPL')
                            ? 'orange'
                            : 'green'
                          : model.status === 'active'
                            ? 'green'
                            : 'purple'
                      }
                      className='!text-[10px] !leading-none !px-1.5 !py-0.5 font-semibold'
                    >
                      {model.title === 'Galaxy Morphology Classifier' &&
                      activeLicense
                        ? activeLicense.includes('GPL')
                          ? 'GPL-3.0'
                          : 'MIT'
                        : model.status === 'active'
                          ? 'LIVE'
                          : 'PLANNED'}
                    </Tag>
                  </div>
                  <p className='text-xs text-white/55 leading-relaxed m-0'>
                    {model.desc}
                  </p>
                </div>
              </div>
            </Card>
          ))}
        </div>

        {/* Footer note */}
        <div
          className='mt-5 pt-4 text-center'
          style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}
        >
          <p className='text-xs text-white/45 m-0'>
            Models deployed as Docker sidecar containers (local inference, zero
            external API)
          </p>
          <p className='text-xs text-white/40 m-0 mt-0.5'>
            Powered by DeepSeek API / ONNX Runtime / PyTorch / numpy+scipy
          </p>
        </div>
      </Drawer>
    </>
  )
}
