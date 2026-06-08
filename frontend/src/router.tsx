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
      {
        path: '/admin/hosts',
        element: <AdminGuard><Wrap><AdminHosts /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/recipes',
        element: <AdminGuard><Wrap><AdminRecipes /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/proxmox',
        element: <AdminGuard><Wrap><AdminProxmox /></Wrap></AdminGuard>,
      },
    ],
  },
])
