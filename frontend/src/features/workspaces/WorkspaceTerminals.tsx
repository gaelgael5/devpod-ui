import { useState, useEffect } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Plus, RotateCw, Terminal, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import WorkspaceSessionTerminal from './WorkspaceSessionTerminal'
import InitializersMenu from './InitializersMenu'
import CreateSessionDialog from './CreateSessionDialog'
import { useWorkspaceStatus } from './useWorkspaceStatus'
import {
  useWorkspaceSessions,
  useWorkspaceStartRecipes,
  useDeleteSession,
} from './useWorkspaceSessions'

// ── Page principale ───────────────────────────────────────────────────────────

export default function WorkspaceTerminals() {
  const { wsName } = useParams<{ wsName: string }>()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const { data: sessions = [] } = useWorkspaceSessions(wsName)
  const { data: startRecipes = [] } = useWorkspaceStartRecipes(wsName)
  const { data: wsStatus } = useWorkspaceStatus(wsName!)
  // ?session=<nom> présélectionne une session (ouverture depuis la carte
  // workspace dans un nouvel onglet). Si elle n'existe pas/plus, les effets
  // ci-dessous retombent sur la première session disponible.
  const [selected, setSelected] = useState<string | null>(
    () => searchParams.get('session')
  )
  const [epochs, setEpochs] = useState<Record<string, number>>({})
  const [createOpen, setCreateOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const deleteSession = useDeleteSession()

  // Force le remontage du terminal d'une session → nouvelle connexion WebSocket
  // (le tmux backend survit : on se rattache via ?session=).
  function reconnect(s: string) {
    setSelected(s)
    setEpochs((prev) => ({ ...prev, [s]: (prev[s] ?? 0) + 1 }))
  }

  useEffect(() => {
    if (sessions.length > 0 && selected === null) setSelected(sessions[0])
  }, [sessions, selected])

  useEffect(() => {
    if (selected !== null && sessions.length > 0 && !sessions.includes(selected)) {
      setSelected(sessions[0])
    } else if (selected !== null && sessions.length === 0) {
      setSelected(null)
    }
  }, [sessions, selected])

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* En-tête */}
      <header className="flex h-10 flex-shrink-0 items-center gap-2 border-b bg-card px-3">
        <Button variant="ghost" size="sm" asChild className="gap-1.5 text-muted-foreground hover:text-foreground">
          <Link to="/workspaces">
            <ArrowLeft size={14} />
            {t('workspaces.terminals.back')}
          </Link>
        </Button>
        <div className="h-4 w-px bg-border" />
        {/* Toggle sidebar */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
          onClick={() => setSidebarOpen((o) => !o)}
          title={sidebarOpen ? t('workspaces.terminals.hideSidebar') : t('workspaces.terminals.showSidebar')}
        >
          {sidebarOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
        </Button>
        <div className="h-4 w-px bg-border" />
        <Terminal size={14} className="text-muted-foreground" />
        <span className="text-sm font-medium">{wsName}</span>
        {/* Bouton "+ session" dans le header quand sidebar fermée */}
        {!sidebarOpen && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-2 h-7 gap-1 text-muted-foreground hover:text-foreground"
            onClick={() => setCreateOpen(true)}
          >
            <Plus size={13} />
            {t('workspaces.terminals.newSession')}
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <InitializersMenu wsName={wsName!} enabled={wsStatus?.status === 'running'} />
          {wsStatus?.url && (
            <>
              <div className="h-4 w-px bg-border" />
              <Button size="sm" variant="outline" className="gap-1.5" asChild>
                <a href={wsStatus.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink size={13} />
                  {t('workspaces.actions.openVscode')}
                </a>
              </Button>
            </>
          )}
        </div>
      </header>

      {/* Corps */}
      <div className="flex min-h-0 flex-1">
        {/* Panneau sessions — masquable */}
        {sidebarOpen && (
          <aside className="flex w-40 flex-shrink-0 flex-col border-r bg-card">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t('workspaces.terminals.title')}
              </span>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6"
                onClick={() => setCreateOpen(true)}
                title={t('workspaces.terminals.newSession')}
              >
                <Plus size={14} />
              </Button>
            </div>

            <ul className="flex-1 overflow-y-auto">
              {sessions.length === 0 ? (
                <li className="px-3 py-3 text-xs text-muted-foreground">
                  {t('workspaces.terminals.noSession')}
                </li>
              ) : (
                sessions.map((s) => (
                  <li key={s} className="group relative">
                    <button
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-2 pr-14 text-sm transition-colors hover:bg-muted',
                        selected === s ? 'bg-muted text-foreground' : 'text-muted-foreground'
                      )}
                      onClick={() => setSelected(s)}
                    >
                      <span className={cn(
                        'h-1.5 w-1.5 flex-shrink-0 rounded-full',
                        selected === s ? 'bg-green-500' : 'bg-muted-foreground/40'
                      )} />
                      <span className="truncate">{s}</span>
                    </button>
                    <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        className="rounded p-0.5 hover:bg-primary/10 hover:text-primary"
                        title={t('workspaces.terminals.reconnectSession')}
                        onClick={(e) => {
                          e.stopPropagation()
                          reconnect(s)
                        }}
                      >
                        <RotateCw size={12} />
                      </button>
                      <button
                        className="rounded p-0.5 hover:bg-destructive/10 hover:text-destructive"
                        title={t('workspaces.terminals.deleteSession')}
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteSession.mutate(
                            { wsName: wsName!, sessionName: s },
                            { onError: (err) => toast.error(err.message) },
                          )
                        }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  </li>
                ))
              )}
            </ul>

            <div className="border-t p-2">
              <Button
                size="sm"
                variant="outline"
                className="w-full gap-1.5"
                onClick={() => setCreateOpen(true)}
              >
                <Plus size={13} />
                {t('workspaces.terminals.newSession')}
              </Button>
            </div>
          </aside>
        )}

        {/* Zone terminal — position:relative donne des dimensions explicites à xterm */}
        <div className="relative min-h-0 min-w-0 flex-1">
          {selected ? (
            <WorkspaceSessionTerminal
              key={`${selected}#${epochs[selected] ?? 0}`}
              wsName={wsName!}
              session={selected}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-3">
              <Terminal size={32} className="text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">{t('workspaces.terminals.noSession')}</p>
              <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
                {t('workspaces.terminals.noSessionAction')}
              </Button>
            </div>
          )}
        </div>
      </div>

      {createOpen && (
        <CreateSessionDialog
          wsName={wsName!}
          sessions={sessions}
          startRecipes={startRecipes}
          onClose={() => setCreateOpen(false)}
          onCreate={(name) => setSelected(name)}
        />
      )}
    </div>
  )
}
