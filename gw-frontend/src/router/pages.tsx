import { lazy, LazyExoticComponent, ComponentType } from 'react'

// R6.57: Extracted from router.tsx to keep the route table a single
// component-only file (satisfies react-refresh/only-export-components).
// All pages remain code-split via React.lazy() so initial bundle stays small.

const LandingPage = lazy(() => import('@/pages/landing'))
const Home = lazy(() => import('@/pages/home'))
const Index = lazy(() => import('@/pages/index'))
const AssistantPage = lazy(() => import('@/pages/assistant'))
const LoginPage = lazy(() => import('@/pages/login'))
const SettingsPage = lazy(() => import('@/pages/settings'))
const MyCommentsPage = lazy(() => import('@/pages/my-comments'))
const CollectionsPage = lazy(() => import('@/pages/collections'))
const SharedCollectionPage = lazy(() => import('@/pages/collections/shared'))
const AdminAuditPage = lazy(() => import('@/pages/admin/audit'))
const AdminConfigPage = lazy(() => import('@/pages/admin/config'))
const AdminProvenancePage = lazy(() => import('@/pages/admin/provenance'))
const AdminObservabilityPage = lazy(() => import('@/pages/admin/observability'))

export type LazyPageType = LazyExoticComponent<ComponentType>

export {
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
}
