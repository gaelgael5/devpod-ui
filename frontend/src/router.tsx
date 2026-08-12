import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppShell from '@/shared/layouts/AppShell'
import AdminGuard from '@/shared/layouts/AdminGuard'
import VaultGuard from '@/shared/layouts/VaultGuard'
import RequireAuth from '@/features/auth/RequireAuth'
import LoginPage from '@/features/auth/LoginPage'
import AuthCallbackPage from '@/features/auth/AuthCallbackPage'
import {
  AdminAgentTypes,
  AdminCompose,
  AdminHosts,
  AdminHypervisorTypes,
  AdminJinjaTemplates,
  AdminLogs,
  AdminBastion,
  AdminTermix,
  AdminNetwork,
  AdminOidc,
  AdminProfileEditor,
  AdminAutomations,
  AutomationEditor,
  AdminContracts,
  AdminEvents,
  AdminProfileSources,
  AdminProxmox,
  AdminRecipes,
  AdminSessions,
  AdminWorkflow,
  ApplicationsPage,
  ComposeGallery,
  ConsentPage,
  CredentialsPage,
  ProfileEditor,
  ProfileList,
  ProfilePage,
  RecipeCatalog,
  SessionsView,
  TerminalPage,
  VaultKeys,
  VaultRecover,
  VaultSetup,
  VaultUnlock,
  WorkspaceCreate,
  WorkspaceList,
  WorkspaceTerminals,
  Wrap,
} from '@/router-pages'

export const router = createBrowserRouter([
  { path: '/auth/login', element: <LoginPage /> },
  { path: '/auth/callback', element: <AuthCallbackPage /> },
  {
    // Consentement OAuth (gateway MCP) — authentifié, hors AppShell/VaultGuard.
    path: '/oauth/consent',
    element: (
      <RequireAuth>
        <Wrap>
          <ConsentPage />
        </Wrap>
      </RequireAuth>
    ),
  },
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
  {
    // Terminal SSH générique plein écran (host Docker, shell workspace, VM de
    // test) ouvert en onglet — hors AppShell. Cible via ?ws=<chemin WebSocket>.
    path: '/terminal',
    element: (
      <RequireAuth>
        <Wrap>
          <TerminalPage />
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
      { path: '/sessions', element: <Wrap><SessionsView /></Wrap> },
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
        path: '/admin/agent-types',
        element: <AdminGuard><Wrap><AdminAgentTypes /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/oidc',
        element: <AdminGuard><Wrap><AdminOidc /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/network',
        element: <AdminGuard><Wrap><AdminNetwork /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/sessions',
        element: <AdminGuard><Wrap><AdminSessions /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/logs',
        element: <AdminGuard><Wrap><AdminLogs /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/bastion',
        element: <AdminGuard><Wrap><AdminBastion /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/termix-instances',
        element: <AdminGuard><Wrap><AdminTermix /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/workflow',
        element: <AdminGuard><Wrap><AdminWorkflow /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/automations',
        element: <AdminGuard><Wrap><AdminAutomations /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/automations/contracts',
        element: <AdminGuard><Wrap><AdminContracts /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/automations/events',
        element: <AdminGuard><Wrap><AdminEvents /></Wrap></AdminGuard>,
      },
      {
        // Édition d'une règle en page pleine ('new' = création) ; les routes
        // statiques /contracts et /events priment sur ce segment dynamique.
        path: '/admin/automations/:automationId',
        element: <AdminGuard><Wrap><AutomationEditor /></Wrap></AdminGuard>,
      },
      { path: '/profile', element: <Wrap><ProfilePage /></Wrap> },
      { path: '/compose', element: <Wrap><ComposeGallery /></Wrap> },
      { path: '/applications', element: <Wrap><ApplicationsPage /></Wrap> },
      {
        path: '/admin/compose',
        element: <AdminGuard><Wrap><AdminCompose /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/jinja-templates',
        element: <AdminGuard><Wrap><AdminJinjaTemplates /></Wrap></AdminGuard>,
      },
    ],
  },
])
