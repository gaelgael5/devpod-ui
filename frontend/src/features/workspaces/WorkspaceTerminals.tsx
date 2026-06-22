import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Plus, Terminal, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import WorkspaceSessionTerminal from './WorkspaceSessionTerminal'
import { useWorkspaceStatus } from './useWorkspaceStatus'
import {
  useWorkspaceSessions,
  useWorkspaceStartRecipes,
  useCreateSession,
  useDeleteSession,
  type WorkspaceStartRecipe,
} from './useWorkspaceSessions'

function computeNextName(sessions: string[]): string {
  const existing = new Set(sessions)
  for (let i = 1; i <= 100; i++) {
    const n = `session${i}`
    if (!existing.has(n)) return n
  }
  return `session${sessions.length + 1}`
}

// ── Dialog "Nouvelle session" ─────────────────────────────────────────────────

interface CreateDialogProps {
  wsName: string
  sessions: string[]
  startRecipes: WorkspaceStartRecipe[]
  onClose: () => void
  onCreate: (name: string) => void
}

function CreateSessionDialog({ wsName, sessions, startRecipes, onClose, onCreate }: CreateDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(() => computeNextName(sessions))
  const nameEdited = useRef(false)
  const [startRecipe, setStartRecipe] = useState(() => startRecipes[0]?.id ?? '')
  const create = useCreateSession()

  useEffect(() => {
    if (!nameEdited.current) setName(computeNextName(sessions))
  }, [sessions])

  function handleSubmit() {
    create.mutate(
      { wsName, name, startRecipe: startRecipe || undefined },
      {
        onSuccess: () => { onCreate(name); onClose() },
        onError: (err) => toast.error(err.message),
      }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('workspaces.terminals.createTitle')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="session-name">{t('workspaces.terminals.nameLabel')}</Label>
            <Input
              id="session-name"
              value={name}
              onChange={(e) => { nameEdited.current = true; setName(e.target.value) }}
              placeholder={t('workspaces.terminals.namePlaceholder')}
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter' && name) handleSubmit() }}
            />
          </div>
          {startRecipes.length === 1 && (
            <label className="flex items-center gap-2 cursor-pointer select-none text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 cursor-pointer accent-primary"
                checked={startRecipe !== ''}
                onChange={(e) => setStartRecipe(e.target.checked ? startRecipes[0].id : '')}
              />
              <span>
                {startRecipes[0].id}
                {startRecipes[0].description && (
                  <span className="text-muted-foreground ml-1">— {startRecipes[0].description}</span>
                )}
              </span>
            </label>
          )}
          {startRecipes.length > 1 && (
            <div className="space-y-1.5">
              <Label htmlFor="session-recipe">{t('workspaces.terminals.startRecipeLabel')}</Label>
              <select
                id="session-recipe"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={startRecipe}
                onChange={(e) => setStartRecipe(e.target.value)}
              >
                <option value="">{t('workspaces.terminals.startRecipeNone')}</option>
                {startRecipes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id}{r.description ? ` — ${r.description}` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('workspaces.terminals.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={!name || create.isPending}>
            {create.isPending ? '…' : t('workspaces.terminals.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Page principale ───────────────────────────────────────────────────────────

export default function WorkspaceTerminals() {
  const { wsName } = useParams<{ wsName: string }>()
  const { t } = useTranslation()
  const { data: sessions = [] } = useWorkspaceSessions(wsName)
  const { data: startRecipes = [] } = useWorkspaceStartRecipes(wsName)
  const { data: wsStatus } = useWorkspaceStatus(wsName!)
  const [selected, setSelected] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const deleteSession = useDeleteSession()

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
        {wsStatus?.url && (
          <>
            <div className="ml-auto h-4 w-px bg-border" />
            <Button size="sm" variant="outline" className="gap-1.5" asChild>
              <a href={wsStatus.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={13} />
                {t('workspaces.actions.openVscode')}
              </a>
            </Button>
          </>
        )}
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
                        'flex w-full items-center gap-2 px-3 py-2 pr-8 text-sm transition-colors hover:bg-muted',
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
                    <button
                      className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
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
              key={selected}
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
