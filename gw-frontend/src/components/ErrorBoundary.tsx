import { Component, type ReactNode, type ErrorInfo } from 'react'
import { Alert, Button } from 'antd'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}
interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

/**
 * Global React Error Boundary — catches unhandled render errors.
 * Prevents the entire SPA from crashing due to a single component tree failure.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, errorInfo: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Caught:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div
          className='flex items-center justify-center p-8'
          style={{ background: '#0A0F1E', minHeight: 200 }}
        >
          <Alert
            type='error'
            showIcon
            message='Component Error'
            description={
              <div>
                <p className='mb-2 text-white/60'>
                  {this.state.error?.message || 'An unexpected error occurred.'}
                </p>
                {this.state.errorInfo && (
                  <details className='text-xs text-white/40 mb-3'>
                    <summary className='cursor-pointer'>Stack trace</summary>
                    <pre className='mt-1 max-h-32 overflow-auto'>
                      {this.state.errorInfo.componentStack}
                    </pre>
                  </details>
                )}
                <div className='flex gap-2'>
                  <Button
                    size='small'
                    icon={<ReloadOutlined />}
                    onClick={this.handleReset}
                  >
                    Retry Component
                  </Button>
                  <Button size='small' onClick={() => window.location.reload()}>
                    Reload Page
                  </Button>
                </div>
              </div>
            }
            style={{ maxWidth: 600 }}
          />
        </div>
      )
    }
    return this.props.children
  }
}
