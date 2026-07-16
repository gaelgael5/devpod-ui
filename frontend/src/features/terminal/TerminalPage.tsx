import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import FullscreenTerminal from './FullscreenTerminal'

/**
 * Page plein écran d'un terminal SSH ouvert dans son propre onglet. La cible est
 * passée en `?ws=<chemin WebSocket>` (+ `?title=`). Le chemin est validé
 * (same-origin, préfixe autorisé) pour éviter toute injection d'hôte.
 *
 * `resize` : seul l'endpoint workspace (tmux) interprète les messages de
 * redimensionnement ; l'endpoint host les traiterait comme du stdin — on ne les
 * envoie donc que pour `/me/workspaces/…`.
 */
function isSafeWsPath(ws: string): boolean {
  // Chemin absolu same-origin uniquement (pas de `//host`, pas de scheme).
  if (!ws.startsWith('/') || ws.startsWith('//')) return false
  return ws.startsWith('/me/') || ws.startsWith('/admin/')
}

export default function TerminalPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const ws = params.get('ws') ?? ''
  const title = params.get('title') ?? undefined

  if (!isSafeWsPath(ws)) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <p className="text-sm text-destructive">{t('terminal.invalidTarget')}</p>
      </div>
    )
  }

  const resize = ws.startsWith('/me/workspaces/')

  return (
    <div className="relative h-screen w-screen bg-[#0d0d1a]">
      <FullscreenTerminal wsPath={ws} title={title} resize={resize} />
    </div>
  )
}
