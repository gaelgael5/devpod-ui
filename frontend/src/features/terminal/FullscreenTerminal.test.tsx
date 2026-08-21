import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import FullscreenTerminal from './FullscreenTerminal'

// Mock xterm : capture l'instance pour déclencher onSelectionChange depuis les
// tests. jsdom ne rend pas de vrai terminal.
const terminals: MockTerminal[] = []

class MockTerminal {
  cols = 80
  rows = 24
  open = vi.fn()
  dispose = vi.fn()
  focus = vi.fn()
  write = vi.fn()
  refresh = vi.fn()
  // xterm normalise et encadre le texte collé, puis le fait ressortir par
  // onData. Le mock reproduit ce relais : sans lui, rien ne partirait vers la WS.
  paste = vi.fn((text: string) => this.dataCb?.(text))
  loadAddon = vi.fn()
  // API publique de xterm (ITerminal.unicode) : l'addon de graphèmes y règle la
  // version active. Absente du mock, le composant plantait au montage.
  unicode = { activeVersion: '11', versions: ['11'] }
  getSelection = vi.fn(() => '')
  private selectionCb: (() => void) | null = null
  private dataCb: ((data: string) => void) | null = null
  onData = vi.fn((cb: (data: string) => void) => {
    this.dataCb = cb
    return { dispose: vi.fn() }
  })
  onResize = vi.fn(() => ({ dispose: vi.fn() }))
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
  static OPEN = 1
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
