import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Terminal, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import WorkspaceSessionTerminal from './WorkspaceSessionTerminal'
import CreateSessionDialog from './CreateSessionDialog'
import {
  useSessionClients,
  useWorkspaceSessions,
  useWorkspaceStartRecipes,
} from './useWorkspaceSessions'
import { useVisualViewportHeight } from '@/features/terminal/useVisualViewportHeight'

/** Terminal plein écran d'une session de workspace — sans chrome (ni en-tête ni
 panneau latéral) : la gestion des sessions (création, liste, ouverture) vit
 dans le menu « Sessions (N) » de la carte workspace, chaque session s'ouvrant
 dans son propre onglet via ?session=<nom>. */
export default function WorkspaceTerminals() {
  const { wsName } = useParams<{ wsName: string }>()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const hauteurVisible = useVisualViewportHeight()
  const { data: sessions = [], isFetched } = useWorkspaceSessions(wsName)
  const { data: startRecipes = [] } = useWorkspaceStartRecipes(wsName)
  const urlSession = searchParams.get('session')
  // Session choisie explicitement (ex. tout juste créée) — prime sur l'URL.
  const [picked, setPicked] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  // Session effective, DÉRIVÉE (pas d'effet → pas de race) :
  //   1. un choix explicite prime toujours (session créée à l'instant) ;
  //   2. sinon on honore ?session=<nom> ;
  //   3. la retombée sur la première session n'a lieu QU'APRÈS le chargement de
  //      la liste — sinon `sessions` vide pendant le fetch écrasait ?session=
  //      et toute session ouverte par URL retombait sur la première (bug).
  const selected =
    picked !== null
      ? picked
      : !isFetched
        ? urlSession
        : urlSession && sessions.includes(urlSession)
          ? urlSession
          : (sessions[0] ?? null)

  // Notre propre terminal compte pour un : le partage commence a deux.
  const { data: clients } = useSessionClients(wsName, selected)
  const partagee = (clients?.clients ?? 0) >= 2

  // Titre d'onglet distinctif : chaque session s'ouvre dans son propre onglet,
  // sans ça ils s'appellent tous « DevPod Portal ».
  useEffect(() => {
    const previous = document.title
    document.title = selected ? `${selected} — ${wsName}` : `${wsName} — sessions`
    return () => { document.title = previous }
  }, [wsName, selected])

  return (
    <div
      className="flex flex-col overflow-hidden bg-background"
      // Meme raison que la page terminal plein ecran : le clavier mobile se pose
      // PAR-DESSUS la page sans la redimensionner, donc `h-screen` laissait tout
      // le bas — prompt compris — sous le clavier. Les logs le montraient bien :
      // la frappe partait (`readyState: 1`), elle etait juste invisible.
      style={{ height: hauteurVisible ?? '100vh' }}
      data-testid="workspace-terminals"
    >
      {/* Deux appareils sur la meme session : tmux cale la fenetre sur le client
          le plus recemment actif, et l'ecran le plus petit recoit des lignes
          trop longues. Rien ne l'expliquait a l'utilisateur, qui n'y voyait
          qu'un affichage casse. */}
      {partagee && (
        <div
          role="status"
          className="flex shrink-0 items-start gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
          data-testid="session-partagee"
        >
          <Users className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{t('workspaces.terminals.sharedSession')}</span>
        </div>
      )}
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
          onCreate={(name) => setPicked(name)}
        />
      )}
    </div>
  )
}
