import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Card, Tabs, Typography } from 'antd'
import UserOutlined from '@ant-design/icons/UserOutlined'
import LockOutlined from '@ant-design/icons/LockOutlined'
import MailOutlined from '@ant-design/icons/MailOutlined'
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
    <div className='min-h-screen flex items-center justify-center bg-nebula relative overflow-hidden animate-fade-in'>
      <div
        className='fixed pointer-events-none z-0'
        style={{
          left: mousePos.x - 150,
          top: mousePos.y - 150,
          width: 300,
          height: 300,
          background:
            'radial-gradient(circle, rgba(0,240,255,0.08) 0%, rgba(124,58,237,0.05) 40%, transparent 70%)',
          borderRadius: '50%',
          transition: 'left 0.15s ease-out, top 0.15s ease-out',
        }}
      />

      <div
        className='fixed top-1/4 left-1/4 w-96 h-96 rounded-full animate-float'
        style={{
          background:
            'radial-gradient(circle, rgba(124,58,237,0.05) 0%, transparent 70%)',
          animationDelay: '0s',
        }}
      />
      <div
        className='fixed bottom-1/4 right-1/4 w-80 h-80 rounded-full animate-float'
        style={{
          background:
            'radial-gradient(circle, rgba(0,240,255,0.05) 0%, transparent 70%)',
          animationDelay: '3s',
        }}
      />
      <div
        className='fixed top-1/2 right-1/3 w-64 h-64 rounded-full animate-float'
        style={{
          background:
            'radial-gradient(circle, rgba(255,0,110,0.04) 0%, transparent 70%)',
          animationDelay: '5s',
        }}
      />

      <Card
        className='relative z-10 animate-slide-up'
        style={{
          width: 'min(420px, 92vw)',
          borderRadius: 20,
          background: 'rgba(255,255,255,0.06)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          border: '1px solid rgba(255,255,255,0.14)',
          boxShadow:
            '0 8px 40px rgba(0,0,0,0.5), 0 0 100px rgba(0,240,255,0.05)',
        }}
        bordered={false}
      >
        <div className='text-center mb-6'>
          <img
            src='/gw-logo.png'
            alt='AliCPT DIVS Logo'
            className='mx-auto mb-2'
            style={{
              width: 'min(240px, 60vw)',
              height: 'auto',
              filter: 'drop-shadow(0 0 30px rgba(0,240,255,0.35))',
            }}
          />
          <Text className='!text-white/55 text-sm tracking-wider font-semibold'>
            Astronomical Data Platform
          </Text>
          <div
            className='mt-3 mx-auto w-16 h-0.5 rounded'
            style={{
              background: 'linear-gradient(90deg, #00F0FF, #7C3AED, #FF006E)',
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
