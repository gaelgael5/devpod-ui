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
import { createLinkCollector } from './linkCollector'
import { isTouchOnly } from './isTouchOnly'
import { createHistoryScroller } from './historyScroll'
import { createDoubleTapDetector } from './doubleTap'
import { isPastLineEnd } from './lineHitTest'
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
  // Zone de saisie cachee de xterm : c'est elle, et elle seule, qu'iOS regarde
  // pour decider d'afficher son clavier. Le bouton « clavier » de la barre la
  // vise directement.
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const [inputFocused, setInputFocused] = useState(false)
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

    // Ajustement GARDÉ. Un `fit()` sur un conteneur de taille nulle — onglet
    // masqué, page en arrière-plan — calcule des dimensions aberrantes et les
    // ENVOIE à tmux via onResize : au retour, tmux a redessiné pour une largeur
    // qui n'existe pas et tout est décalé. Le contenu étant alors mal reflowé,
    // les URL coupées par le retour à la ligne deviennent illisibles pour la
    // détection de liens — mêmes causes, deux symptômes (signalés le 20/08).
    const safeFit = () => {
      const el = termRef.current
      if (!el || document.hidden) return
      const { width, height } = el.getBoundingClientRect()
      if (width < 2 || height < 2) return
      try {
        fitAddon.fit()
      } catch (err) {
        console.warn('[terminal] fit ignoré', err)
      }
    }

    // Liens cliquables : les outils en ligne de commande affichent des URL
    // d'authentification (`claude` en premier) qu'il faut sinon recopier à la
    // main — pénible, et la sélection xterm ne survit pas au redraw d'un TUI.
    //
    // L'addon détecte les liens en relisant le buffer *rendu*. Sur une URL
    // repliée par un terminal étroit, cette reconstitution s'est révélée
    // fautive : des blocs entiers manquaient au milieu de l'URL. On ouvre donc
    // ce que le collecteur a lu dans le flux brut, où l'URL est intacte, et
    // l'addon ne sert plus qu'à repérer l'endroit cliqué.
    const links = createLinkCollector()
    loadOptional('web-links', () => new WebLinksAddon((_event, uri) => openTerminalLink(links.resolve(uri))))
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

    const onInputFocus = () => setInputFocused(true)
    const onInputBlur = () => setInputFocused(false)
    let input: HTMLTextAreaElement | null = null

    if (termRef.current) {
      terminal.open(termRef.current)
      // Le bouton « clavier » bascule : il lui faut l'etat courant de la saisie.
      input = terminal.textarea ?? null
      inputRef.current = input
      input?.addEventListener('focus', onInputFocus)
      input?.addEventListener('blur', onInputBlur)
      // Ajustement SYNCHRONE avant d'ouvrir la WebSocket : `ssh` fixe la taille
      // du PTY distant au démarrage d'après son propre terminal, et ne la relit
      // jamais. Différé d'une frame, il partait sur les 80x24 par défaut et tmux
      // s'y calait pour toute la session. La seconde passe en rAF rattrape la
      // mise en page une fois stabilisée (polices, clavier mobile).
      safeFit()
      requestAnimationFrame(() => {
        safeFit()
        // Pas d'autofocus au tactile : donner le focus a la zone de saisie
        // cachee de xterm deroule le clavier iOS des l'ouverture de la session,
        // qui mange la moitie de l'ecran alors que la barre de touches existe
        // justement pour s'en passer. Au clavier physique on garde l'autofocus :
        // sans lui il faudrait cliquer avant de pouvoir taper.
        if (!isTouchOnly()) terminal.focus()
      })
    }


    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // La taille voyage dans l'URL : le pont doit la connaître avant l'exec, un
    // message de contrôle arriverait trop tard.
    const url = new URL(wsPath, window.location.origin)
    if (resize) {
      url.searchParams.set('cols', String(terminal.cols))
      url.searchParams.set('rows', String(terminal.rows))
    }
    const ws = new WebSocket(`${proto}//${window.location.host}${url.pathname}${url.search}`)
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

    // Molette et glissement remontent dans l'historique tmux. Necessaire parce
    // que sous tmux le scrollback de xterm reste vide (ecran alterne) : sans
    // cela le geste ne produit rien. Voir historyScroll.ts.
    const scroller = createHistoryScroller({
      isAlternate: () => terminal.buffer.active.type === 'alternate',
      send: (data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
      },
    })
    // Double tape -> Tab, mais SEULEMENT dans le vide apres la fin de la ligne.
    // Sur du texte la double tape reste a xterm, qui selectionne le mot touche —
    // c'est le seul moyen de copier au doigt. Au-dela du dernier caractere il
    // n'y a rien a selectionner, et le geste veut dire « complete ce que je
    // viens de taper » : Tab.
    const doubleTap = createDoubleTapDetector()
    /** Position de la derniere tape, pour situer la double tape dans la grille. */
    let dernierePosition = { x: 0, y: 0 }

    const surface = termRef.current
    const onWheel = (e: WheelEvent) => {
      if (scroller.wheel(e.deltaY)) e.preventDefault()
    }
    const onTouchStart = (e: TouchEvent) => {
      const t = e.touches[0]
      doubleTap.start(t.clientX, t.clientY, e.touches.length)
      dernierePosition = { x: t.clientX, y: t.clientY }
      // Un seul doigt : le pincement de zoom ne doit pas devenir un defilement.
      if (e.touches.length === 1) scroller.touchStart(t.clientY)
    }
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      const t = e.touches[0]
      doubleTap.move(t.clientX, t.clientY)
      // Pas de preventDefault sans mouvement : l'appui long, donc la selection
      // native sur mobile, reste intact.
      if (scroller.touchMove(t.clientY)) e.preventDefault()
    }
    const onTouchEnd = (e: TouchEvent) => {
      scroller.touchEnd()
      if (!doubleTap.end()) return
      // Sur du texte : on ne touche a rien, le `dblclick` que le navigateur
      // synthetise fait selectionner le mot par xterm.
      if (!isPastLineEnd(terminal, dernierePosition.x, dernierePosition.y)) return
      // `preventDefault` supprime le `dblclick`, qui poserait ici une selection
      // vide et deplacerait le curseur de selection pour rien.
      e.preventDefault()
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode('\t'))
    }
    // `passive: false` : sans cela le navigateur refuse le preventDefault et
    // laisse son propre defilement s'ajouter au notre.
    surface?.addEventListener('wheel', onWheel, { passive: false })
    surface?.addEventListener('touchstart', onTouchStart, { passive: true })
    surface?.addEventListener('touchmove', onTouchMove, { passive: false })
    surface?.addEventListener('touchend', onTouchEnd, { passive: false })

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

    // `stream: true` : une trame peut couper un caractère multi-octets en deux.
    const decoder = new TextDecoder()
    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      links.push(typeof data === 'string' ? data : decoder.decode(data, { stream: true }))
      terminal.write(data)
    }
    ws.onclose = () => {
      terminal.write(tRef.current('admin.sshTerminal.connClosed'))
      if (!intentional) setDisconnected(true)
    }
    ws.onerror = () => terminal.write(tRef.current('admin.sshTerminal.connError'))

    const onResize = () => safeFit()
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(() => safeFit())
    if (termRef.current) ro.observe(termRef.current)

    // Retour sur l'onglet : re-mesurer puis forcer un redessin complet. Safari
    // mobile réduit la page en arrière-plan (barre d'adresse, clavier) et les
    // dimensions de caractère mises en cache par xterm ne valent plus rien.
    const onVisible = () => {
      if (document.hidden) return
      // Safari coupe la WebSocket en mettant la page en arriere-plan, et ne
      // delivre pas toujours le `close` au retour : l'application se croit
      // connectee, l'overlay de reconnexion ne s'affiche pas, et plus rien de
      // ce qu'on tape ne part. Session figee, sans le moindre indice a l'ecran.
      // On relit donc l'etat reel au retour plutot que d'attendre l'evenement.
      //
      // CONNECTING est exclu a dessein : une socket en cours d'ouverture n'est
      // pas morte, et la remonter ici bouclerait (`focus` et `visibilitychange`
      // arrivent ensemble).
      if (ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
        // Remonte la session. tmux la reattache dans l'etat ou elle etait.
        setDisconnected(false)
        setEpoch((e) => e + 1)
        return
      }
      requestAnimationFrame(() => {
        safeFit()
        terminal.refresh(0, terminal.rows - 1)
      })
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    // Retour depuis le cache de navigation (bouton « precedent » de Safari) :
    // la page revient telle quelle, sans `visibilitychange`, avec une socket
    // deja morte.
    window.addEventListener('pageshow', onVisible)

    return () => {
      intentional = true
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
      window.removeEventListener('pageshow', onVisible)
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
      surface?.removeEventListener('wheel', onWheel)
      surface?.removeEventListener('touchstart', onTouchStart)
      surface?.removeEventListener('touchmove', onTouchMove)
      surface?.removeEventListener('touchend', onTouchEnd)
      input?.removeEventListener('focus', onInputFocus)
      input?.removeEventListener('blur', onInputBlur)
      inputRef.current = null
      terminalRef.current = null
      searchRef.current = null
    }
  }, [wsPath, resize, epoch])

  /**
   * Ouvre ou masque le clavier mobile.
   *
   * Seul chemin fiable au tactile, et c'est pour cela qu'il existe : sous tmux
   * le defilement de l'historique appelle `preventDefault` sur `touchmove` des
   * le premier pixel de mouvement, ce qui supprime le clic synthetise par iOS —
   * or c'est ce clic qui donnait le focus a xterm. Un doigt ne se pose jamais
   * parfaitement immobile : la tape sur la surface n'ouvre donc plus rien.
   * Sans ce bouton, la session est en lecture seule.
   */
  const toggleKeyboard = () => {
    if (inputFocused) inputRef.current?.blur()
    else terminalRef.current?.focus()
  }

  // Pas de `focus()` ici : sur mobile il ouvre le clavier a chaque appui sur la
  // barre, qui mange la moitie de l'ecran alors que ces boutons existent
  // justement pour eviter d'avoir a taper. La barre empeche deja le focus de
  // lui echapper (mousedown annule), donc le terminal garde celui qu'il avait.
  const sendToTerminal = (data: string) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data))
  }

  // Le collage passe par xterm et non par la WS : `paste()` normalise les sauts
  // de ligne (\r\n -> \r) et encadre le texte des marqueurs de « bracketed
  // paste » lorsque l'application distante a activé le mode 2004. Envoyé brut,
  // un code d'authentification arrivait abîmé dans le prompt de `claude`.
  const pasteToTerminal = (text: string) => {
    terminalRef.current?.paste(text)
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
        {/* `touch-action: manipulation` supprime le zoom double-tape d'iOS, qui
            avalait la seconde tape et retardait le clic de la premiere. Le
            defilement reste a notre charge : il passe par le geste, pas par le
            defilement natif. */}
        <div
          ref={termRef}
          className="absolute inset-0 touch-manipulation"
          data-testid="terminal-surface"
        />
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
        keyboardOpen={inputFocused}
        onToggleKeyboard={toggleKeyboard}
        onSearch={() => setSearchOpen(true)}
        onSend={sendToTerminal}
        onPaste={pasteToTerminal}
        getSelection={() =>
          terminalRef.current?.getSelection() || lastSelectionRef.current
        }
      />
    </div>
  )
}
