import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, it, expect, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import i18n from '@/i18n'
import TerminalPage from './TerminalPage'

// Stub du terminal : évite xterm/WebSocket et expose wsPath + resize.
vi.mock('./FullscreenTerminal', () => ({
  default: ({ wsPath, resize }: { wsPath: string; resize: boolean }) => (
    <div data-testid="term" data-ws={wsPath} data-resize={String(resize)} />
  ),
}))

function renderAt(path: string) {
  const router = createMemoryRouter(
    [{ path: '/terminal', element: <I18nextProvider i18n={i18n}><TerminalPage /></I18nextProvider> }],
    { initialEntries: [path] },
  )
  return render(<RouterProvider router={router} />)
}

describe('TerminalPage', () => {
  it('rend le terminal host (resize activé — tmux derrière un PTY)', () => {
    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh&title=h1')
    const term = screen.getByTestId('term')
    expect(term).toHaveAttribute('data-ws', '/admin/hosts/h1/ssh')
    expect(term).toHaveAttribute('data-resize', 'true')
  })

  it('rend le terminal workspace (resize activé)', () => {
    renderAt('/terminal?ws=%2Fme%2Fworkspaces%2Fws1%2Fssh%3Fsession%3Dmain')
    const term = screen.getByTestId('term')
    expect(term).toHaveAttribute('data-ws', '/me/workspaces/ws1/ssh?session=main')
    expect(term).toHaveAttribute('data-resize', 'true')
  })

  it('rejette une cible non autorisée (hors /me et /admin)', () => {
    renderAt('/terminal?ws=%2F%2Fevil.com%2Fssh')
    expect(screen.queryByTestId('term')).not.toBeInTheDocument()
    expect(screen.getByText(/invalide|invalid/i)).toBeInTheDocument()
  })

  it('rejette un ws absent', () => {
    renderAt('/terminal')
    expect(screen.queryByTestId('term')).not.toBeInTheDocument()
    expect(screen.getByText(/invalide|invalid/i)).toBeInTheDocument()
  })
})

describe('TerminalPage — clavier mobile', () => {
  /**
   * Le clavier iOS se pose PAR-DESSUS la page sans la redimensionner : `100vh`
   * ne bouge pas, et tout le bas du terminal — prompt, ligne de statut tmux,
   * barre de touches — passe dessous. Seul `visualViewport` le voit.
   */
  function poserVisualViewport(hauteur: number) {
    const cbs = new Set<() => void>()
    const vue = {
      height: hauteur,
      pageTop: 0,
      addEventListener: (_t: string, cb: () => void) => cbs.add(cb),
      removeEventListener: (_t: string, cb: () => void) => cbs.delete(cb),
    }
    vi.stubGlobal('visualViewport', vue)
    return {
      retrecir(nouvelle: number) {
        vue.height = nouvelle
        cbs.forEach((cb) => cb())
      },
      panner(haut: number) {
        vue.pageTop = haut
        cbs.forEach((cb) => cb())
      },
    }
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('borne la page a la hauteur visible', () => {
    poserVisualViewport(800)

    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh')

    expect(screen.getByTestId('terminal-page')).toHaveStyle({ height: '800px' })
  })

  it('retrecit quand le clavier s’ouvre', () => {
    const vue = poserVisualViewport(800)
    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh')

    act(() => vue.retrecir(420))

    expect(screen.getByTestId('terminal-page')).toHaveStyle({ height: '420px' })
  })

  it('suit la zone visible quand Safari panne le viewport (clavier iOS)', () => {
    // iOS deplace la fenetre visible pour reveler la saisie : sans
    // compensation, le conteneur — ancre en haut du document — se retrouve
    // decale, bande vide a l'ecran. On le translate d'autant.
    const vue = poserVisualViewport(800)
    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh')

    act(() => {
      vue.retrecir(420)
      vue.panner(60)
    })

    const page = screen.getByTestId('terminal-page')
    expect(page).toHaveStyle({ height: '420px' })
    expect(page).toHaveStyle({ transform: 'translateY(60px)' })
  })

  it('garde 100vh sans l’API', () => {
    // Navigateur sans `visualViewport` : on ne remplace pas le dimensionnement
    // d'origine par une hauteur inventee.
    vi.stubGlobal('visualViewport', undefined)

    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh')

    expect(screen.getByTestId('terminal-page')).toHaveStyle({ height: '100vh' })
  })
})
