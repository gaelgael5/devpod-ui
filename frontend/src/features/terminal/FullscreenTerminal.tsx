import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RotateCw } from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { SearchAddon } from '@xterm/addon-search'
import { UnicodeGraphemesAddon } from '@xterm/addon-unicode-graphemes'
import { Button } from '@/components/ui/button'
import TerminalKeybar from '@/features/workspaces/TerminalKeybar'
import { openTerminalLink } from './openTerminalLink'
import TerminalSearchBar, { type SearchResults } from './TerminalSearchBar'
import '@xterm/xterm/css/xterm.css'

interface Props {
  /** Chemin WebSocket same-origin, query comprise (ex. `/me/workspaces/x/ssh?session=y`). */
  wsPath: string
  /** Titre d'onglet (optionnel : le parent peut déjà le gérer). */
  title?: string
  /**
   * Envoyer les messages de redimensionnement (JSON `{type:"resize"}`) au backend.
   * VRAI pour l'endpoint workspace (tmux le gère) ; FAUX pour un endpoint qui
   * traite toute trame comme du stdin (ex. `/admin/hosts/.../ssh`), sinon le
   * JSON serait tapé dans le shell. Défaut : vrai.
   */
  resize?: boolean
}

/**
 * Terminal SSH plein écran (onglet). Généralise le terminal de session : xterm +
 * WebSocket + overlay de reconnexion + barre de touches. La cible est fournie via
 * `wsPath`, ce qui couvre indifféremment session/shell/VM de test/host Docker.
 */
export default function FullscreenTerminal({ wsPath, title, resize = true }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const terminalRef = useRef<Terminal | null>(null)
  // Dernière sélection non vide : la sélection xterm est volatile (toute frappe,
  // resize ou reset d'écran l'efface) — on la mémorise pour le bouton Copier.
  const lastSelectionRef = useRef('')
  const searchRef = useRef<SearchAddon | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<SearchResults | null>(null)
  const [disconnected, setDisconnected] = useState(false)
  const [epoch, setEpoch] = useState(0)
  const tRef = useRef(t)
  useLayoutEffect(() => {
    tRef.current = t
  })

  // Titre d'onglet distinctif (optionnel).
  useEffect(() => {
    if (!title) return
    const previous = document.title
    document.title = title
    return () => { document.title = previous }
  }, [title])

  useEffect(() => {
    let intentional = false
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: "'Courier New', monospace",
      fontSize: 13,
      theme: { background: '#0d0d1a', foreground: '#e0e0ff', cursor: '#e0e0ff' },
      // Requis par l'addon unicode-graphemes : `terminal.unicode` est une API
      // « proposed » de xterm. Sans ce drapeau, loadAddon LÈVE — et l'exception
      // remontait au rendu React, faisant avaler toute la page terminal par
      // l'ErrorBoundary (panne du 20/08 : plus aucune fenêtre SSH ne s'ouvrait).
      allowProposedApi: true,
    })
    // Les addons sont des AMÉLIORATIONS : aucun ne doit pouvoir empêcher le
    // terminal de s'afficher. On isole donc chaque chargement — l'échec part en
    // console.warn (remonté à Loki via Faro) et le terminal reste utilisable.
    // `fit` est la seule exception : sans lui le terminal est inexploitable.
    const loadOptional = (name: string, make: () => Parameters<typeof terminal.loadAddon>[0]) => {
      try {
        terminal.loadAddon(make())
        return true
      } catch (err) {
        console.warn(`[terminal] addon ${name} non chargé`, err)
        return false
      }
    }

    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    // Liens cliquables : les outils en ligne de commande affichent des URL
    // d'authentification (`claude` en premier) qu'il faut sinon recopier à la
    // main — pénible, et la sélection xterm ne survit pas au redraw d'un TUI.
    // L'addon gère les URL coupées par le retour à la ligne, ce qu'un simple
    // clic sur du texte brut ne saurait pas faire.
    loadOptional('web-links', () => new WebLinksAddon((_event, uri) => openTerminalLink(uri)))
    // Largeur des caractères : sans cet addon, xterm applique les tables Unicode 6
    // et calcule mal la largeur des emoji et des caractères larges (CJK). Une
    // largeur fausse décale TOUT le redessin d'un TUI — cadres brisés, curseur à
    // côté. Les sorties d'agents et de Termix en sont pleines.
    if (loadOptional('unicode-graphemes', () => new UnicodeGraphemesAddon())) {
      terminal.unicode.activeVersion = '15-graphemes'
    }
    // Recherche dans le scrollback.
    const searchAddon = new SearchAddon()
    const searchOk = loadOptional('search', () => searchAddon)
    searchRef.current = searchOk ? searchAddon : null
    const resultsDisposable = searchOk
      ? searchAddon.onDidChangeResults((r) =>
          setSearchResults({ resultIndex: r.resultIndex, resultCount: r.resultCount }),
        )
      : { dispose: () => {} }

    if (termRef.current) {
      terminal.open(termRef.current)
      requestAnimationFrame(() => { fitAddon.fit(); terminal.focus() })
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}${wsPath}`)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    terminalRef.current = terminal

    const sendResize = (cols: number, rows: number) => {
      if (resize && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    }
    ws.onopen = () => sendResize(terminal.cols, terminal.rows)

    const encoder = new TextEncoder()
    const dataDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
    })
    const resizeDisposable = terminal.onResize(({ cols, rows }) => sendResize(cols, rows))

    // Copy-on-select : la sélection part au presse-papier dès qu'elle se stabilise
    // (debounce du drag). Indispensable ici : la sélection xterm ne survit ni à une
    // frappe ni aux redraws des TUI, le copier différé (menu, bouton) est fragile.
    // Les échecs (permission presse-papier, contexte) partent en console.warn —
    // remontés à Loki via Faro, sans casser la session ; le bouton Copier reste
    // le chemin explicite.
    // Diagnostic temporaire (préfixe terminal_diag, relayé à Loki via Faro) :
    // la sélection souris n'aboutit pas chez certains clients — tracer ce que
    // reçoit réellement xterm pour situer la perte (DOM ? xterm ? clipboard ?).
    // (payloads sérialisés en JSON : Faro rend « [object Object] » sinon)
    console.warn(`terminal_diag: mount ${JSON.stringify({ wsPath })}`)
    let mouseLogs = 0
    const diagMouse = (ev: MouseEvent) => {
      if (mouseLogs < 6) {
        mouseLogs++
        console.warn(
          `terminal_diag: mouse ${JSON.stringify({
            type: ev.type,
            button: ev.button,
            shift: ev.shiftKey,
            mouseTracking: terminal.modes.mouseTrackingMode,
          })}`,
        )
      }
    }
    const termHost = termRef.current
    termHost?.addEventListener('mousedown', diagMouse)
    termHost?.addEventListener('mouseup', diagMouse)
    let selLogs = 0

    let copyTimer: ReturnType<typeof setTimeout> | undefined
    let copyLogged = false
    const selectionDisposable = terminal.onSelectionChange(() => {
      const text = terminal.getSelection()
      if (selLogs < 10) {
        selLogs++
        console.warn(`terminal_diag: selection_change ${JSON.stringify({ chars: text.length })}`)
      }
      if (!text) return
      lastSelectionRef.current = text
      clearTimeout(copyTimer)
      copyTimer = setTimeout(() => {
        if (!navigator.clipboard) {
          console.warn('terminal_copy_on_select: navigator.clipboard indisponible')
          return
        }
        navigator.clipboard.writeText(text).then(
          () => {
            if (!copyLogged) {
              copyLogged = true
              console.warn(`terminal_copy_on_select: ok ${JSON.stringify({ chars: text.length })}`)
            }
          },
          (err: unknown) => console.warn(`terminal_copy_on_select: échec ${String(err)}`),
        )
      }, 200)
    })

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      terminal.write(data)
    }
    ws.onclose = () => {
      terminal.write(tRef.current('admin.sshTerminal.connClosed'))
      if (!intentional) setDisconnected(true)
    }
    ws.onerror = () => terminal.write(tRef.current('admin.sshTerminal.connError'))

    const onResize = () => fitAddon.fit()
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(() => fitAddon.fit())
    if (termRef.current) ro.observe(termRef.current)

    return () => {
      intentional = true
      window.removeEventListener('resize', onResize)
      termHost?.removeEventListener('mousedown', diagMouse)
      termHost?.removeEventListener('mouseup', diagMouse)
      ro.disconnect()
      dataDisposable.dispose()
      resizeDisposable.dispose()
      selectionDisposable.dispose()
      resultsDisposable.dispose()
      clearTimeout(copyTimer)
      ws.close()
      terminal.dispose()
      wsRef.current = null
      terminalRef.current = null
      searchRef.current = null
    }
  }, [wsPath, resize, epoch])

  const sendToTerminal = (data: string) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data))
    terminalRef.current?.focus()
  }

  // Ctrl/Cmd+Maj+F : Ctrl+F seul appartient au shell distant (recherche de
  // l'historique, navigation d'un TUI) — l'intercepter le priverait d'une touche.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function closeSearch() {
    setSearchOpen(false)
    setSearchResults(null)
    // Les surlignages survivraient à la fermeture de la barre.
    searchRef.current?.clearDecorations()
    terminalRef.current?.focus()
  }

  return (
    <div className="absolute inset-0 flex flex-col bg-[#0d0d1a]">
      {searchOpen && (
        <TerminalSearchBar
          results={searchResults}
          onClose={closeSearch}
          onFind={(term, direction) => {
            const addon = searchRef.current
            if (!addon) return
            if (direction === 'next') addon.findNext(term)
            else addon.findPrevious(term)
          }}
        />
      )}
      <div className="relative min-h-0 flex-1">
        <div ref={termRef} className="absolute inset-0" />
        {disconnected && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60 backdrop-blur-sm">
            <p className="text-sm text-white/80">{t('workspaces.terminals.disconnected')}</p>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setDisconnected(false); setEpoch((e) => e + 1) }}
            >
              <RotateCw className="mr-1 h-3.5 w-3.5" />
              {t('workspaces.terminals.reconnect')}
            </Button>
          </div>
        )}
      </div>
      <TerminalKeybar
        onSearch={() => setSearchOpen(true)}
        onSend={sendToTerminal}
        getSelection={() =>
          terminalRef.current?.getSelection() || lastSelectionRef.current
        }
      />
    </div>
  )
}
