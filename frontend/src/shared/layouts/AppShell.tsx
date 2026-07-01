import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Puzzle, LogOut, Sun, Moon, Globe, SquareLibrary, KeyRound, Container, Activity } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useUserStore } from '@/store/user'
import { useThemeStore } from '@/store/theme'
import { cn } from '@/lib/utils'
import { useLogsConfig } from '@/features/grafana/useLogsConfig'

const RAIL_LINK =
  'flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'
const RAIL_ACTIVE = 'bg-muted text-foreground'

export default function AppShell() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const user = useUserStore((s) => s.user)
  const clear = useUserStore((s) => s.clear)
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { theme, toggle } = useThemeStore()
  const { data: logsConfig } = useLogsConfig()

  function handleLogout() {
    clear()
    window.location.href = '/auth/logout'
  }

  function toggleLang() {
    i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Rail */}
      <nav className="flex w-12 flex-col items-center gap-2 border-r bg-card py-3">
        <NavLink
          to="/workspaces"
          className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
          title={t('workspaces.title')}
        >
          <LayoutDashboard size={18} />
        </NavLink>
        <NavLink
          to="/recipes"
          className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
          title={t('recipes.title')}
        >
          <Puzzle size={18} />
        </NavLink>
        <NavLink
          to="/profiles"
          className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
          title={t('profiles.title')}
        >
          <SquareLibrary size={18} />
        </NavLink>
        <NavLink
          to="/git-credentials"
          className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
          title={t('gitCredentials.title')}
        >
          <KeyRound size={18} />
        </NavLink>
        <NavLink
          to="/compose"
          className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)}
          title={t('compose.title')}
        >
          <Container size={18} />
        </NavLink>
        {logsConfig?.enabled && logsConfig.grafana_url && (
          <a
            href={logsConfig.grafana_url}
            target="_blank"
            rel="noopener noreferrer"
            className={RAIL_LINK}
            title={t('nav.logs')}
          >
            <Activity size={18} />
          </a>
        )}

        {/* Profile menu at bottom */}
        <div className="mt-auto">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className={RAIL_LINK} title={t('nav.profile')}>
                <span className="text-xs font-semibold uppercase">
                  {user?.login.slice(0, 2) ?? '?'}
                </span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="right" align="end" className="w-48">
              <DropdownMenuLabel className="text-xs text-muted-foreground">
                {user?.login}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={toggle}>
                {theme === 'dark' ? (
                  <Sun size={14} className="mr-2" />
                ) : (
                  <Moon size={14} className="mr-2" />
                )}
                {t('nav.theme')}: {t(theme === 'dark' ? 'nav.dark' : 'nav.light')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={toggleLang}>
                <Globe size={14} className="mr-2" />
                {t('nav.language')}: {i18n.language.startsWith('fr') ? 'EN' : 'FR'}
              </DropdownMenuItem>

              {isAdmin && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => navigate('/admin/hypervisor-types')}>
                    {t('admin.hypervisorTypes')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/hypervisors')}>
                    {t('admin.hypervisors')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/hosts')}>
                    {t('admin.hosts')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/recipes')}>
                    {t('admin.sharedRecipes')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/profile-sources')}>
                    {t('admin.profileSources.navLabel')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/oidc')}>
                    {t('admin.oidc.navLabel')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/network')}>
                    {t('admin.network.navLabel')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/compose')}>
                    {t('compose.admin.navLabel')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate('/admin/jinja-templates')}>
                    {t('jinjaTemplates.title')}
                  </DropdownMenuItem>
                </>
              )}

              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="text-destructive">
                <LogOut size={14} className="mr-2" />
                {t('nav.logout')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
