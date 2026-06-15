import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'
import AppShell from '@/shared/layouts/AppShell'
import AdminGuard from '@/shared/layouts/AdminGuard'
import RequireAuth from '@/features/auth/RequireAuth'
import LoginPage from '@/features/auth/LoginPage'
import AuthCallbackPage from '@/features/auth/AuthCallbackPage'

const WorkspaceList = lazy(() => import('@/features/workspaces/WorkspaceList'))
const WorkspaceCreate = lazy(() => import('@/features/workspaces/WorkspaceCreate'))
const RecipeCatalog = lazy(() => import('@/features/recipes/RecipeCatalog'))
const AdminHosts = lazy(() => import('@/features/admin/AdminHosts'))
const AdminRecipes = lazy(() => import('@/features/admin/AdminRecipes'))
const AdminProxmox = lazy(() => import('@/features/admin/AdminProxmox'))
const AdminHypervisorTypes = lazy(() => import('@/features/admin/AdminHypervisorTypes'))
const ProfileList = lazy(() => import('@/features/profiles/ProfileList'))
const ProfileEditor = lazy(() => import('@/features/profiles/ProfileEditor'))
const AdminProfiles = lazy(() => import('@/features/admin/AdminProfiles'))
const AdminProfileSources = lazy(() => import('@/features/admin/AdminProfileSources'))

function Wrap({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>
}

export const router = createBrowserRouter([
  { path: '/auth/login', element: <LoginPage /> },
  { path: '/auth/callback', element: <AuthCallbackPage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/workspaces" replace /> },
      { path: '/workspaces', element: <Wrap><WorkspaceList /></Wrap> },
      { path: '/workspaces/new', element: <Wrap><WorkspaceCreate /></Wrap> },
      { path: '/recipes', element: <Wrap><RecipeCatalog /></Wrap> },
      { path: '/profiles', element: <Wrap><ProfileList /></Wrap> },
      { path: '/profiles/new', element: <Wrap><ProfileEditor /></Wrap> },
      { path: '/profiles/:slug', element: <Wrap><ProfileEditor /></Wrap> },
      {
        path: '/admin/hosts',
        element: <AdminGuard><Wrap><AdminHosts /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/recipes',
        element: <AdminGuard><Wrap><AdminRecipes /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/profiles',
        element: <AdminGuard><Wrap><AdminProfiles /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/profile-sources',
        element: <AdminGuard><Wrap><AdminProfileSources /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/hypervisors',
        element: <AdminGuard><Wrap><AdminProxmox /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/hypervisor-types',
        element: <AdminGuard><Wrap><AdminHypervisorTypes /></Wrap></AdminGuard>,
      },
    ],
  },
])
