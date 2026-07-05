import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import EventsTab from './EventsTab'

const EVENT_OK = {
  id: 'a'.repeat(32),
  type: 'workspace.created',
  actor: 'alice',
  workspace: 'mon-projet',
  subject: { ws_id: 'alice-mon-projet', node: 'node1' },
  correlation_id: null,
  occurred_at: '2026-07-05T12:00:00Z',
  deliveries: [
    {
      id: 1,
      event_id: 'a'.repeat(32),
      listener: 'docflow-bootstrap',
      status: 'ok',
      error: null,
      finished_at: '2026-07-05T12:00:01Z',
    },
  ],
}

const EVENT_ERROR = {
  ...EVENT_OK,
  id: 'b'.repeat(32),
  type: 'session.created',
  workspace: 'autre-ws',
  deliveries: [
    {
      id: 2,
      event_id: 'b'.repeat(32),
      listener: 'docflow-bootstrap',
      status: 'error',
      error: 'AutomationError: backend indisponible',
      finished_at: '2026-07-05T12:01:00Z',
    },
  ],
}

describe('EventsTab', () => {
  it('affiche les événements avec le statut de leurs livraisons', async () => {
    server.use(http.get('/me/events', () => HttpResponse.json([EVENT_OK, EVENT_ERROR])))
    renderWithProviders(<EventsTab />)

    expect(await screen.findByText('workspace.created')).toBeInTheDocument()
    expect(screen.getByText('session.created')).toBeInTheDocument()
    expect(screen.getByText('mon-projet')).toBeInTheDocument()
    expect(screen.getByText('docflow-bootstrap: ok')).toBeInTheDocument()
    expect(screen.getByText('docflow-bootstrap: error')).toBeInTheDocument()
  })

  it("affiche l'état vide sans événement", async () => {
    server.use(http.get('/me/events', () => HttpResponse.json([])))
    renderWithProviders(<EventsTab />)
    expect(await screen.findByText(/aucun événement|no event/i)).toBeInTheDocument()
  })

  it("n'affiche que la dernière livraison par écouteur (historique de rejeux)", async () => {
    const replayed = {
      ...EVENT_ERROR,
      deliveries: [
        ...EVENT_ERROR.deliveries,
        { ...EVENT_ERROR.deliveries[0], id: 3, status: 'ok', error: null },
      ],
    }
    server.use(http.get('/me/events', () => HttpResponse.json([replayed])))
    renderWithProviders(<EventsTab />)
    expect(await screen.findByText('docflow-bootstrap: ok')).toBeInTheDocument()
    expect(screen.queryByText('docflow-bootstrap: error')).not.toBeInTheDocument()
  })

  it('affiche le détail des règles déclenchées et leurs erreurs', async () => {
    const withDetail = {
      ...EVENT_ERROR,
      id: 'c'.repeat(32),
      deliveries: [
        {
          id: 4,
          event_id: 'c'.repeat(32),
          listener: 'user-rules',
          status: 'error',
          error: 'AutomationError: règle(s) en échec: cassée',
          detail: [
            { rule: 'docflow bootstrap', matched: true, actions_ran: 3 },
            { rule: 'sans effet', matched: false, actions_ran: 0 },
            { rule: 'cassée', rule_id: 'r9', error: 'AutomationError: service manquant' },
          ],
          finished_at: '2026-07-05T12:02:00Z',
        },
      ],
    }
    server.use(http.get('/me/events', () => HttpResponse.json([withDetail])))
    renderWithProviders(<EventsTab />)

    expect(await screen.findByText('docflow bootstrap')).toBeInTheDocument()
    expect(screen.getByText(/3 action\(s\)/)).toBeInTheDocument()
    expect(screen.getByText(/conditions fausses|conditions false/)).toBeInTheDocument()
    expect(screen.getByText(/service manquant/)).toBeInTheDocument()
  })

  it('rejoue un événement (POST /replay)', async () => {
    let replayedId: string | null = null
    server.use(
      http.get('/me/events', () => HttpResponse.json([EVENT_ERROR])),
      http.post('/me/events/:id/replay', ({ params }) => {
        replayedId = params.id as string
        return HttpResponse.json({ replayed: params.id }, { status: 202 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EventsTab />)

    await user.click(await screen.findByRole('button', { name: /rejouer|replay/i }))
    await waitFor(() => expect(replayedId).toBe('b'.repeat(32)))
  })
})
