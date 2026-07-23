import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import SessionsView from './SessionsView'

const SESSIONS = [
  {
    family: 'workspace',
    target: 'alice-proj',
    owner: 'alice',
    host: 'node2',
    session: 'main',
    attached: true,
  },
  {
    family: 'test',
    target: 'testvm-1',
    owner: 'alice',
    host: 'testvm-1',
    workspace: 'proj',
    session: null,
    attached: false,
  },
]

/** Les groupes serveurs sont repliés par défaut : on déplie tout avant d'ass.
 *  `findAllByRole(..., {expanded:false})` attend aussi le chargement des données. */
async function expandGroups(user: ReturnType<typeof userEvent.setup>) {
  const headers = await screen.findAllByRole('button', { expanded: false })
  for (const h of headers) await user.click(h)
}

describe('SessionsView', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: [], is_admin: false } })
  })

  it('liste les sessions et propose Ouvrir', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await expandGroups(user)
    expect(await screen.findByText('alice-proj')).toBeInTheDocument()
    expect(screen.getAllByText('testvm-1').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Open' }).length).toBeGreaterThan(0)
  })

  it('mobile : rend des cartes (pas de tableau) sous le breakpoint md', async () => {
    // matchMedia est stubbé matches:false par le setup → on force le mode mobile.
    const orig = window.matchMedia
    window.matchMedia = ((q: string) => ({
      matches: true,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia
    try {
      server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
      const user = userEvent.setup()
      renderWithProviders(<SessionsView />)

      await expandGroups(user)
      expect(await screen.findByText('alice-proj')).toBeInTheDocument()
      // Variante mobile : aucune <table>, chaque cible n'apparaît qu'une fois.
      expect(document.querySelector('table')).toBeNull()
      expect(screen.getAllByText('alice-proj')).toHaveLength(1)
      expect(screen.getAllByRole('button', { name: 'Open' }).length).toBeGreaterThan(0)
    } finally {
      window.matchMedia = orig
    }
  })

  it('badge « orphan » sur une session vivante hors registre', async () => {
    const orphan = [
      {
        family: 'workspace',
        target: 'admin-workflow',
        owner: 'alice',
        host: 'host-dev-01',
        session: 'workflow1',
        attached: false,
        orphan: true,
      },
    ]
    server.use(http.get('/sessions', () => HttpResponse.json(orphan)))
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    // Le groupe par host est visible même replié ; on déplie pour voir le badge.
    expect(await screen.findByRole('rowheader', { name: /host-dev-01/ })).toBeInTheDocument()
    await expandGroups(user)
    expect(await screen.findByText('orphan')).toBeInTheDocument()
  })

  it('regroupe les sessions par host', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    renderWithProviders(<SessionsView />)

    // Un en-tête de groupe par nœud : le conteneur sous node2, la VM sous elle-même.
    // Les en-têtes sont visibles même repliés (pas besoin de déplier).
    expect(await screen.findByRole('rowheader', { name: /node2/ })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: /testvm-1/ })).toBeInTheDocument()
  })

  it('filtre par famille', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await screen.findByRole('rowheader', { name: /node2/ })
    await user.click(screen.getByRole('button', { name: 'Test' }))
    // testvm-1 reste (son groupe) ; le groupe node2 (alice-proj) disparaît.
    expect(screen.getByRole('rowheader', { name: /testvm-1/ })).toBeInTheDocument()
    expect(screen.queryByRole('rowheader', { name: /node2/ })).not.toBeInTheDocument()
  })

  it('ferme une session workspace via POST /sessions/close', async () => {
    let body: unknown = null
    server.use(
      http.get('/sessions', () => HttpResponse.json(SESSIONS)),
      http.post('/sessions/close', async ({ request }) => {
        body = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await expandGroups(user)
    await screen.findByText('alice-proj')
    await user.click(screen.getAllByRole('button', { name: 'Close' })[0])
    expect(body).toEqual({
      family: 'workspace',
      target: 'alice-proj',
      owner: 'alice',
      session: 'main',
    })
  })

  it('admin : Ouvrir/Fermer actifs sur la session attachée d’un autre user (host)', async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'], is_admin: true } })
    const hostSessions = [
      { family: 'host', target: 'node1', owner: 'admin', session: null, attached: true },
      {
        family: 'workspace',
        target: 'bob-proj',
        owner: 'bob',
        session: 'main',
        attached: true,
      },
    ]
    let body: unknown = null
    server.use(
      http.get('/sessions', () => HttpResponse.json(hostSessions)),
      http.post('/sessions/close', async ({ request }) => {
        body = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await expandGroups(user)
    // Le workspace d'un autre user est ouvrable par l'admin.
    await screen.findByText('bob-proj')
    const openButtons = screen.getAllByRole('button', { name: 'Open' })
    expect(openButtons.every((b) => !(b as HTMLButtonElement).disabled)).toBe(true)

    // Fermeture du terminal host attaché.
    await user.click(screen.getAllByRole('button', { name: 'Close' })[0])
    expect(body).toEqual({ family: 'host', target: 'node1', owner: 'admin', session: null })
  })

  it('signale en bas de page les hosts sans tmux (sessions non persistantes)', async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'], is_admin: true } })
    const entries = [
      { family: 'host', target: 'workflow', owner: 'admin', host: 'workflow', session: null, attached: false, no_tmux: true },
      { family: 'host', target: 'node1', owner: 'admin', host: 'node1', session: 'main', attached: false },
    ]
    server.use(http.get('/sessions', () => HttpResponse.json(entries)))
    renderWithProviders(<SessionsView />)

    const notice = await screen.findByText(/tmux/i)
    expect(notice.textContent).toContain('workflow')
    expect(notice.textContent).not.toContain('node1')
  })

  it("pas de bannière tmux quand tous les hosts l'ont", async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'], is_admin: true } })
    const entries = [
      { family: 'host', target: 'node1', owner: 'admin', host: 'node1', session: 'main', attached: false },
    ]
    server.use(http.get('/sessions', () => HttpResponse.json(entries)))
    renderWithProviders(<SessionsView />)

    await screen.findAllByText('node1')
    expect(screen.queryByText(/tmux n'est pas installé|tmux is not installed/i)).not.toBeInTheDocument()
  })

  it('host : ouvre la session tmux ciblée (?session=) et peut fermer même détachée', async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'], is_admin: true } })
    const hostSessions = [
      { family: 'host', target: 'node1', owner: 'admin', host: 'node1', session: 'ops', attached: false },
    ]
    let body: unknown = null
    server.use(
      http.get('/sessions', () => HttpResponse.json(hostSessions)),
      http.post('/sessions/close', async ({ request }) => {
        body = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await expandGroups(user)
    await screen.findByText('ops')
    await user.click(screen.getByRole('button', { name: 'Open' }))
    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining(encodeURIComponent('/admin/hosts/node1/ssh?session=ops')),
      '_blank',
      'noopener',
    )
    openSpy.mockRestore()

    // Détachée mais tmux vivant → fermeture (tue la session distante).
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(body).toEqual({ family: 'host', target: 'node1', owner: 'admin', session: 'ops' })
  })
})
