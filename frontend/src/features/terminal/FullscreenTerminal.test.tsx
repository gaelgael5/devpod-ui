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
  loadAddon = vi.fn()
  // API publique de xterm (ITerminal.unicode) : l'addon de graphèmes y règle la
  // version active. Absente du mock, le composant plantait au montage.
  unicode = { activeVersion: '11', versions: ['11'] }
  getSelection = vi.fn(() => '')
  private selectionCb: (() => void) | null = null
  onData = vi.fn(() => ({ dispose: vi.fn() }))
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
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function () {
    return { fit: vi.fn() }
  }),
}))

class MockWebSocket {
  static OPEN = 1
  readyState = 1
  binaryType = ''
  send = vi.fn()
  close = vi.fn()
  onopen: (() => void) | null = null
  onmessage: ((e: unknown) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
}

const writeText = vi.fn(() => Promise.resolve())

beforeEach(() => {
  vi.useFakeTimers()
  terminals.length = 0
  writeText.mockClear()
  vi.stubGlobal('WebSocket', MockWebSocket)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText, readText: vi.fn(() => Promise.resolve('')) },
    configurable: true,
  })
})

afterEach(() => {
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
