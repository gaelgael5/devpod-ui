import FullscreenTerminal from '@/features/terminal/FullscreenTerminal'

interface Props {
  wsName: string
  session: string
}

/** Terminal d'une session de workspace — délègue au terminal plein écran
 *  générique (le titre d'onglet est géré par WorkspaceTerminals). */
export default function WorkspaceSessionTerminal({ wsName, session }: Props) {
  return (
    <FullscreenTerminal
      wsPath={
        `/me/workspaces/${encodeURIComponent(wsName)}/ssh` +
        `?session=${encodeURIComponent(session)}`
      }
    />
  )
}
