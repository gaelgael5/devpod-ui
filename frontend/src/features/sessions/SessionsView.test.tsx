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

describe('SessionsView', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: [], is_admin: false } })
  })

  it('liste les sessions et propose Ouvrir', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    renderWithProviders(<SessionsView />)

    expect(await screen.findByText('alice-proj')).toBeInTheDocument()
    expect(screen.getAllByText('testvm-1').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Open' }).length).toBeGreaterThan(0)
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
    renderWithProviders(<SessionsView />)

    expect(await screen.findByText('orphan')).toBeInTheDocument()
    // Le badge coexiste avec le groupe par host.
    expect(screen.getByRole('rowheader', { name: /host-dev-01/ })).toBeInTheDocument()
  })

  it('regroupe les sessions par host', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    renderWithProviders(<SessionsView />)

    await screen.findByText('alice-proj')
    // Un en-tête de groupe par nœud : le conteneur sous node2, la VM sous elle-même.
    expect(screen.getByRole('rowheader', { name: /node2/ })).toBeInTheDocument()
    expect(screen.getByRole('rowheader', { name: /testvm-1/ })).toBeInTheDocument()
  })

  it('filtre par famille', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await screen.findByText('alice-proj')
    await user.click(screen.getByRole('button', { name: 'Test' }))
    expect(screen.getAllByText('testvm-1').length).toBeGreaterThan(0)
    expect(screen.queryByText('alice-proj')).not.toBeInTheDocument()
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

    // Le workspace d'un autre user est ouvrable par l'admin.
    await screen.findByText('bob-proj')
    const openButtons = screen.getAllByRole('button', { name: 'Open' })
    expect(openButtons.every((b) => !(b as HTMLButtonElement).disabled)).toBe(true)

    // Fermeture du terminal host attaché.
    await user.click(screen.getAllByRole('button', { name: 'Close' })[0])
    expect(body).toEqual({ family: 'host', target: 'node1', owner: 'admin', session: null })
  })
})
