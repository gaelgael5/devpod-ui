import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import type { ReactNode } from 'react'
import AppShell from '@/shared/layouts/AppShell'
import AdminGuard from '@/shared/layouts/AdminGuard'
import VaultGuard from '@/shared/layouts/VaultGuard'
import RequireAuth from '@/features/auth/RequireAuth'
import LoginPage from '@/features/auth/LoginPage'
import AuthCallbackPage from '@/features/auth/AuthCallbackPage'

const WorkspaceList = lazy(() => import('@/features/workspaces/WorkspaceList'))
const WorkspaceCreate = lazy(() => import('@/features/workspaces/WorkspaceCreate'))
const WorkspaceTerminals = lazy(() => import('@/features/workspaces/WorkspaceTerminals'))
const RecipeCatalog = lazy(() => import('@/features/recipes/RecipeCatalog'))
const AdminHosts = lazy(() => import('@/features/admin/AdminHosts'))
const AdminRecipes = lazy(() => import('@/features/admin/AdminRecipes'))
const AdminProxmox = lazy(() => import('@/features/admin/AdminProxmox'))
const AdminHypervisorTypes = lazy(() => import('@/features/admin/AdminHypervisorTypes'))
const AdminOidc = lazy(() => import('@/features/admin/AdminOidc'))
const ProfileList = lazy(() => import('@/features/profiles/ProfileList'))
const ProfileEditor = lazy(() => import('@/features/profiles/ProfileEditor'))
const AdminProfileEditor = lazy(() => import('@/features/admin/AdminProfileEditor'))
const AdminProfileSources = lazy(() => import('@/features/admin/AdminProfileSources'))
const CredentialsPage = lazy(() => import('@/features/git-credentials/CredentialsPage'))
const VaultSetup = lazy(() => import('@/features/vault/VaultSetup'))
const VaultUnlock = lazy(() => import('@/features/vault/VaultUnlock'))
const VaultRecover = lazy(() => import('@/features/vault/VaultRecover'))
const VaultKeys = lazy(() => import('@/features/vault/VaultKeys'))

function Wrap({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>
}

/**
 * Catch-all : une URL sans route React. Si c'est une route BACKEND (`/auth/*`, ex.
 * `/auth/logout` servi par erreur via une SPA en cache), on force une vraie requête
 * serveur en bustant le cache. Sinon on renvoie proprement vers l'accueil — jamais
 * l'erreur 404 brute de react-router.
 */
function RouteFallback() {
  const loc = useLocation()
  const isBackend = loc.pathname.startsWith('/auth/')
  useEffect(() => {
    if (isBackend) {
      const sep = loc.search ? '&' : '?'
      window.location.replace(`${loc.pathname}${loc.search}${sep}_=${Date.now()}`)
    }
  }, [isBackend, loc.pathname, loc.search])
  return isBackend ? null : <Navigate to="/" replace />
}

export const router = createBrowserRouter([
  { path: '/auth/login', element: <LoginPage /> },
  { path: '/auth/callback', element: <AuthCallbackPage /> },
  {
    // Page plein-écran gestion des sessions terminal — hors AppShell
    path: '/workspaces/:wsName/terminals',
    element: (
      <RequireAuth>
        <Wrap>
          <WorkspaceTerminals />
        </Wrap>
      </RequireAuth>
    ),
  },
  // Routes vault : authentifiées mais hors VaultGuard (accessibles même coffre verrouillé)
  {
    path: '/vault/setup',
    element: (
      <RequireAuth>
        <Wrap>
          <VaultSetup />
        </Wrap>
      </RequireAuth>
    ),
  },
  {
    path: '/vault/unlock',
    element: (
      <RequireAuth>
        <Wrap>
          <VaultUnlock />
        </Wrap>
      </RequireAuth>
    ),
  },
  {
    path: '/vault/recover',
    element: (
      <RequireAuth>
        <Wrap>
          <VaultRecover />
        </Wrap>
      </RequireAuth>
    ),
  },
  {
    element: (
      <RequireAuth>
        <VaultGuard>
          <AppShell />
        </VaultGuard>
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
      { path: '/git-credentials', element: <Wrap><CredentialsPage /></Wrap> },
      { path: '/vault/keys', element: <Wrap><VaultKeys /></Wrap> },
      {
        path: '/admin/hosts',
        element: <AdminGuard><Wrap><AdminHosts /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/recipes',
        element: <AdminGuard><Wrap><AdminRecipes /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/profiles/new',
        element: <AdminGuard><Wrap><AdminProfileEditor /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/profiles/:slug',
        element: <AdminGuard><Wrap><AdminProfileEditor /></Wrap></AdminGuard>,
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
      {
        path: '/admin/oidc',
        element: <AdminGuard><Wrap><AdminOidc /></Wrap></AdminGuard>,
      },
    ],
  },
  // Filet : URL sans route React → jamais l'erreur 404 brute de react-router.
  { path: '*', element: <RouteFallback /> },
])
