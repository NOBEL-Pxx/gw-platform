import { useState, useEffect } from 'react'
import LogoFade from '@/components/LogoFade'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Card, Tabs, Typography } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'

import { useAuth } from '@/contexts/AuthContext'

const { Text } = Typography

export default function LoginPage() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [loading, setLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })

  useEffect(() => {
    let rafId: number
    const handler = (e: MouseEvent) => {
      cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() =>
        setMousePos({ x: e.clientX, y: e.clientY }),
      )
    }
    window.addEventListener('mousemove', handler, { passive: true })
    return () => {
      window.removeEventListener('mousemove', handler)
      cancelAnimationFrame(rafId)
    }
  }, [])

  const handleLogin = async (values: {
    username: string
    password: string
  }) => {
    setLoading(true)
    setLoginError('')
    const ok = await login(values.username, values.password)
    setLoading(false)
    if (ok) navigate('/index')
    else setLoginError('Invalid username or password. Please try again.')
  }

  const handleRegister = async (values: {
    username: string
    password: string
    email?: string
  }) => {
    setLoading(true)
    setLoginError('')
    const ok = await register(values.username, values.password, values.email)
    setLoading(false)
    if (ok) navigate('/index')
    else setLoginError('Registration failed. Username may already exist.')
  }

  return (
    <div
      className='min-h-screen flex items-center justify-center relative overflow-hidden animate-fade-in'
      style={{
        background:
          'radial-gradient(ellipse 80% 60% at 20% 20%, rgba(93,52,208,0.35) 0%, transparent 60%), radial-gradient(ellipse 70% 50% at 80% 30%, rgba(255,0,110,0.25) 0%, transparent 55%), radial-gradient(ellipse 90% 60% at 50% 90%, rgba(0,240,255,0.20) 0%, transparent 60%), linear-gradient(135deg, #050510 0%, #0A0820 50%, #060512 100%)',
      }}
    >
      {/* R6.83: Aurora mesh conic overlay - the visual signature */}
      <div
        className='fixed inset-0 pointer-events-none z-0 opacity-30'
        style={{
          background:
            'conic-gradient(from 215deg at 30% 70%, #5D34D0 0deg, #FF006E 90deg, #00F0FF 180deg, #7C3AED 270deg, #5D34D0 360deg)',
          filter: 'blur(80px)',
          mixBlendMode: 'screen',
        }}
      />

      {/* Mouse-tracked cyan-violet glow (parallax cursor cue) */}
      <div
        className='fixed pointer-events-none z-0'
        style={{
          left: mousePos.x - 200,
          top: mousePos.y - 200,
          width: 400,
          height: 400,
          background:
            'radial-gradient(circle, rgba(0,240,255,0.10) 0%, rgba(124,58,237,0.06) 40%, transparent 70%)',
          borderRadius: '50%',
          transition: 'left 0.18s ease-out, top 0.18s ease-out',
        }}
      />

      <Card
        className='relative z-10 animate-slide-up'
        style={{
          width: 'min(440px, 92vw)',
          borderRadius: 24,
          background:
            'linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(124,58,237,0.04) 50%, rgba(0,240,255,0.03) 100%)',
          backdropFilter: 'blur(28px)',
          WebkitBackdropFilter: 'blur(28px)',
          border: '1px solid rgba(255,255,255,0.16)',
          boxShadow:
            '0 12px 56px rgba(0,0,0,0.6), 0 0 120px rgba(0,240,255,0.08), inset 0 1px 0 rgba(255,255,255,0.10)',
        }}
        bordered={false}
      >
        <div className='text-center mb-7'>
          <LogoFade size={120} alt='AliCPT DIVS Logo' className='!mb-4' />
          <div
            className='font-black tracking-tight leading-none select-none'
            style={{
              fontSize: 'clamp(28px, 6vw, 36px)',
              background:
                'linear-gradient(90deg, #00F0FF 0%, #7C3AED 50%, #FF006E 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              filter: 'drop-shadow(0 0 24px rgba(0,240,255,0.45))',
              fontFamily:
                '"Inter Variable", "Inter", -apple-system, BlinkMacSystemFont, sans-serif',
              letterSpacing: '-0.02em',
            }}
          >
            AliCPT DIVS
          </div>
          <Text
            className='!text-white/55 text-sm tracking-wider font-semibold'
            style={{ marginTop: 8, display: 'block' }}
          >
            Astronomical Data Platform
          </Text>
          <div
            className='mt-4 mx-auto w-20 h-0.5 rounded-full'
            style={{
              background: 'linear-gradient(90deg, #00F0FF, #7C3AED, #FF006E)',
              boxShadow: '0 0 12px rgba(0,240,255,0.6)',
            }}
          />
        </div>

        {loginError && (
          <div
            className='mb-4 p-3 rounded-lg text-sm font-semibold'
            style={{
              background: 'rgba(255,0,110,0.15)',
              border: '1px solid rgba(255,0,110,0.35)',
              color: '#FF6B9D',
            }}
          >
            {loginError}
          </div>
        )}

        <Tabs
          activeKey={tab}
          onChange={(k) => {
            setTab(k as 'login' | 'register')
            setLoginError('')
          }}
          centered
          items={[
            {
              key: 'login',
              label: <span className='px-2 font-semibold'>Login</span>,
              children: (
                <Form onFinish={handleLogin} size='large' autoComplete='off'>
                  <Form.Item
                    name='username'
                    rules={[{ required: true, message: 'Enter username' }]}
                  >
                    <Input
                      prefix={<UserOutlined className='!text-white/45' />}
                      placeholder='Username'
                      aria-label='Username'
                    />
                  </Form.Item>
                  <Form.Item
                    name='password'
                    rules={[{ required: true, message: 'Enter password' }]}
                  >
                    <Input.Password
                      prefix={<LockOutlined className='!text-white/45' />}
                      placeholder='Password'
                      aria-label='Password'
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type='primary'
                      htmlType='submit'
                      loading={loading}
                      block
                      size='large'
                      style={{
                        height: 46,
                        borderRadius: 12,
                        fontWeight: 700,
                        fontSize: 16,
                      }}
                    >
                      Login
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: 'register',
              label: <span className='px-2 font-semibold'>Register</span>,
              children: (
                <Form onFinish={handleRegister} size='large' autoComplete='off'>
                  <Form.Item
                    name='username'
                    rules={[
                      { required: true, message: 'Enter username' },
                      { min: 3, message: 'At least 3 characters' },
                    ]}
                  >
                    <Input
                      prefix={<UserOutlined className='!text-white/45' />}
                      placeholder='Username'
                      aria-label='Username'
                    />
                  </Form.Item>
                  <Form.Item
                    name='email'
                    rules={[{ type: 'email', message: 'Valid email' }]}
                  >
                    <Input
                      prefix={<MailOutlined className='!text-white/45' />}
                      placeholder='Email (optional)'
                      aria-label='Email (optional)'
                    />
                  </Form.Item>
                  <Form.Item
                    name='password'
                    rules={[
                      { required: true, message: 'Enter password' },
                      { min: 8, message: 'At least 8 characters' },
                    ]}
                  >
                    <Input.Password
                      prefix={<LockOutlined className='!text-white/45' />}
                      placeholder='Password'
                      aria-label='Password'
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type='primary'
                      htmlType='submit'
                      loading={loading}
                      block
                      size='large'
                      style={{
                        height: 46,
                        borderRadius: 12,
                        fontWeight: 700,
                        fontSize: 16,
                      }}
                    >
                      Register
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />

        <div className='text-center mt-1'>
          <Button
            type='link'
            size='small'
            onClick={() => navigate('/index')}
            className='!text-white/45 hover:!text-aurora-cyan transition-colors font-semibold'
          >
            Back to Search
          </Button>
        </div>
      </Card>
    </div>
  )
}
