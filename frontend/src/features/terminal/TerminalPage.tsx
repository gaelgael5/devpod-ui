import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import FullscreenTerminal from './FullscreenTerminal'
import { useVisualViewport } from './useVisualViewport'

/**
 * Page plein écran d'un terminal SSH ouvert dans son propre onglet. La cible est
 * passée en `?ws=<chemin WebSocket>` (+ `?title=`). Le chemin est validé
 * (same-origin, préfixe autorisé) pour éviter toute injection d'hôte.
 *
 * `resize` : les endpoints workspace ET host tournent dans tmux derrière un PTY
 * (pont mutualisé) et interprètent les messages de redimensionnement.
 */
function isSafeWsPath(ws: string): boolean {
  // Chemin absolu same-origin uniquement (pas de `//host`, pas de scheme).
  if (!ws.startsWith('/') || ws.startsWith('//')) return false
  return ws.startsWith('/me/') || ws.startsWith('/admin/')
}

export default function TerminalPage() {
  const { t } = useTranslation()
  // Le clavier mobile se pose PAR-DESSUS la page sans la redimensionner : en
  // `h-screen`, tout le bas du terminal — prompt, ligne de statut tmux, barre
  // de touches — passait dessous et devenait invisible. Et pour reveler la
  // saisie, Safari DEPLACE en plus la fenetre visible (`haut`) : sans
  // translation, tout l'affichage paraissait decale, bande vide a l'ecran.
  const vue = useVisualViewport()
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

  const resize = ws.startsWith('/me/workspaces/') || ws.startsWith('/admin/hosts/')

  return (
    <div
      className="relative w-screen overflow-hidden bg-[#0d0d1a]"
      // `100vh` en repli : sans l'API, on garde le dimensionnement d'origine
      // plutot qu'une geometrie inventee. `translate` et non `top` : pas de
      // reflow, le ResizeObserver du terminal ne repart que sur la hauteur.
      style={{
        height: vue?.hauteur ?? '100vh',
        transform: vue ? `translateY(${vue.haut}px)` : undefined,
      }}
      data-testid="terminal-page"
    >
      <FullscreenTerminal wsPath={ws} title={title} resize={resize} />
    </div>
  )
}
