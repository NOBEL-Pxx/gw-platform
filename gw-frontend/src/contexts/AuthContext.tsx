import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react'
import { message } from '@/util/AntdMessage'
import axios from 'axios'

interface User {
  userId: string
  username: string
  role: string
}

interface AuthState {
  user: User | null
  token: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<boolean>
  register: (
    username: string,
    password: string,
    email?: string,
  ) => Promise<boolean>
  logout: () => void
}

const AuthContext = createContext<AuthState>({
  user: null,
  token: null,
  loading: true,
  login: async () => false,
  register: async () => false,
  logout: () => {},
})

const TOKEN_KEY = 'gw_auth_token'
const USER_KEY = 'gw_auth_user'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY),
  )
  const [user, setUser] = useState<User | null>(() => {
    try {
      const stored = localStorage.getItem(USER_KEY)
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })
  const [loading, setLoading] = useState(true)

  // Verify token on mount (restore session after refresh). R6.35: 5s timeout
  // so loading=false ALWAYS runs, preventing splash from getting stuck.
  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    let cancelled = false
    const timeoutId = setTimeout(() => {
      if (!cancelled) setLoading(false)
    }, 5000)
    axios
      .get('/api/auth/verify', {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 4500,
      })
      .then((res) => {
        const d = res.data?.data
        if (d && d.userId) {
          const u: User = {
            userId: d.userId,
            username: d.username,
            role: d.role,
          }
          setUser(u)
          localStorage.setItem(USER_KEY, JSON.stringify(u))
        } else {
          // Token invalid — clear
          setToken(null)
          setUser(null)
          localStorage.removeItem(TOKEN_KEY)
          localStorage.removeItem(USER_KEY)
        }
      })
      .catch(() => {
        // Network error or backend down - keep existing state
      })
      .finally(() => {
        clearTimeout(timeoutId)
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      clearTimeout(timeoutId)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      try {
        // R6.35: 12s timeout so login() never hangs forever.
        const res = await axios.post(
          '/api/auth/login',
          { username, password },
          { timeout: 12000 },
        )
        const d = res.data?.data
        if (d && d.token) {
          setToken(d.token)
          const u: User = {
            userId: d.userId,
            username: d.username,
            role: d.role,
          }
          setUser(u)
          localStorage.setItem(TOKEN_KEY, d.token)
          localStorage.setItem(USER_KEY, JSON.stringify(u))
          message.success(`Welcome, ${d.username}`)
          return true
        }
        message.error(res.data?.error?.msg || 'Login failed')
        return false
      } catch (err: unknown) {
        const e = err as { response?: { data?: { error?: { msg?: string } } } }
        message.error(e.response?.data?.error?.msg || 'Login failed')
        return false
      }
    },
    [],
  )

  const register = useCallback(
    async (
      username: string,
      password: string,
      email?: string,
    ): Promise<boolean> => {
      try {
        const res = await axios.post('/api/auth/register', {
          username,
          password,
          email: email || '',
        })
        const d = res.data?.data
        if (d && d.token) {
          setToken(d.token)
          const u: User = {
            userId: d.userId,
            username: d.username,
            role: d.role,
          }
          setUser(u)
          localStorage.setItem(TOKEN_KEY, d.token)
          localStorage.setItem(USER_KEY, JSON.stringify(u))
          message.success(`Registered as ${d.username}`)
          return true
        }
        message.error(res.data?.error?.msg || 'Registration failed')
        return false
      } catch (err: unknown) {
        const e = err as { response?: { data?: { error?: { msg?: string } } } }
        message.error(e.response?.data?.error?.msg || 'Registration failed')
        return false
      }
    },
    [],
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    message.info('Logged out')
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, token, loading, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}
