import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RotateCw } from 'lucide-react'
import { toast } from 'sonner'
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
import { createHistoryScroller, pixelsDeMolette } from './historyScroll'
import { createDoubleTapDetector } from './doubleTap'
import { createSelectionHintDetector } from './selectionHint'
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
/**
 * Delai avant de se recaler sur une nouvelle taille.
 *
 * Assez long pour couvrir l'animation d'ouverture du clavier mobile, assez
 * court pour que le terminal ne reste pas visiblement mal dimensionne.
 */
export const AJUSTEMENT_MS = 150

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
  /** Publie le rafraichissement d'affichage, defini dans l'effet (ws + terminal). */
  const refreshRef = useRef<(() => void) | null>(null)
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

    // Borne comme les autres sondes. Sans elle, une session ou le focus oscille
    // — precisement le defaut qu'on cherchait a voir — inonde la collecte de
    // logs en continu, et le motif interessant se noie dans sa propre trace.
    // Douze suffisent a lire l'oscillation.
    let focusLogs = 0
    const tracerFocus = (message: string) => {
      if (focusLogs >= 12) return
      focusLogs++
      console.warn(message)
    }

    const onInputFocus = () => {
      tracerFocus('terminal_diag: saisie_focus')
      setInputFocused(true)
    }
    const onInputBlur = (e: FocusEvent) => {
      // QUI prend le focus est la seule chose qui manque pour comprendre : les
      // logs montrent le focus perdu quelques centaines de ms apres l'avoir
      // pris, en boucle, sans que rien ne dise vers quoi il part.
      const cible = e.relatedTarget instanceof Element ? e.relatedTarget : document.activeElement
      tracerFocus(
        `terminal_diag: saisie_blur ${JSON.stringify({
          vers: cible instanceof Element ? cible.tagName.toLowerCase() : null,
          classe: cible instanceof Element ? cible.className.toString().slice(0, 80) : null,
          testid: cible instanceof Element ? cible.getAttribute('data-testid') : null,
        })}`,
      )
      setInputFocused(false)
    }
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

    /**
     * Force tmux a tout redessiner.
     *
     * Quand la fenetre tmux et le terminal divergent — deux clients de tailles
     * differentes, un resize manque — l'ecran garde des rendus anciens : des
     * barres de statut empilees, des lignes qui se marchent dessus. tmux ne
     * redessine que sur changement de taille, et renvoyer la MEME taille ne
     * declenche rien.
     *
     * D'ou l'aller-retour : une taille volontairement fausse, puis la vraie a
     * la frame suivante. Deux SIGWINCH, un redessin complet. Espacer les deux
     * est necessaire — le PTY regroupe les ecritures rapprochees et tmux perd
     * alors le second (meme contrainte que le defilement de l'historique).
     */
    refreshRef.current = () => {
      safeFit()
      const { cols, rows } = terminal
      sendResize(cols, Math.max(1, rows - 1))
      requestAnimationFrame(() => {
        sendResize(cols, rows)
        terminal.refresh(0, terminal.rows - 1)
      })
    }

    const encoder = new TextEncoder()
    // Molette et glissement remontent dans l'historique tmux. Necessaire parce
    // que sous tmux le scrollback de xterm reste vide (ecran alterne) : sans
    // cela le geste ne produit rien. Voir historyScroll.ts.
    const scroller = createHistoryScroller({
      isAlternate: () => terminal.buffer.active.type === 'alternate',
      send: (data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
      },
    })

    /** Frappes clavier : le chemin le plus direct, et le dernier reste muet. */
    let dataLogs = 0
    const dataDisposable = terminal.onData((data) => {
      if (dataLogs < 10) {
        dataLogs++
        console.warn(
          `terminal_diag: data ${JSON.stringify({
            chars: data.length,
            readyState: ws.readyState,
          })}`,
        )
      }
      if (ws.readyState === WebSocket.OPEN) {
        // Le geste de defilement a fait entrer tmux en copy-mode, ou la saisie
        // est absorbee au lieu d'atteindre l'application : on en sort avant de
        // laisser passer la frappe. Sans ca, l'utilisateur qui remonte dans
        // l'historique puis se remet a taper ne voit plus rien s'inscrire.
        if (scroller.exitCopyMode()) {
          // Une frame d'ecart : tmux perd les touches ecrites dans la meme
          // lecture PTY (cf. l'en-tete de historyScroll).
          requestAnimationFrame(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
          })
          return
        }
        ws.send(encoder.encode(data))
        return
      }
      // Taper sur une socket fermee ne produisait RIEN : ni caractere a
      // l'ecran, ni message. Le clavier repond, la session non, et rien ne dit
      // laquelle des deux est en cause.
      console.warn(
        `terminal_diag: frappe_sur_socket_fermee ${JSON.stringify({ readyState: ws.readyState })}`,
      )
      setDisconnected(true)
    })
    let resizeLogs = 0
    const resizeDisposable = terminal.onResize(({ cols, rows }) => {
      if (resizeLogs < 15) {
        resizeLogs++
        console.warn(`terminal_diag: resize ${JSON.stringify({ cols, rows })}`)
      }
      sendResize(cols, rows)
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
      if (scroller.wheel(pixelsDeMolette(e, terminal.rows))) e.preventDefault()
    }

    /**
     * Molette : empeche xterm d'envoyer FLECHE HAUT / BAS a l'application.
     *
     * Sous tmux, le tampon alterne n'a pas de scrollback — et xterm traduit
     * alors la molette en touches de curseur (`ESC [ A` / `ESC [ B`), qu'il
     * ecrit directement dans la session. Le shell comme Claude Code lisent ces
     * touches pour ce qu'elles sont : un parcours de l'HISTORIQUE DES
     * COMMANDES. A la molette, le terminal rappelait donc les commandes
     * precedentes au lieu de defiler. Verifie dans la source d'@xterm/xterm 6 :
     * la traduction est gardee par `!buffer.hasScrollback`, sans option pour la
     * couper (`alternateScroll` / DECSET 1007 n'y existent pas).
     *
     * `attachCustomWheelEventHandler` est consulte EN PREMIER sur les deux
     * chemins molette de xterm — celui des touches de curseur, et celui de
     * l'evenement souris quand une application suit la souris. Retourner
     * `false` les coupe tous les deux, et le geste revient au meme scroller que
     * le glissement du doigt.
     *
     * `stopPropagation` est indispensable : xterm ne l'appelle PAS quand notre
     * handler rend `false` (aucun `cancel` sur ce chemin), et son element est
     * un ENFANT du conteneur. Sans lui, l'evenement remonterait jusqu'a
     * `onWheel` qui alimenterait le scroller une seconde fois — un cran de
     * molette ferait defiler deux fois trop vite.
     *
     * Maj rend la main a l'application : sans cette echappatoire, plus aucun
     * moyen de faire defiler sa propre interface.
     */
    terminal.attachCustomWheelEventHandler((e: WheelEvent) => {
      if (e.shiftKey) return true
      if (!scroller.wheel(pixelsDeMolette(e, terminal.rows))) return true
      e.preventDefault()
      e.stopPropagation()
      return false
    })
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

    // Glissé stérile : l'annoncer plutôt que de le laisser muet. Le `mouseup`
    // est guetté sur `window` et non sur la surface — un glissé de sélection
    // finit souvent hors du terminal, et l'écouteur de xterm (sur `document`)
    // passe alors avant le nôtre : `hasSelection` est déjà à jour quand on lit.
    const indiceSelection = createSelectionHintDetector()
    const surDebutGlisse = (ev: MouseEvent) => {
      if (ev.button !== 0) return
      indiceSelection.start(ev.clientX, ev.clientY, {
        shift: ev.shiftKey,
        suiviSouris: terminal.modes.mouseTrackingMode !== 'none',
      })
    }
    const surFinGlisse = (ev: MouseEvent) => {
      if (ev.button !== 0) return
      const manque = indiceSelection.end(ev.clientX, ev.clientY, {
        selectionActive: terminal.hasSelection(),
      })
      // `id` fixe : deux glissés rapprochés remplacent le toast au lieu de l'empiler.
      if (manque) {
        toast.info(tRef.current('admin.sshTerminal.selectionShiftHint'), {
          id: 'terminal-selection-shift',
        })
      }
    }
    termHost?.addEventListener('mousedown', surDebutGlisse)
    window.addEventListener('mouseup', surFinGlisse)
    let selLogs = 0

    let copyTimer: ReturnType<typeof setTimeout> | undefined
    let copyLogged = false
    const selectionDisposable = terminal.onSelectionChange(() => {
      const text = terminal.getSelection()
      if (selLogs < 10) {
        selLogs++
        console.warn(
          `terminal_diag: selection_change ${JSON.stringify({
            chars: text.length,
            active: terminal.hasSelection(),
          })}`,
        )
      }
      // La bande surlignee en travers de l'ecran est une selection de xterm qui
      // ne couvre que du vide. Son texte est '' et non une suite d'espaces :
      // `getSelection` traduit les lignes en les rognant a droite. Tester le
      // contenu ne pouvait donc rien attraper — mesure cote Loki : 29
      // `selection_change` d'affilee, tous a `chars: 0`, alors que la bande
      // etait bien visible.
      //
      // On interroge donc l'ETAT de la selection, pas son texte. `clearSelection`
      // relance l'evenement, mais `hasSelection` est alors faux : pas de boucle.
      if (!text) {
        if (terminal.hasSelection()) terminal.clearSelection()
        return
      }
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

    /**
     * Ajustement differe.
     *
     * L'ouverture du clavier mobile n'est pas un evenement unique : le viewport
     * retrecit par paliers pendant toute l'animation. Ajuster a chaque palier
     * envoyait une rafale de SIGWINCH a tmux, qui redessinait a chacun — d'ou
     * un affichage entrelace, deux lignes se marchant dessus. On attend que la
     * taille se stabilise avant de se recaler une seule fois.
     *
     * Le premier ajustement, lui, reste synchrone au montage : `ssh` fixe la
     * taille du PTY distant au demarrage et ne la relit jamais.
     */
    let ajustement: ReturnType<typeof setTimeout> | undefined
    const planifierAjustement = () => {
      clearTimeout(ajustement)
      ajustement = setTimeout(() => {
        // Le NUDGE, et non `terminal.refresh()` seul.
        //
        // `refresh()` redessine le tampon LOCAL de xterm. Si tmux y a ecrit une
        // trame entrelacee pendant que le clavier s'ouvrait, on la redessine a
        // l'identique : proprement, mais toujours fausse. Seul l'aller-retour
        // de taille fait repeindre tmux (cf. `refreshRef`), et c'est ce que le
        // bouton « rafraichir » faisait a la main pendant que le recalage
        // automatique, lui, ne le faisait jamais.
        //
        // Deux SIGWINCH par recalage : ce chemin RESTE donc derriere le
        // debounce, qui existe pour eviter exactement cette rafale.
        refreshRef.current?.()
      }, AJUSTEMENT_MS)
    }

    const onResize = planifierAjustement
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(planifierAjustement)
    if (termRef.current) ro.observe(termRef.current)
    // Clavier mobile. iOS ne fait varier NI `window.resize` NI la hauteur du
    // viewport de mise en page (cf. `useVisualViewportHeight`) : sans ces deux
    // ecouteurs, le recalage n'arrive qu'indirectement — etat React, puis
    // hauteur du conteneur, puis ResizeObserver — et PAS DU TOUT quand iOS
    // deplace le viewport visuel sans le redimensionner.
    const vueVisuelle = window.visualViewport
    vueVisuelle?.addEventListener('resize', planifierAjustement)
    vueVisuelle?.addEventListener('scroll', planifierAjustement)

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
      clearTimeout(ajustement)
      window.removeEventListener('resize', onResize)
      vueVisuelle?.removeEventListener('resize', planifierAjustement)
      vueVisuelle?.removeEventListener('scroll', planifierAjustement)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
      window.removeEventListener('pageshow', onVisible)
      termHost?.removeEventListener('mousedown', diagMouse)
      termHost?.removeEventListener('mouseup', diagMouse)
      termHost?.removeEventListener('mousedown', surDebutGlisse)
      window.removeEventListener('mouseup', surFinGlisse)
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
      refreshRef.current = null
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

  /**
   * La session peut-elle encore recevoir ? Sinon on le DIT.
   *
   * Avant, tout ce qui partait de la barre — touche, collage — etait jete en
   * silence quand la socket n'etait pas ouverte : le bouton ne faisait
   * simplement « rien », sans le moindre indice a l'ecran. Impossible de
   * distinguer un bouton casse d'une session perdue, et c'est exactement la
   * question qu'on s'est posee. On bascule donc sur l'overlay de reconnexion,
   * qui existe deja et porte son bouton.
   */
  const sessionVivante = (): boolean => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) return true
    console.warn(
      `terminal_diag: envoi_sur_socket_fermee ${JSON.stringify({
        readyState: ws?.readyState ?? null,
      })}`,
    )
    setDisconnected(true)
    return false
  }

  // Pas de `focus()` ici : sur mobile il ouvre le clavier a chaque appui sur la
  // barre, qui mange la moitie de l'ecran alors que ces boutons existent
  // justement pour eviter d'avoir a taper. La barre empeche deja le focus de
  // lui echapper (mousedown annule), donc le terminal garde celui qu'il avait.
  const sendToTerminal = (data: string) => {
    if (!sessionVivante()) return
    wsRef.current?.send(new TextEncoder().encode(data))
  }

  // Le collage passe par xterm et non par la WS : `paste()` normalise les sauts
  // de ligne (\r\n -> \r) et encadre le texte des marqueurs de « bracketed
  // paste » lorsque l'application distante a activé le mode 2004. Envoyé brut,
  // un code d'authentification arrivait abîmé dans le prompt de `claude`.
  const pasteToTerminal = (text: string) => {
    // Le collage traverse xterm, qui le ressort par `onData` vers la socket :
    // sur une socket fermee il disparaissait sans un mot, apres que l'utilisateur
    // ait pourtant valide l'invite « Coller » du systeme.
    if (!sessionVivante()) return
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
        onRefreshDisplay={() => refreshRef.current?.()}
        keyboardOpen={inputFocused}
        onToggleKeyboard={toggleKeyboard}
        onSearch={() => setSearchOpen(true)}
        onSend={sendToTerminal}
        onPaste={pasteToTerminal}
        getSelection={() =>
          terminalRef.current?.getSelection() || lastSelectionRef.current
        }
        // Terminal pas encore monté : `undefined !== 'none'` aurait annoncé une
        // capture souris qui n'existe pas, et le message aurait parlé de Maj à tort.
        souriCapturee={() => {
          const mode = terminalRef.current?.modes.mouseTrackingMode
          return mode !== undefined && mode !== 'none'
        }}
      />
    </div>
  )
}
