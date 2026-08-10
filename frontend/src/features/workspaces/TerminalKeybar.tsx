import { useTranslation } from 'react-i18next'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ClipboardPaste,
  Copy,
  CornerDownLeft,
  IndentIncrease,
  OctagonX,
} from 'lucide-react'
import { toast } from 'sonner'

interface Props {
  /** Écrit des données brutes dans le stdin de la session (via la WS ouverte). */
  onSend: (data: string) => void
  /** Sélection à copier : la courante, sinon la dernière non vide ('' si aucune). */
  getSelection: () => string
}

/** Barre de touches/actions tactiles pour la fenêtre de session SSH.
 *
 * Usage mobilité (pas de clavier physique). Sémantique « actions utiles » :
 * les boutons rendent le service attendu plutôt que d'émuler des chords bruts.
 * Front mince — Échap/Interrompre/Coller écrivent dans le stdin de la session
 * via la WS déjà ouverte (`\x1b`, `\x03`, texte presse-papier) ; la PTY backend
 * traduit `\x03` en SIGINT du process au premier plan. Copier lit la sélection
 * xterm vers le presse-papier. Premier lot extensible (Ctrl+D, Tab, flèches…). */
export default function TerminalKeybar({ onSend, getSelection }: Props) {
  const { t } = useTranslation()

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) onSend(text)
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
      <button
        type="button"
        className={btn}
        onClick={() => onSend('\x1b')}
        title={t('workspaces.terminals.keybar.escTitle')}
      >
        <CornerDownLeft className="h-3.5 w-3.5" />
        {t('workspaces.terminals.keybar.esc')}
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
        onClick={() => onSend('\t')}
        title={t('workspaces.terminals.keybar.tabTitle')}
      >
        <IndentIncrease className="h-3.5 w-3.5" />
        {t('workspaces.terminals.keybar.tab')}
      </button>
      <button
        type="button"
        className={btn}
        onClick={() => onSend('\x03')}
        title={t('workspaces.terminals.keybar.interruptTitle')}
      >
        <OctagonX className="h-3.5 w-3.5" />
        {t('workspaces.terminals.keybar.interrupt')}
      </button>
      <button
        type="button"
        className={btn}
        onClick={paste}
        title={t('workspaces.terminals.keybar.pasteTitle')}
      >
        <ClipboardPaste className="h-3.5 w-3.5" />
        {t('workspaces.terminals.keybar.paste')}
      </button>
      <button
        type="button"
        className={btn}
        onClick={copy}
        title={t('workspaces.terminals.keybar.copyTitle')}
      >
        <Copy className="h-3.5 w-3.5" />
        {t('workspaces.terminals.keybar.copy')}
      </button>
    </div>
  )
}
