import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, it, expect, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { render } from '@testing-library/react'
import i18n from '@/i18n'
import { server } from '@/test/server'
import WorkspaceTerminals from './WorkspaceTerminals'

// Stub du terminal : évite xterm/WebSocket (absents de jsdom) et expose la
// session effectivement sélectionnée.
vi.mock('./WorkspaceSessionTerminal', () => ({
  default: ({ session }: { session: string }) => <div data-testid="term">{session}</div>,
}))

function renderPage(path = '/workspaces/myapp/terminals') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter(
    [{ path: '/workspaces/:wsName/terminals', element: <I18nextProvider i18n={i18n}><WorkspaceTerminals /></I18nextProvider> }],
    { initialEntries: [path] }
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('bug 044 : validation client du nom de session', () => {
  it('rejette un nom de session invalide et n\'appelle pas le backend', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    let createCalled = false
    server.use(
      http.post('/me/workspaces/:name/sessions', () => {
        createCalled = true
        return HttpResponse.json({ name: 's1' }, { status: 201 })
      })
    )
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getAllByText(/aucune session|no active session/i).length).toBeGreaterThan(0))
    await user.click(screen.getByRole('button', { name: /créer une session|create a session/i }))

    const input = await screen.findByLabelText(/^nom$|^name$/i)
    await user.clear(input)
    await user.type(input, 'a/b c#')
    await user.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(createCalled).toBe(false)
  })

  it('accepte un nom de session valide et appelle le backend', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    let createdName = ''
    server.use(
      http.post('/me/workspaces/:name/sessions', async ({ request }) => {
        const body = (await request.json()) as { name: string }
        createdName = body.name
        return HttpResponse.json({ name: body.name }, { status: 201 })
      })
    )
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getAllByText(/aucune session|no active session/i).length).toBeGreaterThan(0))
    await user.click(screen.getByRole('button', { name: /créer une session|create a session/i }))

    const input = await screen.findByLabelText(/^nom$|^name$/i)
    await user.clear(input)
    await user.type(input, 'myapp1')
    await user.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(createdName).toBe('myapp1'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('bug : ?session ne doit pas retomber sur la première session', () => {
  it('honore ?session=devpod2 même pendant le chargement de la liste', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () =>
        HttpResponse.json(['devpod1', 'devpod2']),
      ),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    renderPage('/workspaces/myapp/terminals?session=devpod2')

    // La session ciblée par l'URL est sélectionnée d'emblée…
    expect(await screen.findByTestId('term')).toHaveTextContent('devpod2')
    // …et le reste après résolution de la liste (pas de repli sur devpod1).
    await waitFor(() => expect(document.title).toContain('devpod2'))
    expect(screen.getByTestId('term')).toHaveTextContent('devpod2')
    expect(screen.getByTestId('term')).not.toHaveTextContent('devpod1')
  })

  it('retombe sur la première session si ?session cible une session inexistante', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () =>
        HttpResponse.json(['devpod1', 'devpod2']),
      ),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    renderPage('/workspaces/myapp/terminals?session=ghost')
    await waitFor(() => expect(screen.getByTestId('term')).toHaveTextContent('devpod1'))
  })
})

describe('WorkspaceTerminals — clavier mobile', () => {
  /**
   * Meme cause que sur la page terminal plein ecran : le clavier iOS se pose
   * PAR-DESSUS la page sans la redimensionner, donc `h-screen` laissait tout le
   * bas — prompt compris — sous le clavier. Les logs l'ont montre : la frappe
   * partait bien (`readyState: 1`), elle etait juste invisible.
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

  it('borne la page a la hauteur visible', async () => {
    poserVisualViewport(800)

    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('workspace-terminals')).toHaveStyle({ height: '800px' }),
    )
  })

  it('retrecit quand le clavier s’ouvre', async () => {
    const vue = poserVisualViewport(800)
    renderPage()
    await screen.findByTestId('workspace-terminals')

    act(() => vue.retrecir(401))

    expect(screen.getByTestId('workspace-terminals')).toHaveStyle({ height: '401px' })
  })

  it('suit la zone visible quand Safari panne le viewport (clavier iOS)', async () => {
    // iOS deplace la fenetre visible pour reveler la saisie : sans
    // compensation, le conteneur reste ancre en haut du document et tout
    // l'affichage parait decale (bande vide). On le translate d'autant.
    const vue = poserVisualViewport(800)
    renderPage()
    await screen.findByTestId('workspace-terminals')

    act(() => {
      vue.retrecir(401)
      vue.panner(44)
    })

    const page = screen.getByTestId('workspace-terminals')
    expect(page).toHaveStyle({ height: '401px' })
    expect(page).toHaveStyle({ transform: 'translateY(44px)' })
  })

  it('garde 100vh sans l’API', async () => {
    vi.stubGlobal('visualViewport', undefined)

    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('workspace-terminals')).toHaveStyle({ height: '100vh' }),
    )
  })
})

describe('WorkspaceTerminals — session ouverte sur deux appareils', () => {
  /**
   * tmux cale la fenetre sur le client le plus recemment actif : l'ecran le plus
   * petit recoit des lignes trop longues et se retrouve deforme. Rien ne
   * l'expliquait a l'utilisateur, qui n'y voyait qu'un affichage casse.
   */
  function monter(clients: number) {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json(['s1'])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/sessions/:session/clients', () =>
        HttpResponse.json({ clients }),
      ),
    )
    renderPage('/workspaces/myapp/terminals?session=s1')
  }

  it('avertit quand un autre appareil regarde la meme session', async () => {
    monter(2)

    expect(await screen.findByTestId('session-partagee')).toBeInTheDocument()
  })

  it('n’avertit pas pour notre seul terminal', async () => {
    // Le notre compte pour un : avertir des le premier client crierait au loup
    // en permanence.
    monter(1)

    await screen.findByTestId('term')
    expect(screen.queryByTestId('session-partagee')).toBeNull()
  })

  it('n’avertit pas quand le compte est inconnu', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json(['s1'])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/sessions/:session/clients', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    renderPage('/workspaces/myapp/terminals?session=s1')

    await screen.findByTestId('term')
    expect(screen.queryByTestId('session-partagee')).toBeNull()
  })
})
