import { Suspense } from 'react'
import { createBrowserRouter, Link, Navigate } from 'react-router-dom'
import Layout from '@common/Layout'
import {
  LandingPage,
  Home,
  Index,
  AssistantPage,
  LoginPage,
  SettingsPage,
  MyCommentsPage,
  CollectionsPage,
  SharedCollectionPage,
  AdminAuditPage,
  AdminConfigPage,
  AdminProvenancePage,
  AdminObservabilityPage,
  LazyPageType,
} from './router/pages'

// eslint-disable-next-line react-refresh/only-export-components
function LazyPage({ Page }: { Page: LazyPageType }) {
  return (
    <Suspense fallback={null}>
      <Page />
    </Suspense>
  )
}

const routesConfig = [
  // R6.9a: Landing page renders WITHOUT Layout wrapper (no nav bar / header).
  // It's a pure fullscreen splash that fades out and navigates to /index
  // (which IS wrapped in Layout).
  {
    path: '/',
    element: <LazyPage Page={LandingPage} />,
  },
  {
    path: '/login',
    element: <LazyPage Page={LoginPage} />,
  },
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        path: 'search',
        element: <LazyPage Page={Home} />,
      },
      {
        path: 'index',
        element: <LazyPage Page={Index} />,
      },
      {
        path: 'assistant',
        element: <LazyPage Page={AssistantPage} />,
      },
      {
        path: 'settings',
        element: <LazyPage Page={SettingsPage} />,
      },
      // v4.13: New routes
      // v4.DIVS: /my-comments replaces /favorites (older label was 'My Comments')
      {
        path: 'my-comments',
        element: <LazyPage Page={MyCommentsPage} />,
      },
      {
        path: 'favorites',
        element: <Navigate to='my-comments' replace />,
      },
      {
        path: 'collections',
        element: <LazyPage Page={CollectionsPage} />,
      },
      {
        path: 'collections/shared/:token',
        element: <LazyPage Page={SharedCollectionPage} />,
      },
      // v4.35: Admin audit dashboard (Fix #6)
      {
        path: 'admin/audit',
        element: <LazyPage Page={AdminAuditPage} />,
      },
      // v4.48: Admin config + provenance (Fixes #3, #4)
      {
        path: 'admin/config',
        element: <LazyPage Page={AdminConfigPage} />,
      },
      {
        path: 'admin/provenance',
        element: <LazyPage Page={AdminProvenancePage} />,
      },
      // R6.45: Observability dashboard
      {
        path: 'admin/observability',
        element: <LazyPage Page={AdminObservabilityPage} />,
      },
      {
        path: '*',
        element: (
          <div
            className='flex items-center justify-center h-full'
            style={{ background: '#0A0F1E' }}
          >
            <div className='text-center'>
              <h2
                className='text-4xl font-bold text-white/30 mb-4'
                style={{ fontFamily: 'monospace' }}
              >
                404
              </h2>
              <p className='text-white/45 text-sm mb-6'>Page not found</p>
              <Link
                to='/index'
                className='text-aurora-cyan hover:text:aurora-cyan/80 font-semibold text-sm'
              >
                Return Home
              </Link>
            </div>
          </div>
        ),
      },
    ],
  },
]

const router = createBrowserRouter(routesConfig, {
  future: {
    v7_relativeSplatPath: true,
    v7_fetcherPersist: true,
    v7_normalizeFormMethod: true,
    v7_partialHydration: true,
    v7_skipActionErrorRevalidation: true,
  },
})

export default router
