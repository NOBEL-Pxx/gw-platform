// R6.45: Sentry init kicks off before render (non-blocking).
// No-op if VITE_SENTRY_DSN is unset (current production reality).
import { initSentry } from './sentry'

initSentry().catch(() => {
  /* non-fatal */
})

// import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AntdMessage from '@/util/AntdMessage.ts'
import { App as AntdApp } from 'antd'
import { AuthProvider } from '@/contexts/AuthContext'
import App from './App.tsx'
import './index.css'

createRoot(document.getElementById('root')!).render(
  // <StrictMode>
  <AntdApp>
    <AntdMessage />
    <AuthProvider>
      <App />
    </AuthProvider>
  </AntdApp>,
  // </StrictMode>,
)
