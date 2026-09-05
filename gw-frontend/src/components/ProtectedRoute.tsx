import { useAuth } from '@/contexts/AuthContext'
import { Button } from 'antd'
import type { ReactNode } from 'react'

interface ProtectedRouteProps {
  children: ReactNode
  /** If true, render children in a blurred/disabled state instead of redirecting */
  fallbackMode?: boolean
  fallback?: ReactNode
  /** v4.35: Minimum role required to access (Fix #1) */
  requiredRole?: 'observer' | 'analyst' | 'admin'
}

/**
 * Wraps content that requires authentication.
 *
 * - fallbackMode=true: renders children but shows a login prompt overlay (for comments section).
 * - fallbackMode=false: redirects to /login (for full-page protection).
 */
export default function ProtectedRoute({
  children,
  fallbackMode,
  fallback,
  requiredRole,
}: ProtectedRouteProps) {
  const { user, loading } = useAuth()

  if (loading) return null

  // v4.35: Role-based access check (Fix #1)
  if (requiredRole && user) {
    const roleHierarchy: Record<string, number> = {
      observer: 1,
      analyst: 2,
      admin: 3,
    }
    const userLevel = roleHierarchy[user.role] || 0
    const requiredLevel = roleHierarchy[requiredRole] || 0
    if (userLevel < requiredLevel) {
      return (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <h2>Permission Denied</h2>
          <p>
            Your role ({user.role}) does not have access to this page. Required
            role: {requiredRole}+
          </p>
        </div>
      )
    }
  }
  if (user) return <>{children}</>

  if (fallbackMode) {
    return fallback ? (
      <>{fallback}</>
    ) : (
      <div className='flex items-center justify-center py-8 text-gray-400'>
        <span>
          <Button type='link' href='/login'>
            Login
          </Button>{' '}
          to leave comments
        </span>
      </div>
    )
  }

  // Full redirect
  window.location.href = '/login'
  return null
}
