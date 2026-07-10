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
})
