/** Pages lazy du router — module séparé pour satisfaire react-refresh :
 un fichier qui n'exporte QUE des composants reste hot-swappable, et
 `router.tsx` (fichier de composition) n'a plus à définir de composant. */
import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'

export const WorkspaceList = lazy(() => import('@/features/workspaces/WorkspaceList'))
export const WorkspaceCreate = lazy(() => import('@/features/workspaces/WorkspaceCreate'))
export const WorkspaceTerminals = lazy(() => import('@/features/workspaces/WorkspaceTerminals'))
export const TerminalPage = lazy(() => import('@/features/terminal/TerminalPage'))
export const RecipeCatalog = lazy(() => import('@/features/recipes/RecipeCatalog'))
export const AdminHosts = lazy(() => import('@/features/admin/AdminHosts'))
export const AdminRecipes = lazy(() => import('@/features/admin/AdminRecipes'))
export const AdminMachineProfiles = lazy(
  () => import('@/features/admin/AdminMachineProfiles'),
)
export const AdminHostProfiles = lazy(
  () => import('@/features/admin/AdminHostProfiles'),
)
export const AdminBillingCatalog = lazy(
  () => import('@/features/admin/AdminBillingCatalog'),
)
export const AdminProxmox = lazy(() => import('@/features/admin/AdminProxmox'))
export const AdminHypervisorTypes = lazy(() => import('@/features/admin/AdminHypervisorTypes'))
export const AdminAgentTypes = lazy(() => import('@/features/admin/AdminAgentTypes'))
export const AdminOidc = lazy(() => import('@/features/admin/AdminOidc'))
export const AdminNetwork = lazy(() => import('@/features/admin/AdminNetwork'))
export const AdminSessions = lazy(() => import('@/features/admin/AdminSessions'))
export const AdminLogs = lazy(() => import('@/features/admin/AdminLogs'))
export const AdminBastion = lazy(() => import('@/features/admin/AdminBastion'))
export const AdminTermix = lazy(() => import('@/features/admin/AdminTermix'))
export const AdminUsers = lazy(() => import('@/features/admin/AdminUsers'))
export const AdminWorkflow = lazy(() => import('@/features/admin/AdminWorkflow'))
export const AdminAutomations = lazy(() => import('@/features/automations/AdminAutomations'))
export const AutomationEditor = lazy(() => import('@/features/automations/AutomationEditorPage'))
export const AdminContracts = lazy(() => import('@/features/automations/AdminContracts'))
export const AdminEvents = lazy(() => import('@/features/automations/AdminEvents'))
export const SessionsView = lazy(() => import('@/features/sessions/SessionsView'))
export const ProfileList = lazy(() => import('@/features/profiles/ProfileList'))
export const ProfileEditor = lazy(() => import('@/features/profiles/ProfileEditor'))
export const AdminProfileEditor = lazy(() => import('@/features/admin/AdminProfileEditor'))
export const AdminProfileSources = lazy(() => import('@/features/admin/AdminProfileSources'))
export const CredentialsPage = lazy(() => import('@/features/git-credentials/CredentialsPage'))
export const VaultSetup = lazy(() => import('@/features/vault/VaultSetup'))
export const VaultUnlock = lazy(() => import('@/features/vault/VaultUnlock'))
export const VaultRecover = lazy(() => import('@/features/vault/VaultRecover'))
export const VaultKeys = lazy(() => import('@/features/vault/VaultKeys'))
export const ConsentPage = lazy(() => import('@/features/oauth/ConsentPage'))
export const ComposeGallery = lazy(() => import('@/features/compose/ComposeGallery'))
export const ApplicationsPage = lazy(() => import('@/features/applications/ApplicationsPage'))
export const AdminCompose = lazy(() => import('@/features/compose/AdminCompose'))
export const AdminJinjaTemplates = lazy(() => import('@/features/admin/AdminJinjaTemplates'))
export const ProfilePage = lazy(() => import('@/features/profile/ProfilePage'))

export function Wrap({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>
}
