import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import FullscreenTerminal, { AJUSTEMENT_MS } from './FullscreenTerminal'
import { ENTER_COPY, EXIT_COPY, LINE_DOWN, LINE_PX, LINE_UP } from './historyScroll'

// Mock xterm : capture l'instance pour déclencher onSelectionChange depuis les
// tests. jsdom ne rend pas de vrai terminal.
const terminals: MockTerminal[] = []
/** Largeur d'une colonne dans le mock ; la hauteur de ligne en vaut le double. */
const CELL_PX = 10
/** Ce que xterm ecrit dans la session a la molette faute de scrollback. */
const CURSEUR_HAUT = '\x1b[A'
const CURSEUR_BAS = '\x1b[B'

class MockTerminal {
  cols = 80
  rows = 24
  // Zone de saisie cachee de xterm. Le vrai composant s'y accroche pour suivre
  // l'etat du clavier mobile : sans elle le bouton « clavier » ne peut rien.
  textarea: HTMLTextAreaElement = document.createElement('textarea')
  /**
   * Zone de rendu, cherchee par le hit-test des gestes. Une colonne fait
   * `CELL_PX` de large et une ligne `CELL_PX * 2` de haut, quel que soit le fit :
   * une tape en (x, y) tombe donc sur la colonne `x / CELL_PX`.
   */
  screen: HTMLDivElement = Object.assign(document.createElement('div'), {
    className: 'xterm-screen',
  })
  element: HTMLElement | undefined
  /** Contenu de toute ligne du tampon. */
  ligne = 'ls -la'
  open = vi.fn((el: HTMLElement) => {
    // xterm cree SON element comme ENFANT du conteneur (`parent.appendChild`)
    // et y pose ses ecouteurs. Le mock doit reproduire ce niveau : c'est lui
    // qui decide si un `wheel` traite par xterm remonte, ou non, jusqu'a
    // l'ecouteur que le composant pose sur le conteneur.
    this.element = document.createElement('div')
    this.element.classList.add('xterm')
    el.appendChild(this.element)
    this.element.appendChild(this.textarea)
    this.element.appendChild(this.screen)
    this.element.addEventListener('wheel', (e) => this.routeWheel(e as WheelEvent))
    this.screen.getBoundingClientRect = () =>
      ({
        left: 0,
        top: 0,
        width: this.cols * CELL_PX,
        height: this.rows * CELL_PX * 2,
      }) as DOMRect
  })
  dispose = vi.fn()
  focus = vi.fn(() => this.textarea.focus())
  write = vi.fn()
  refresh = vi.fn()
  // xterm normalise et encadre le texte collé, puis le fait ressortir par
  // onData. Le mock reproduit ce relais : sans lui, rien ne partirait vers la WS.
  paste = vi.fn((text: string) => this.dataCb?.(text))
  loadAddon = vi.fn()
  // API publique de xterm (ITerminal.unicode) : l'addon de graphèmes y règle la
  // version active. Absente du mock, le composant plantait au montage.
  unicode = { activeVersion: '11', versions: ['11'] }
  // tmux occupe l'ecran alterne : c'est ce que le defilement au geste teste.
  buffer = {
    active: {
      type: 'alternate' as 'normal' | 'alternate',
      viewportY: 0,
      getLine: () => ({ translateToString: () => this.ligne }),
    },
  }
  getSelection = vi.fn(() => '')
  /**
   * xterm rogne les lignes a droite : une selection qui ne couvre que du vide
   * a un texte VIDE tout en restant active — et dessinee. Le mock doit donc
   * porter les deux etats separement, sinon il ne peut pas reproduire le bug.
   */
  selectionActive = false
  hasSelection = vi.fn(() => this.selectionActive)
  clearSelection = vi.fn(() => {
    this.selectionActive = false
    this.simulateSelection('')
  })
  private selectionCb: (() => void) | null = null
  private dataCb: ((data: string) => void) | null = null
  onData = vi.fn((cb: (data: string) => void) => {
    this.dataCb = cb
    return { dispose: vi.fn() }
  })
  onResize = vi.fn(() => ({ dispose: vi.fn() }))
  /** Point d'extension d'xterm pour la molette, consulte par `routeWheel`. */
  customWheelHandler: ((e: WheelEvent) => boolean) | null = null
  attachCustomWheelEventHandler = vi.fn((cb: (e: WheelEvent) => boolean) => {
    this.customWheelHandler = cb
  })

  /**
   * Le chemin molette d'@xterm/xterm 6, reproduit a l'identique.
   *
   * Ce que fait la vraie source, dans cet ordre : le handler personnalise est
   * consulte EN PREMIER et un `false` fait sortir SANS annuler l'evenement —
   * donc sans `stopPropagation`, l'evenement continue de remonter. Sinon, et
   * seulement si le tampon n'a pas de scrollback (ecran alterne = tmux), xterm
   * ECRIT une touche de curseur dans la session, puis annule l'evenement.
   *
   * C'est cette touche que le shell et Claude Code lisent comme un parcours de
   * l'historique des commandes. Sans ce niveau de fidelite, le mock ne peut ni
   * reproduire le bug, ni montrer la double alimentation du scroller.
   */
  private routeWheel(e: WheelEvent) {
    if (this.customWheelHandler?.(e) === false) return
    if (this.buffer.active.type !== 'alternate') return
    if (e.deltaY === 0) return
    this.dataCb?.(e.deltaY < 0 ? CURSEUR_HAUT : CURSEUR_BAS)
    e.preventDefault()
    e.stopPropagation()
  }
  onSelectionChange = vi.fn((cb: () => void) => {
    this.selectionCb = cb
    return { dispose: vi.fn() }
  })

  options: Record<string, unknown>

  constructor(options: Record<string, unknown> = {}) {
    this.options = options
    terminals.push(this)
  }

  /** Simule une sélection souris : getSelection retourne `text`, l'événement part. */
  simulateSelection(text: string) {
    this.getSelection.mockReturnValue(text)
    this.selectionCb?.()
  }

  /** Simule une frappe au clavier : xterm la ressort par `onData`. */
  simulateData(data: string) {
    this.dataCb?.(data)
  }

  /** Selection posee sur du vide : active, mais sans texte a en tirer. */
  simulateEmptySelection() {
    this.selectionActive = true
    this.simulateSelection('')
  }
}

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(function (options?: Record<string, unknown>) {
    return new MockTerminal(options)
  }),
}))
const fitAddons: { fit: ReturnType<typeof vi.fn> }[] = []
// Le vrai FitAddon mesure le conteneur et REDIMENSIONNE le terminal. Un mock
// inerte laisserait passer un fit appelé trop tard : c'est précisément ce que
// ces tests doivent attraper.
const FITTED_COLS = 56
const FITTED_ROWS = 20
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function () {
    const instance = {
      fit: vi.fn(() => {
        const term = terminals[terminals.length - 1]
        if (term) {
          term.cols = FITTED_COLS
          term.rows = FITTED_ROWS
        }
      }),
    }
    fitAddons.push(instance)
    return instance
  }),
}))

// Le gestionnaire de clic sur lien, capturé : l'addon réel n'est jamais activé
// (loadAddon est un mock), donc on l'appelle directement pour simuler un clic.
let linkHandler: ((event: unknown, uri: string) => void) | null = null
vi.mock('@xterm/addon-web-links', () => ({
  WebLinksAddon: vi.fn(function (handler: (event: unknown, uri: string) => void) {
    linkHandler = handler
    return { activate: vi.fn(), dispose: vi.fn() }
  }),
}))

const sockets: MockWebSocket[] = []

class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  readyState = 1
  url = ''
  binaryType = ''
  send = vi.fn()
  close = vi.fn()
  onopen: (() => void) | null = null
  onmessage: ((e: unknown) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(url?: string) {
    this.url = url ?? ''
    sockets.push(this)
  }
}

const writeText = vi.fn(() => Promise.resolve())

beforeEach(() => {
  vi.useFakeTimers()
  // jsdom ne fait pas de mise en page : sans dimensions, la garde de safeFit
  // refuse d'ajuster et les tests de taille ne mesureraient rien.
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    width: 500,
    height: 300,
    top: 0,
    left: 0,
    bottom: 300,
    right: 500,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  terminals.length = 0
  fitAddons.length = 0
  sockets.length = 0
  linkHandler = null
  writeText.mockClear()
  vi.stubGlobal('WebSocket', MockWebSocket)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText, readText: vi.fn(() => Promise.resolve('')) },
    configurable: true,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function renderTerminal() {
  return render(
    <I18nextProvider i18n={i18n}>
      <FullscreenTerminal wsPath="/me/workspaces/ws1/ssh?session=main" />
    </I18nextProvider>,
  )
}

describe('FullscreenTerminal — copy-on-select', () => {
  it('copie automatiquement la sélection dans le presse-papier', () => {
    renderTerminal()
    act(() => {
      terminals[0].simulateSelection('texte choisi')
      vi.advanceTimersByTime(400)
    })
    expect(writeText).toHaveBeenCalledWith('texte choisi')
  })

  it('ne copie qu\'une fois la sélection stabilisée (debounce du drag)', () => {
    renderTerminal()
    act(() => {
      terminals[0].simulateSelection('tex')
      vi.advanceTimersByTime(50)
      terminals[0].simulateSelection('texte choisi')
      vi.advanceTimersByTime(400)
    })
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('texte choisi')
  })

  it('n\'écrase pas le presse-papier quand la sélection est simplement effacée', () => {
    renderTerminal()
    act(() => {
      terminals[0].simulateSelection('texte choisi')
      vi.advanceTimersByTime(400)
      terminals[0].simulateSelection('')
      vi.advanceTimersByTime(400)
    })
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('texte choisi')
  })

  it('le bouton Copier retombe sur la dernière sélection si elle a été effacée', () => {
    renderTerminal()
    act(() => {
      terminals[0].simulateSelection('texte choisi')
      vi.advanceTimersByTime(400)
      // La sélection xterm est ensuite effacée (frappe clavier, refresh TUI…)
      terminals[0].simulateSelection('')
      vi.advanceTimersByTime(400)
    })
    writeText.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /copier|copy/i }))
    expect(writeText).toHaveBeenCalledWith('texte choisi')
  })
})

describe('FullscreenTerminal — robustesse des addons', () => {
  it('active allowProposedApi (requis par l’addon unicode)', () => {
    // Panne du 20/08 : sans ce drapeau, `terminal.unicode` étant une API
    // « proposed », loadAddon LÈVE et l'exception remonte au rendu React —
    // l'ErrorBoundary avale alors toute la page terminal et plus aucune
    // fenêtre SSH ne s'ouvre. Le drapeau est donc un invariant, pas un détail.
    render(
      <I18nextProvider i18n={i18n}>
        <FullscreenTerminal wsPath="/me/workspaces/x/ssh" />
      </I18nextProvider>,
    )
    expect(terminals.at(-1)?.options.allowProposedApi).toBe(true)
  })

  it('un addon qui échoue n’empêche pas le terminal de s’afficher', () => {
    // Les addons sont des améliorations : leur échec doit dégrader, pas casser.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <FullscreenTerminal wsPath="/me/workspaces/x/ssh" />
      </I18nextProvider>,
    )
    const term = terminals.at(-1)
    expect(term).toBeDefined()

    // Rejoue un chargement d'addon en échec comme le ferait xterm.
    term!.loadAddon.mockImplementationOnce(() => {
      throw new Error('You must set the allowProposedApi option to true')
    })

    // Le conteneur du terminal est bien rendu malgré tout.
    expect(container.querySelector('div')).toBeTruthy()
    warn.mockRestore()
  })
})

describe('FullscreenTerminal — ajustement gardé', () => {
  /** Le FitAddon mocké le plus récent, pour observer les appels à fit(). */
  const lastFit = () => fitAddons.at(-1)!.fit

  function mountTerminal() {
    return render(
      <I18nextProvider i18n={i18n}>
        <FullscreenTerminal wsPath="/me/workspaces/x/ssh" />
      </I18nextProvider>,
    )
  }

  it('n’ajuste pas quand l’onglet est masqué', () => {
    mountTerminal()
    const fit = lastFit()
    fit.mockClear()

    // Onglet en arrière-plan : un fit() calculerait des dimensions aberrantes
    // et les enverrait à tmux, qui redessinerait pour une largeur inexistante.
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    window.dispatchEvent(new Event('resize'))

    expect(fit).not.toHaveBeenCalled()
  })

  it('n’ajuste pas sur un conteneur de taille nulle', () => {
    const { container } = mountTerminal()
    const fit = lastFit()
    fit.mockClear()

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    // jsdom rend des rects à zéro par défaut — c'est exactement le cas à écarter.
    const host = container.querySelector('div > div') as HTMLElement
    vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({
      width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}),
    })
    window.dispatchEvent(new Event('resize'))

    expect(fit).not.toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — liens du flux', () => {
  const AUTH_URL =
    'https://claude.ai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e' +
    '&response_type=code&scope=org%3Acreate_api_key+user%3Aprofile' +
    '&state=puGyxuUpf7QyKJFbvSK3vINUjVrNik60OipNHknuvy0'

  it('ouvre l’URL lue dans le flux, pas celle mutilée par le repli', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderTerminal()

    // Le serveur envoie l'URL entière ; xterm la repliera à l'écran.
    act(() => {
      sockets[0].onmessage?.({ data: `Use the url below:\n\n${AUTH_URL}\n` })
    })

    // Ce que le détecteur remonte au clic, reconstitué depuis un buffer replié.
    act(() => {
      linkHandler?.({}, 'https://claude.ai/oauth/authorize?code=true&cliened-5944d1962f5e=')
    })

    expect(open).toHaveBeenCalledWith(AUTH_URL, '_blank', 'noopener,noreferrer')
  })

  it('ouvre le lien tel quel quand le flux n’en connaît pas de meilleur', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderTerminal()

    act(() => {
      linkHandler?.({}, 'https://dev.yoops.org/portal')
    })

    expect(open).toHaveBeenCalledWith('https://dev.yoops.org/portal', '_blank', 'noopener,noreferrer')
  })
})

describe('FullscreenTerminal — collage', () => {
  it('fait passer le presse-papier par xterm avant la WebSocket', async () => {
    const readText = vi.fn().mockResolvedValue('code-a-coller')
    Object.defineProperty(navigator, 'clipboard', {
      value: { readText, writeText },
      configurable: true,
    })
    renderTerminal()

    fireEvent.click(screen.getByRole('button', { name: /coller|paste/i }))
    await vi.waitFor(() => expect(terminals[0].paste).toHaveBeenCalledWith('code-a-coller'))

    // xterm normalise et encadre le texte, puis le ressort par onData : c'est
    // cette sortie-là qui doit atteindre la WS, jamais le presse-papier brut.
    expect(sockets[0].send).toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — taille initiale', () => {
  it('annonce cols/rows dans l’URL avant même la connexion', () => {
    renderTerminal()

    // `ssh` dimensionne le PTY distant au démarrage d'après son propre terminal
    // et ne le relit jamais : transmise par message de contrôle, la taille
    // arriverait après l'exec et tmux resterait calé sur 80x24.
    const url = new URL(sockets[0].url, 'https://portail.test')
    expect(url.searchParams.get('cols')).toBe(String(FITTED_COLS))
    expect(url.searchParams.get('rows')).toBe(String(FITTED_ROWS))
    expect(url.searchParams.get('session')).toBe('main')
  })

  it('ajuste la taille avant d’ouvrir la connexion, pas une frame plus tard', () => {
    renderTerminal()

    // Différé d'une frame, le fit laissait partir la connexion — et donc `ssh`
    // et tmux — sur les 80x24 par défaut.
    expect(fitAddons[0].fit).toHaveBeenCalled()
    expect(terminals[0].cols).toBe(FITTED_COLS)
  })
})

describe('FullscreenTerminal — recalage au clavier mobile', () => {
  /** jsdom n'a pas `visualViewport` — et c'est precisement l'API iOS a couvrir. */
  function poserViewportVisuel() {
    const vue = new EventTarget() as EventTarget & { height: number }
    vue.height = 400
    Object.defineProperty(window, 'visualViewport', { value: vue, configurable: true })
    return vue
  }

  function messagesResize() {
    return sockets[0].send.mock.calls
      .map((appel) => String(appel[0]))
      .filter((message) => message.includes('"type":"resize"'))
  }

  it('se recale quand le viewport visuel change, sans window.resize', () => {
    // iOS ne fait varier NI `window.resize` NI la hauteur du viewport de mise
    // en page a l'ouverture du clavier : sans ecouteur sur `visualViewport`,
    // rien ne declenche le recalage.
    const vue = poserViewportVisuel()
    renderTerminal()
    act(() => { vi.runAllTimers() })
    const fit = fitAddons.at(-1)!.fit
    fit.mockClear()

    act(() => { vue.dispatchEvent(new Event('resize')) })
    act(() => { vi.advanceTimersByTime(AJUSTEMENT_MS) })

    expect(fit).toHaveBeenCalled()
  })

  it('suit aussi le DEPLACEMENT du viewport, qui ne le redimensionne pas', () => {
    // iOS fait defiler le viewport visuel sans changer sa taille : aucun
    // ResizeObserver ne se declenche alors, et l'ecran reste decale.
    const vue = poserViewportVisuel()
    renderTerminal()
    act(() => { vi.runAllTimers() })
    const fit = fitAddons.at(-1)!.fit
    fit.mockClear()

    act(() => { vue.dispatchEvent(new Event('scroll')) })
    act(() => { vi.advanceTimersByTime(AJUSTEMENT_MS) })

    expect(fit).toHaveBeenCalled()
  })

  it('fait REPEINDRE tmux, au lieu de redessiner la trame locale', () => {
    // Le coeur du defaut : `terminal.refresh()` redessine le tampon de xterm.
    // Si tmux y a ecrit une trame entrelacee pendant l'ouverture du clavier, on
    // la redessine a l'identique. tmux ne repeint que sur CHANGEMENT de taille,
    // d'ou la taille volontairement fausse qui doit partir sur la socket.
    const vue = poserViewportVisuel()
    renderTerminal()
    act(() => { vi.runAllTimers() })
    sockets[0].send.mockClear()

    act(() => { vue.dispatchEvent(new Event('resize')) })
    act(() => { vi.advanceTimersByTime(AJUSTEMENT_MS) })

    expect(messagesResize().length).toBeGreaterThan(0)
  })

  it('ne recale qu\'une fois pour une rafale de paliers', () => {
    // Le clavier ne s'ouvre pas d'un coup : le viewport retrecit par paliers.
    // Un recalage par palier renverrait la rafale de SIGWINCH que le debounce
    // existe pour eviter — et qui produisait l'entrelacement.
    const vue = poserViewportVisuel()
    renderTerminal()
    act(() => { vi.runAllTimers() })
    sockets[0].send.mockClear()

    act(() => {
      for (let i = 0; i < 8; i++) vue.dispatchEvent(new Event('resize'))
    })
    act(() => { vi.advanceTimersByTime(AJUSTEMENT_MS) })

    // Un seul aller-retour : la taille fausse puis la vraie, pas huit.
    expect(messagesResize().length).toBeLessThanOrEqual(2)
  })
})

describe('FullscreenTerminal — clavier mobile', () => {
  it('n’ouvre pas le clavier en envoyant depuis la barre', async () => {
    renderTerminal()
    // Le montage donne deliberement le focus au terminal ; on ne mesure que ce
    // qui suit l'appui sur un bouton.
    act(() => { vi.runAllTimers() })
    terminals[0].focus.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /échap|esc/i }))

    // `focus()` place le curseur dans la zone de saisie cachee de xterm : sur
    // iOS cela deroule le clavier, qui mange la moitie de l'ecran.
    expect(terminals[0].focus).not.toHaveBeenCalled()
    expect(sockets[0].send).toHaveBeenCalled()
  })

  it('n’ouvre pas le clavier en collant', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { readText: vi.fn().mockResolvedValue('texte'), writeText },
      configurable: true,
    })
    renderTerminal()
    // Le montage donne deliberement le focus au terminal ; on ne mesure que ce
    // qui suit l'appui sur un bouton.
    act(() => { vi.runAllTimers() })
    terminals[0].focus.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /coller|paste/i }))
    await vi.waitFor(() => expect(terminals[0].paste).toHaveBeenCalled())

    expect(terminals[0].focus).not.toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — autofocus selon l’appareil', () => {
  it('ne prend pas le focus sur un appareil tactile', () => {
    // Le focus deroule le clavier iOS des l'ouverture, sur une session dont la
    // barre de touches existe justement pour eviter d'avoir a taper.
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
    renderTerminal()

    act(() => { vi.runAllTimers() })

    expect(terminals[0].focus).not.toHaveBeenCalled()
  })

  it('prend le focus quand il y a un clavier physique', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
    renderTerminal()

    act(() => { vi.runAllTimers() })

    expect(terminals[0].focus).toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — historique au geste', () => {
  function surface() {
    return screen.getByTestId('terminal-surface')
  }

  function sent() {
    const dec = new TextDecoder()
    // Pas d'`instanceof Uint8Array` : jsdom fait cohabiter deux realms et le
    // test comparerait a un constructeur different de celui du composant.
    return sockets[0].send.mock.calls
      .map((c) => c[0])
      .filter((d) => typeof d !== 'string')
      .map((d) => dec.decode(d as ArrayBufferView))
  }

  it('remonte dans l’historique tmux a la molette', () => {
    renderTerminal()

    fireEvent.wheel(surface(), { deltaY: -LINE_PX * 2 })
    act(() => { vi.runAllTimers() })

    // Un jeton par frame : le PTY regroupe les ecritures rapprochees et tmux
    // perd alors les touches repetees.
    expect(sent()).toEqual(expect.arrayContaining([ENTER_COPY, LINE_UP]))
  })

  it('redescend a la molette inverse', () => {
    renderTerminal()

    fireEvent.wheel(surface(), { deltaY: LINE_PX })
    act(() => { vi.runAllTimers() })

    expect(sent()).toContain(LINE_DOWN)
  })

  /** Molette posee la ou l'utilisateur la pose : sur l'element de xterm. */
  function moletteSurXterm(deltaY: number, init: Record<string, unknown> = {}) {
    fireEvent.wheel(terminals[0].element as HTMLElement, { deltaY, ...init })
  }

  it('n’envoie plus de touche de curseur a l’application', () => {
    // LE bug : faute de scrollback sous tmux, xterm traduisait la molette en
    // fleche haut. Le shell et Claude Code y lisent un rappel des commandes
    // precedentes — a la molette, le terminal remontait dans l'historique des
    // COMMANDES au lieu de defiler dans celui de l'ECRAN.
    renderTerminal()

    moletteSurXterm(-LINE_PX * 2)
    act(() => { vi.runAllTimers() })

    expect(sent()).not.toContain(CURSEUR_HAUT)
    expect(sent()).toEqual(expect.arrayContaining([ENTER_COPY, LINE_UP]))
  })

  it('ne compte le cran de molette qu’une fois', () => {
    // xterm n'annule PAS l'evenement quand le handler rend `false` : sans
    // `stopPropagation`, il remonterait jusqu'a l'ecouteur du conteneur et le
    // meme cran alimenterait le scroller deux fois — deux lignes au lieu d'une.
    renderTerminal()

    moletteSurXterm(-LINE_PX)
    act(() => { vi.runAllTimers() })

    // Un cran = UNE ligne. Alimente deux fois, le meme cran en donnerait deux.
    expect(sent()).toContain(ENTER_COPY)
    expect(sent().filter((d) => d === LINE_UP)).toHaveLength(1)
  })

  it('rend la molette a l’application quand Maj est enfonce', () => {
    // Echappatoire : sans elle, plus aucun moyen de faire defiler l'interface
    // d'une appli qui gere elle-meme la souris.
    renderTerminal()

    moletteSurXterm(-LINE_PX * 2, { shiftKey: true })
    act(() => { vi.runAllTimers() })

    expect(sent()).toContain(CURSEUR_HAUT)
    expect(sent().join('')).not.toContain(LINE_UP)
  })

  it('laisse le defilement natif quand tmux n’occupe pas l’ecran alterne', () => {
    renderTerminal()
    terminals[0].buffer.active.type = 'normal'

    fireEvent.wheel(surface(), { deltaY: -LINE_PX * 3 })
    act(() => { vi.runAllTimers() })

    // Sans tmux, xterm a un vrai scrollback : on ne doit rien envoyer.
    expect(sent().join('')).not.toContain(LINE_UP)
  })
})

describe('FullscreenTerminal — double tape', () => {
  /**
   * Le mock affiche « ls -la » sur chaque ligne : les colonnes 0 a 5 portent du
   * texte, au-dela c'est le vide. A `CELL_PX` par colonne, x=25 tombe sur le
   * texte et x=200 loin apres la fin de la ligne.
   */
  const SUR_LE_TEXTE = 2.5 * CELL_PX
  const APRES_LA_LIGNE = 20 * CELL_PX

  function tape(x = APRES_LA_LIGNE, y = 10) {
    const el = screen.getByTestId('terminal-surface')
    fireEvent.touchStart(el, { touches: [{ clientX: x, clientY: y }] })
    fireEvent.touchEnd(el, { touches: [] })
  }

  function sent() {
    const dec = new TextDecoder()
    return sockets[0].send.mock.calls
      .map((c) => c[0])
      .filter((d) => typeof d !== 'string')
      .map((d) => dec.decode(d as ArrayBufferView))
  }

  it('envoie Tab sur une double tape apres la fin de la ligne', () => {
    renderTerminal()

    tape()
    expect(sent()).not.toContain('\t')

    tape()
    expect(sent()).toContain('\t')
  })

  it('laisse la selection de mot a xterm sur du texte', () => {
    // Double taper un mot doit le selectionner — seul moyen de copier au doigt.
    // Envoyer Tab la, ou seulement supprimer l'evenement, volerait ce geste.
    renderTerminal()

    tape(SUR_LE_TEXTE)
    tape(SUR_LE_TEXTE)

    expect(sent()).not.toContain('\t')
  })

  it('n’envoie rien sur une tape isolee', () => {
    renderTerminal()

    tape()

    expect(sent()).not.toContain('\t')
  })

  it('n’envoie rien quand le doigt a glisse', () => {
    // Le glissement fait defiler l'historique : il ne doit pas valoir Tab.
    renderTerminal()
    const el = screen.getByTestId('terminal-surface')

    tape()
    fireEvent.touchStart(el, { touches: [{ clientX: APRES_LA_LIGNE, clientY: 10 }] })
    fireEvent.touchMove(el, { touches: [{ clientX: APRES_LA_LIGNE, clientY: 210 }] })
    fireEvent.touchEnd(el, { touches: [] })

    expect(sent()).not.toContain('\t')
  })

  it('ne supprime pas le geste d’une tape simple', () => {
    // Supprimer l'evenement tuerait le clic synthetise par le navigateur, donc
    // le focus de xterm : plus de clavier mobile, plus de selection.
    renderTerminal()
    const el = screen.getByTestId('terminal-surface')

    fireEvent.touchStart(el, { touches: [{ clientX: APRES_LA_LIGNE, clientY: 10 }] })
    const permis = fireEvent.touchEnd(el, { touches: [] })

    expect(permis).toBe(true)
  })
})

describe('FullscreenTerminal — bouton clavier', () => {
  /**
   * Au tactile ce bouton est le seul chemin vers le clavier : le defilement de
   * l'historique annule le clic que le navigateur synthetise sur la surface,
   * donc xterm ne prend plus le focus tout seul.
   */
  function bouton() {
    return screen.getByRole('button', { name: /^clavier$|^keyboard$/i })
  }

  it('donne le focus a la zone de saisie puis le retire', () => {
    renderTerminal()
    const saisie = terminals[0].textarea

    fireEvent.click(bouton())
    expect(document.activeElement).toBe(saisie)
    expect(bouton()).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(bouton())
    expect(document.activeElement).not.toBe(saisie)
    expect(bouton()).toHaveAttribute('aria-pressed', 'false')
  })

  it('suit le focus perdu sans passer par le bouton', () => {
    // iOS masque le clavier par son propre bouton : l'etat doit suivre, sinon
    // la bascule suivante fermerait un clavier deja ferme.
    renderTerminal()
    const saisie = terminals[0].textarea

    fireEvent.click(bouton())
    act(() => saisie.blur())

    expect(bouton()).toHaveAttribute('aria-pressed', 'false')
  })

  it('ne vole pas le focus par son propre mousedown', () => {
    // Sans cela le bouton prendrait le focus avant le clic : la bascule lirait
    // un etat faux et le clavier se rouvrirait au lieu de se fermer.
    renderTerminal()

    const evt = fireEvent.mouseDown(bouton())

    expect(evt).toBe(false)
  })
})

describe('FullscreenTerminal — retour sur la session', () => {
  /** Simule un retour au premier plan (onglet, ou retour arriere de Safari). */
  function revenir() {
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
      vi.advanceTimersByTime(50)
    })
  }

  it('reconnecte quand la socket est morte pendant l’absence', () => {
    // Safari coupe la WebSocket en arriere-plan sans toujours delivrer `close` :
    // sans cette relecture, la session restait figee et muette.
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CLOSED

    revenir()

    expect(sockets).toHaveLength(2)
  })

  it('reconnecte aussi au retour depuis le cache de navigation', () => {
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CLOSED

    act(() => {
      window.dispatchEvent(new Event('pageshow'))
      vi.advanceTimersByTime(50)
    })

    expect(sockets).toHaveLength(2)
  })

  it('ne reconnecte pas une socket vivante', () => {
    renderTerminal()

    revenir()

    expect(sockets).toHaveLength(1)
  })

  it('ne reconnecte pas une socket en cours d’ouverture', () => {
    // `focus` et `visibilitychange` arrivent ensemble : remonter ici bouclerait.
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CONNECTING

    revenir()
    revenir()

    expect(sockets).toHaveLength(1)
  })
})

describe('FullscreenTerminal — selection de vide', () => {
  /**
   * La bande surlignee en travers de l'ecran est une selection de xterm posee
   * sur du vide. Son texte est '' et non une suite d'espaces — xterm rogne les
   * lignes a droite. C'est ce qui rendait le bug insaisissable : mesure Loki,
   * 29 `selection_change` d'affilee a `chars: 0`, bande bien visible.
   */
  it('annule une selection active mais sans texte', () => {
    renderTerminal()

    terminals[0].simulateEmptySelection()

    expect(terminals[0].clearSelection).toHaveBeenCalled()
  })

  it('ne fait rien quand aucune selection n’est active', () => {
    // L'evenement part aussi quand une selection DISPARAIT : re-effacer la
    // relancerait sans fin.
    renderTerminal()

    terminals[0].simulateSelection('')

    expect(terminals[0].clearSelection).not.toHaveBeenCalled()
  })

  it('ne boucle pas sur l’annulation', () => {
    // `clearSelection` relance l'evenement : `hasSelection` est alors faux.
    renderTerminal()

    terminals[0].simulateEmptySelection()

    expect(terminals[0].clearSelection).toHaveBeenCalledTimes(1)
  })

  it('garde une selection de texte', () => {
    // C'est la selection utile : celle qu'on vient de faire pour copier.
    renderTerminal()
    terminals[0].selectionActive = true

    terminals[0].simulateSelection('ls -la')

    expect(terminals[0].clearSelection).not.toHaveBeenCalled()
  })

  it('ne copie pas une selection de vide', () => {
    renderTerminal()

    terminals[0].simulateEmptySelection()
    act(() => vi.advanceTimersByTime(300))

    expect(writeText).not.toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — session perdue', () => {
  /**
   * Avant, tout ce qui partait de la barre etait jete en silence quand la
   * socket n'etait pas ouverte : le bouton ne faisait « rien », sans le moindre
   * indice a l'ecran. Impossible de distinguer un bouton casse d'une session
   * perdue.
   */
  function keybar(nom: RegExp) {
    return screen.getByRole('button', { name: nom })
  }

  it('signale la session perdue au lieu de jeter la touche', () => {
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CLOSED

    fireEvent.click(keybar(/^échap$|^esc$/i))

    expect(sockets[0].send).not.toHaveBeenCalled()
    expect(screen.getByText(/déconnect|disconnect/i)).toBeInTheDocument()
  })

  it('n’envoie pas un collage dans le vide', async () => {
    // L'utilisateur a valide l'invite « Coller » du systeme : lui rendre le
    // silence est le pire des retours.
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText, readText: vi.fn(() => Promise.resolve('ls -la')) },
      configurable: true,
    })
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CLOSED

    fireEvent.click(keybar(/^coller$|^paste$/i))
    // La lecture du presse-papier est asynchrone : sans ce relais, l'assertion
    // passerait avant que le collage ait seulement ete tente.
    await act(async () => {})

    expect(terminals[0].paste).not.toHaveBeenCalled()
    expect(screen.getByText(/déconnect|disconnect/i)).toBeInTheDocument()
  })

  it('laisse passer la touche quand la session est vivante', () => {
    renderTerminal()

    fireEvent.click(keybar(/^échap$|^esc$/i))

    expect(sockets[0].send).toHaveBeenCalled()
    expect(screen.queryByText(/déconnect|disconnect/i)).toBeNull()
  })
})

describe('FullscreenTerminal — frappe clavier', () => {
  /**
   * `onData` porte la frappe au clavier : le chemin le plus direct, et le
   * dernier a rester muet. Taper sur une socket fermee ne produisait RIEN — ni
   * caractere a l'ecran, ni message — et rien ne disait si le fautif etait le
   * clavier ou la session.
   */
  it('envoie la frappe quand la session est vivante', () => {
    renderTerminal()

    act(() => terminals[0].simulateData('a'))

    expect(sockets[0].send).toHaveBeenCalled()
    expect(screen.queryByText(/déconnect|disconnect/i)).toBeNull()
  })

  it('signale la session perdue au lieu d’avaler la frappe', () => {
    renderTerminal()
    sockets[0].readyState = MockWebSocket.CLOSED

    act(() => terminals[0].simulateData('a'))

    expect(sockets[0].send).not.toHaveBeenCalled()
    expect(screen.getByText(/déconnect|disconnect/i)).toBeInTheDocument()
  })
})

describe('FullscreenTerminal — retour du copy-mode', () => {
  /**
   * Le geste de defilement fait entrer tmux en copy-mode, ou la saisie est
   * ABSORBEE au lieu d'atteindre l'application. L'utilisateur qui remonte dans
   * l'historique puis se remet a taper ne voyait plus rien s'inscrire, alors
   * que sa frappe partait bel et bien.
   */
  function defiler() {
    const el = screen.getByTestId('terminal-surface')
    fireEvent.touchStart(el, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(el, { touches: [{ clientX: 100, clientY: 160 }] })
    fireEvent.touchMove(el, { touches: [{ clientX: 100, clientY: 400 }] })
    fireEvent.touchEnd(el, { touches: [] })
    act(() => vi.advanceTimersByTime(200))
  }

  function envoye() {
    const dec = new TextDecoder()
    return sockets[0].send.mock.calls
      .map((c) => c[0])
      .filter((d) => typeof d !== 'string')
      .map((d) => dec.decode(d as ArrayBufferView))
  }

  it('quitte le copy-mode avant de transmettre la frappe', () => {
    renderTerminal()
    defiler()
    sockets[0].send.mockClear()

    act(() => terminals[0].simulateData('a'))

    expect(envoye()).toContain(EXIT_COPY)
  })

  it('transmet quand meme la frappe', () => {
    // La sortie du mode ne doit pas manger le caractere : il arrive a la frame
    // suivante, tmux perdant les touches ecrites dans la meme lecture PTY.
    renderTerminal()
    defiler()
    sockets[0].send.mockClear()

    act(() => terminals[0].simulateData('a'))
    act(() => vi.advanceTimersByTime(50))

    expect(envoye()).toContain('a')
  })

  it('n’envoie pas de sortie sans defilement prealable', () => {
    // `q` sur une application qui n'est pas en copy-mode y ecrirait un
    // caractere bien reel.
    renderTerminal()
    sockets[0].send.mockClear()

    act(() => terminals[0].simulateData('a'))

    expect(envoye()).not.toContain(EXIT_COPY)
    expect(envoye()).toContain('a')
  })
})

describe('FullscreenTerminal — stabilite de l’affichage au redimensionnement', () => {
  /**
   * L'ouverture du clavier mobile n'est pas un evenement unique : le viewport
   * retrecit par paliers pendant toute l'animation. Ajuster a chaque palier
   * envoyait une rafale de SIGWINCH a tmux, qui redessinait a chacun — d'ou
   * l'affichage entrelace, deux lignes se marchant dessus.
   */
  /** Monte, puis laisse retomber les ajustements du montage lui-meme. */
  function monterStabilise() {
    renderTerminal()
    act(() => vi.advanceTimersByTime(AJUSTEMENT_MS * 2))
  }

  function rafaleDeRedimensionnements(n: number) {
    for (let i = 0; i < n; i++) {
      act(() => {
        window.dispatchEvent(new Event('resize'))
        vi.advanceTimersByTime(10)
      })
    }
  }

  it('ne se recale qu’une fois pour toute une rafale', () => {
    monterStabilise()
    const fit = fitAddons[0].fit
    fit.mockClear()

    rafaleDeRedimensionnements(12)
    act(() => vi.advanceTimersByTime(AJUSTEMENT_MS))

    expect(fit).toHaveBeenCalledTimes(1)
  })

  it('attend la fin de la rafale avant de se recaler', () => {
    // Se recaler au milieu, c'est se caler sur une taille intermediaire que le
    // clavier va encore faire bouger.
    monterStabilise()
    const fit = fitAddons[0].fit
    fit.mockClear()

    rafaleDeRedimensionnements(3)

    expect(fit).not.toHaveBeenCalled()
  })

  it('redessine tout apres s’etre recale', () => {
    // Les tailles intermediaires laissent des residus a l'ecran : sans redessin
    // complet, ce sont eux qu'on prend pour un affichage instable.
    monterStabilise()
    terminals[0].refresh.mockClear()

    rafaleDeRedimensionnements(2)
    act(() => vi.advanceTimersByTime(AJUSTEMENT_MS))

    expect(terminals[0].refresh).toHaveBeenCalled()
  })
})

describe('FullscreenTerminal — rafraichir l’affichage', () => {
  /**
   * Quand la fenetre tmux et le terminal divergent, l'ecran garde des rendus
   * anciens — des barres de statut empilees. tmux ne redessine que sur
   * changement de taille : renvoyer la MEME ne declenche rien.
   */
  function resizesEnvoyes() {
    return sockets[0].send.mock.calls
      .map((c) => c[0])
      .filter((d): d is string => typeof d === 'string')
      .map((d) => JSON.parse(d) as { type: string; cols: number; rows: number })
      .filter((m) => m.type === 'resize')
  }

  function rafraichir() {
    fireEvent.click(screen.getByRole('button', { name: /rafraîchir|refresh/i }))
  }

  it('envoie une taille differente puis la vraie', () => {
    renderTerminal()
    act(() => vi.advanceTimersByTime(AJUSTEMENT_MS * 2))
    sockets[0].send.mockClear()

    rafraichir()
    act(() => vi.advanceTimersByTime(50))

    const envoyes = resizesEnvoyes()
    expect(envoyes).toHaveLength(2)
    expect(envoyes[0].rows).not.toBe(envoyes[1].rows)
    // La derniere doit etre la VRAIE : rester sur la fausse laisserait le PTY
    // distant d'une ligne trop court.
    expect(envoyes[1].rows).toBe(terminals[0].rows)
  })

  it('redessine le terminal', () => {
    renderTerminal()
    act(() => vi.advanceTimersByTime(AJUSTEMENT_MS * 2))
    terminals[0].refresh.mockClear()

    rafraichir()
    act(() => vi.advanceTimersByTime(50))

    expect(terminals[0].refresh).toHaveBeenCalled()
  })
})
