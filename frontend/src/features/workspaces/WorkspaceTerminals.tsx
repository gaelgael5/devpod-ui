import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Terminal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import WorkspaceSessionTerminal from './WorkspaceSessionTerminal'
import CreateSessionDialog from './CreateSessionDialog'
import {
  useWorkspaceSessions,
  useWorkspaceStartRecipes,
} from './useWorkspaceSessions'

/** Terminal plein écran d'une session de workspace — sans chrome (ni en-tête ni
 panneau latéral) : la gestion des sessions (création, liste, ouverture) vit
 dans le menu « Sessions (N) » de la carte workspace, chaque session s'ouvrant
 dans son propre onglet via ?session=<nom>. */
export default function WorkspaceTerminals() {
  const { wsName } = useParams<{ wsName: string }>()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const { data: sessions = [] } = useWorkspaceSessions(wsName)
  const { data: startRecipes = [] } = useWorkspaceStartRecipes(wsName)
  // ?session=<nom> présélectionne la session ; si elle n'existe pas/plus, les
  // effets ci-dessous retombent sur la première session disponible.
  const [selected, setSelected] = useState<string | null>(
    () => searchParams.get('session')
  )
  const [createOpen, setCreateOpen] = useState(false)

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
      {/* Zone terminal — position:relative donne des dimensions explicites à xterm */}
      <div className="relative min-h-0 min-w-0 flex-1">
        {selected ? (
          <WorkspaceSessionTerminal wsName={wsName!} session={selected} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <Terminal size={32} className="text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">{t('workspaces.terminals.noSession')}</p>
            <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
              {t('workspaces.terminals.noSessionAction')}
            </Button>
          </div>
        )}
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
