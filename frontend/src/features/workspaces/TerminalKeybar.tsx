import type { MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ClipboardPaste,
  Copy,
  CornerDownLeft,
  Keyboard,
  OctagonX,
  Search,
} from 'lucide-react'
import { toast } from 'sonner'

interface Props {
  /** Écrit des données brutes dans le stdin de la session (via la WS ouverte). */
  onSend: (data: string) => void
  /** Sélection à copier : la courante, sinon la dernière non vide ('' si aucune). */
  getSelection: () => string
  /** Ouvre la recherche. Absent = bouton masqué (terminal sans addon de recherche). */
  onSearch?: () => void
  /**
   * Injecte du texte collé. Distinct de `onSend` : le collage doit passer par
   * xterm, qui normalise les sauts de ligne et encadre le texte des marqueurs
   * de « bracketed paste » quand l'application distante a activé le mode 2004.
   * Sans cela, un TUI reçoit le collage comme une rafale de frappes et réécrit
   * son prompt en cours de route — le texte arrive abîmé.
   */
  onPaste: (text: string) => void
  /** Ouvre ou masque le clavier mobile. Absent = bouton masque. */
  onToggleKeyboard?: () => void
  /** Le clavier est-il ouvert ? Pilote l'etat du bouton pour le lecteur d'ecran. */
  keyboardOpen?: boolean
}

/** Barre de touches/actions tactiles pour la fenêtre de session SSH.
 *
 * Usage mobilité (pas de clavier physique). Sémantique « actions utiles » :
 * les boutons rendent le service attendu plutôt que d'émuler des chords bruts.
 * Front mince — Échap/Interrompre/Coller écrivent dans le stdin de la session
 * via la WS déjà ouverte (`\x1b`, `\x03`, texte presse-papier) ; la PTY backend
 * traduit `\x03` en SIGINT du process au premier plan. Copier lit la sélection
 * xterm vers le presse-papier. Premier lot extensible (Ctrl+D, Tab, flèches…). */
/**
 * Empeche le bouton de voler le focus au terminal.
 *
 * Sans cela il fallait rendre le focus a xterm apres chaque envoi — ce qui, sur
 * mobile, rouvrait le clavier a chaque appui. Annuler le `mousedown` conserve
 * le focus la ou il etait : le clavier reste ouvert s'il l'etait, ferme sinon.
 * Le `click` part normalement, seul le deplacement du focus est supprime.
 */
function keepFocus(e: MouseEvent) {
  e.preventDefault()
}

export default function TerminalKeybar({
  onSend,
  onPaste,
  getSelection,
  onSearch,
  onToggleKeyboard,
  keyboardOpen = false,
}: Props) {
  const { t } = useTranslation()

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) onPaste(text)
    } catch {
      toast.error(t('workspaces.terminals.keybar.pasteError'))
    }
  }

  const copy = async () => {
    const sel = getSelection()
    if (!sel) {
      toast.info(t('workspaces.terminals.keybar.copyEmpty'))
      return
    }
    try {
      await navigator.clipboard.writeText(sel)
      toast.success(t('workspaces.terminals.keybar.copied'))
    } catch {
      toast.error(t('workspaces.terminals.keybar.pasteError'))
    }
  }

  // Cibles tactiles confortables sur mobile (min 36px), plus compactes en desktop.
  const btn =
    'inline-flex min-h-9 min-w-9 items-center justify-center gap-1 rounded border ' +
    'border-white/15 bg-white/5 px-3 py-1.5 text-sm text-white/80 transition-colors ' +
    'hover:bg-white/15 active:bg-white/25 focus:outline-none focus-visible:ring-1 ' +
    'focus-visible:ring-white/40 sm:min-h-0 sm:min-w-0 sm:px-2.5 sm:py-1 sm:text-xs'

  return (
    <div
      className="flex shrink-0 flex-wrap items-center gap-1.5 border-t border-white/10 bg-[#0d0d1a] px-2 py-1.5"
      role="toolbar"
      aria-label={t('workspaces.terminals.keybar.esc')}
    >
      {/* Clavier : au tactile c'est le SEUL moyen d'ecrire. La tape sur la
          surface ne donne plus le focus a xterm — le defilement de l'historique
          annule le clic que le navigateur en synthetise. */}
      {onToggleKeyboard && (
        <button
          type="button"
          className={btn}
          onMouseDown={keepFocus}
          onClick={onToggleKeyboard}
          aria-pressed={keyboardOpen}
          title={t('workspaces.terminals.keybar.keyboardTitle')}
          aria-label={t('workspaces.terminals.keybar.keyboard')}
        >
          <Keyboard className="h-3.5 w-3.5" />
        </button>
      )}
      <button
        type="button"
        className={btn}
        onMouseDown={keepFocus}
        onClick={() => onSend('\x1b')}
        title={t('workspaces.terminals.keybar.escTitle')}
        aria-label={t('workspaces.terminals.keybar.esc')}
      >
        <CornerDownLeft className="h-3.5 w-3.5" />
      </button>
      {/* Flèches : séquences ANSI CSI (mode curseur normal) — navigation dans les
          menus/CLI interactifs depuis un écran tactile. */}
      {(
        [
          ['\x1b[A', 'arrowUp', ArrowUp],
          ['\x1b[B', 'arrowDown', ArrowDown],
          ['\x1b[C', 'arrowRight', ArrowRight],
          ['\x1b[D', 'arrowLeft', ArrowLeft],
        ] as const
      ).map(([seq, key, Icon]) => (
        <button
          key={key}
          type="button"
          className={btn}
          onMouseDown={keepFocus}
          onClick={() => onSend(seq)}
          title={t(`workspaces.terminals.keybar.${key}`)}
          aria-label={t(`workspaces.terminals.keybar.${key}`)}
        >
          <Icon className="h-3.5 w-3.5" />
        </button>
      ))}
      <button
        type="button"
        className={btn}
        onMouseDown={keepFocus}
        onClick={() => onSend('\x03')}
        title={t('workspaces.terminals.keybar.interruptTitle')}
        aria-label={t('workspaces.terminals.keybar.interrupt')}
      >
        <OctagonX className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        className={btn}
        onMouseDown={keepFocus}
        onClick={paste}
        title={t('workspaces.terminals.keybar.pasteTitle')}
        aria-label={t('workspaces.terminals.keybar.paste')}
      >
        <ClipboardPaste className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        className={btn}
        onMouseDown={keepFocus}
        onClick={copy}
        title={t('workspaces.terminals.keybar.copyTitle')}
        aria-label={t('workspaces.terminals.keybar.copy')}
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
      {/* Recherche : le raccourci clavier n'existe pas sur mobile, or c'est
          précisément la cible de cette barre. */}
      {onSearch && (
        <button
          type="button"
          className={btn}
          onMouseDown={keepFocus}
          onClick={onSearch}
          title={t('workspaces.terminals.keybar.searchTitle', {
            defaultValue: 'Rechercher dans le terminal (Ctrl+Maj+F)',
          })}
          aria-label={t('workspaces.terminals.keybar.search', {
            defaultValue: 'Rechercher',
          })}
        >
          <Search className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
