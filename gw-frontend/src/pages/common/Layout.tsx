import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { Button, Dropdown, Tooltip, Select } from 'antd'
import AIFloatingButton from '@/components/AIFloatingButton'
import ErrorBoundary from '@/components/ErrorBoundary'
import StarfieldBackground, {
  detectGpuBudget,
} from '@/components/StarfieldBackground'
import { useFloatingButtonVisible } from '@/hooks/useFloatingButtonVisible'
import UserOutlined from '@ant-design/icons/UserOutlined'
import LogoutOutlined from '@ant-design/icons/LogoutOutlined'
import CommentOutlined from '@ant-design/icons/CommentOutlined'
import AlertOutlined from '@ant-design/icons/AlertOutlined'
import MenuOutlined from '@ant-design/icons/MenuOutlined'

type QualityTier = 'low' | 'medium' | 'high'
const TIER_CONFIG: Record<
  QualityTier,
  { stars: number; fps: number; glow: boolean }
> = {
  low: { stars: 150, fps: 15, glow: false },
  medium: { stars: 400, fps: 30, glow: true },
  high: { stars: 800, fps: 60, glow: true },
}
const nextTier: Record<QualityTier, QualityTier> = {
  low: 'medium',
  medium: 'high',
  high: 'low',
}

// R6.57: navItems is pure data (no props/state refs) — lift to module scope so
// mobileNavOptions useMemo gets a stable reference and exhaustive-deps lint passes.
const NAV_ITEMS: ReadonlyArray<{
  path: string
  label: string
  aria: string
  icon?: React.ReactNode
}> = [
  {
    path: '/index',
    label: 'Abnormal Data',
    aria: 'Navigate to Abnormal Data page',
  },
  {
    path: '/search',
    label: 'FITS Search',
    aria: 'Navigate to FITS Search page',
  },
  { path: '/assistant', label: 'AI Chat', aria: 'Navigate to AI Chat page' },
  {
    path: '/collections',
    label: 'Alert',
    aria: 'Navigate to Alert page',
    icon: <AlertOutlined />,
  },
  {
    path: '/my-comments',
    label: 'My Comments',
    aria: 'Navigate to My Comments page',
    icon: <CommentOutlined />,
  },
  { path: '/settings', label: 'Info', aria: 'Navigate to Info page' },
]

export default function LayoutWrapper() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  // R6.27: Starfield is now DEFAULT OFF to protect first-paint FPS on
  // mid/low-end devices. Users opt in via the starfield toggle button.
  // detectGpuBudget() seeds the tier regardless — when the user enables it,
  // the appropriate tier is already selected for their hardware.
  const [tier, setTier] = useState<QualityTier>(() => detectGpuBudget())
  const [starfieldOn, setStarfieldOn] = useState(() => {
    // Explicit opt-in: user must have set 'gw-starfield-enabled' = 'true'
    return localStorage.getItem('gw-starfield-enabled') === 'true'
  })
  // v4.55: Meteor (shooting star) toggle — default OFF
  const [meteorOn, setMeteorOn] = useState(
    () => localStorage.getItem('gw-meteor-enabled') === 'true',
  )

  // R6.27i: AI Models Hub floating button visibility toggle.
  // Default: HIDDEN — entire button is not rendered. User clicks navbar
  // button to make the floating AI Models Hub button appear.
  const [btnVisible, toggleBtnVisible] = useFloatingButtonVisible()

  useEffect(() => {
    // R6.27: opt-in model — localStorage key is 'gw-starfield-enabled'
    localStorage.setItem('gw-starfield-enabled', starfieldOn ? 'true' : 'false')
  }, [starfieldOn])

  useEffect(() => {
    localStorage.setItem('gw-meteor-enabled', meteorOn ? 'true' : 'false')
  }, [meteorOn])

  const cycleTier = useCallback(() => setTier((t) => nextTier[t]), [])

  const isActive = (path: string) => pathname === path

  const navLinkClass = (path: string) => {
    const active = isActive(path)
    return (
      'relative px-4 py-1.5 rounded-lg text-sm font-semibold transition-all duration-200 ' +
      (active ? 'text-white' : 'text-white/55 hover:text-white/85')
    )
  }

  // v4.54: Mobile nav dropdown options
  const mobileNavOptions = useMemo(
    () =>
      NAV_ITEMS.map(({ path, label }) => ({
        value: path,
        label: (
          <span
            className={
              pathname === path ? 'text-aurora-cyan font-bold' : 'text-white/75'
            }
          >
            {label}
          </span>
        ),
      })),
    [pathname],
  )

  const handleMobileNav = useCallback(
    (val: string) => {
      navigate(val)
    },
    [navigate],
  )

  const cfg = TIER_CONFIG[tier]

  return (
    <div className='h-screen flex flex-col bg-space-dark relative'>
      <StarfieldBackground
        tier={tier}
        disabled={!starfieldOn}
        meteors={meteorOn}
      />
      {/* Header */}
      <div
        className='h-16 flex-shrink-0 flex items-center px-6 gap-6 relative z-20'
        style={{
          background:
            'linear-gradient(135deg, rgba(26,10,46,0.92) 0%, rgba(10,26,46,0.92) 40%, rgba(10,10,26,0.92) 100%)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',
          borderBottom: '1px solid rgba(0,240,255,0.10)',
          boxShadow: '0 2px 20px rgba(124,58,237,0.08)',
        }}
      >
        {/* Logo */}
        <Link
          to='/index'
          className='flex items-center gap-2 shrink-0 !text-inherit hover:!text-inherit'
        >
          <span className='text-lg font-bold tracking-tight aurora-text'>
            AliCPT DIVS
          </span>
          <span className='text-xs text-white/40 mt-0.5 font-semibold'>
            v4.62
          </span>
        </Link>

        {/* Navigation: Desktop — horizontal tabs */}
        <nav className='hidden md:flex gap-1'>
          {NAV_ITEMS.map(({ path, label, aria, icon }) => (
            <Link
              key={path}
              to={path}
              className={navLinkClass(path)}
              aria-label={aria}
              aria-current={isActive(path) ? 'page' : undefined}
            >
              {icon && <span className='mr-1'>{icon}</span>}
              {label}
              {isActive(path) && (
                <span
                  className='absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full'
                  style={{
                    background: 'linear-gradient(90deg, #00F0FF, #7C3AED)',
                  }}
                />
              )}
            </Link>
          ))}
        </nav>

        {/* v4.54: Mobile Navigation — dropdown select */}
        <div className='flex md:hidden items-center flex-1 mx-1'>
          <Select
            value={pathname}
            onChange={handleMobileNav}
            options={mobileNavOptions}
            popupMatchSelectWidth={false}
            variant='borderless'
            className='mobile-nav-select w-full'
            aria-label='Navigate to page'
            suffixIcon={<MenuOutlined className='text-white/50 text-sm' />}
          />
        </div>

        {/* v4.54: Starfield controls in nav bar (was bottom-right corner) */}
        <div className='flex items-center gap-1 ml-auto mr-2'>
          {/* R6.27i: AI Models Hub floating button visibility toggle.
              Default: HIDDEN (entire button not rendered). User clicks
              this navbar button to make the floating AI Models Hub appear.
              Shows "🤖" when visible, "○" when hidden. */}
          <Tooltip
            title={
              btnVisible
                ? 'AI Models Hub visible — click to hide'
                : 'AI Models Hub hidden — click to show'
            }
          >
            <button
              onClick={toggleBtnVisible}
              aria-label={
                btnVisible ? 'Hide AI Models Hub' : 'Show AI Models Hub'
              }
              aria-pressed={btnVisible}
              data-testid='gw-ai-button-toggle'
              className='text-[10px] px-2 py-1 rounded border transition-colors shrink-0'
              style={{
                background: btnVisible
                  ? 'rgba(0,240,255,0.12)'
                  : 'rgba(255,255,255,0.04)',
                borderColor: btnVisible
                  ? 'rgba(0,240,255,0.35)'
                  : 'rgba(255,255,255,0.05)',
                color: btnVisible
                  ? 'rgba(0,240,255,0.95)'
                  : 'rgba(255,255,255,0.30)',
              }}
            >
              {btnVisible ? '🤖' : '○'}
            </button>
          </Tooltip>
          <Tooltip
            title={
              starfieldOn
                ? 'Starfield ON — click to disable (R6.27: default OFF, opt-in)'
                : 'Starfield OFF — click to enable'
            }
          >
            <button
              onClick={() => setStarfieldOn((s) => !s)}
              className='text-white/30 hover:text-white/60 text-[10px] px-2 py-1 rounded border border-white/5 hover:border-white/10 transition-colors shrink-0'
              style={{ background: 'rgba(255,255,255,0.04)' }}
            >
              {starfieldOn ? '✦' : '✧'}
            </button>
          </Tooltip>
          {starfieldOn && (
            <>
              {/* v4.55: Meteor toggle — default OFF */}
              <Tooltip
                title={
                  meteorOn
                    ? 'Meteors ON — click to disable'
                    : 'Meteors OFF — click to enable'
                }
              >
                <button
                  onClick={() => setMeteorOn((s) => !s)}
                  className='text-white/30 hover:text-white/60 text-[10px] px-2 py-1 rounded border border-white/5 hover:border-white/10 transition-colors shrink-0'
                  style={{
                    background: meteorOn
                      ? 'rgba(0,240,255,0.12)'
                      : 'rgba(255,255,255,0.04)',
                  }}
                >
                  ☄
                </button>
              </Tooltip>
              <Tooltip
                title={`${tier} · ${cfg.stars} stars @ ${cfg.fps}fps — click to change`}
              >
                <button
                  onClick={cycleTier}
                  className='text-white/30 hover:text-white/60 text-[10px] px-2 py-1 rounded border border-white/5 hover:border-white/10 transition-colors shrink-0'
                  style={{ background: 'rgba(255,255,255,0.04)' }}
                >
                  {tier === 'high' ? '★★★' : tier === 'medium' ? '★★☆' : '★☆☆'}
                </button>
              </Tooltip>
            </>
          )}
        </div>

        {/* User */}
        <div className='shrink-0'>
          {user ? (
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'info',
                    label: (
                      <div className='py-1'>
                        <div className='text-sm font-semibold'>
                          {user.username}
                        </div>
                        <div className='text-xs text-white/45 capitalize'>
                          {user.role}
                        </div>
                      </div>
                    ),
                    disabled: true,
                  },
                  { type: 'divider' },
                  {
                    key: 'comments',
                    label: 'My Comments',
                    icon: <CommentOutlined />,
                    onClick: () => navigate('/my-comments'),
                  },
                  {
                    key: 'alerts',
                    label: 'Alerts',
                    icon: <AlertOutlined />,
                    onClick: () => navigate('/collections'),
                  },
                  { type: 'divider' },
                  {
                    key: 'logout',
                    label: 'Logout',
                    icon: <LogoutOutlined />,
                    danger: true,
                    onClick: () => {
                      logout()
                      navigate('/')
                    },
                  },
                ],
              }}
              trigger={['click']}
            >
              <Button
                type='text'
                className='!text-white/65 hover:!text-white !h-9 font-semibold'
                icon={<UserOutlined />}
                style={{ borderRadius: 10 }}
              >
                {user.username}
              </Button>
            </Dropdown>
          ) : (
            <Button
              type='default'
              onClick={() => navigate('/login')}
              className='!border-white/20 !text-white/75 hover:!border-aurora-cyan/40 hover:!text-white !h-9 font-semibold'
              style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 10 }}
            >
              Login
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className='flex-1 overflow-auto relative z-10'>
        <div className='animate-fade-in'>
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>

      <ErrorBoundary>
        <AIFloatingButton />
      </ErrorBoundary>
    </div>
  )
}
