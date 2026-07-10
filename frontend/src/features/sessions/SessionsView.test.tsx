import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import SessionsView from './SessionsView'

const SESSIONS = [
  { family: 'workspace', target: 'alice-proj', owner: 'alice', session: 'main', attached: true },
  {
    family: 'test',
    target: 'testvm-1',
    owner: 'alice',
    workspace: 'proj',
    session: null,
    attached: false,
  },
]

describe('SessionsView', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: [] } })
  })

  it('liste les sessions et propose Ouvrir', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    renderWithProviders(<SessionsView />)

    expect(await screen.findByText('alice-proj')).toBeInTheDocument()
    expect(screen.getByText('testvm-1')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Open' }).length).toBeGreaterThan(0)
  })

  it('filtre par famille', async () => {
    server.use(http.get('/sessions', () => HttpResponse.json(SESSIONS)))
    const user = userEvent.setup()
    renderWithProviders(<SessionsView />)

    await screen.findByText('alice-proj')
    await user.click(screen.getByRole('button', { name: 'Test' }))
    expect(screen.getByText('testvm-1')).toBeInTheDocument()
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
    useUserStore.setState({ user: { login: 'root', roles: ['admin'] } })
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
