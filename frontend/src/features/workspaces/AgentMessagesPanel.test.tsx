// frontend/src/features/workspaces/AgentMessagesPanel.test.tsx
/** Panneau « Demandes inter-agents » : liste pending, rejet, ouverture délivrance. */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AgentMessagesPanel from './AgentMessagesPanel'

const MSG = {
  id: 'm1',
  created_at: '2026-07-05T06:00:00Z',
  from_ws_id: 'admin-rag',
  to_ws_id: 'admin-devpod',
  from_name: 'rag',
  to_name: 'devpod',
  from_session: null,
  subject: 'Contrat API',
  body: 'Quel format de réponse ?',
  reply_to: null,
  status: 'pending',
  delivered_at: null,
  delivered_to_session: null,
}

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('AgentMessagesPanel', () => {
  it('liste les messages pending avec émetteur → destinataire', async () => {
    server.use(
      http.get('/me/agent-messages', () => HttpResponse.json([MSG])),
    )
    renderWithProviders(<AgentMessagesPanel open onOpenChange={vi.fn()} />)

    expect(await screen.findByText('Contrat API')).toBeInTheDocument()
    expect(screen.getByText(/rag/)).toBeInTheDocument()
    expect(screen.getByText(/devpod/)).toBeInTheDocument()
  })

  it('rejette un message (POST cancel)', async () => {
    let cancelled = ''
    server.use(
      http.get('/me/agent-messages', () => HttpResponse.json([MSG])),
      http.post('/me/agent-messages/:id/cancel', ({ params }) => {
        cancelled = String(params.id)
        return HttpResponse.json({ status: 'cancelled' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AgentMessagesPanel open onOpenChange={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: /rejeter|reject/i }))
    await waitFor(() => expect(cancelled).toBe('m1'))
  })

  it('ouvre le dialog de délivrance et transmet vers la session choisie', async () => {
    let delivered: { id: string; session: string } | null = null
    server.use(
      http.get('/me/agent-messages', () => HttpResponse.json([MSG])),
      http.get('/me/workspaces/devpod/sessions', () => HttpResponse.json(['main'])),
      http.post('/me/agent-messages/:id/deliver', async ({ params, request }) => {
        const body = (await request.json()) as { session: string }
        delivered = { id: String(params.id), session: body.session }
        return HttpResponse.json({ status: 'delivered', delivered_to_session: body.session })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AgentMessagesPanel open onOpenChange={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: /transmettre|deliver/i }))
    // session unique 'main' pré-sélectionnée → bouton Transmettre du dialog actif
    const submit = await screen.findByRole('button', { name: /^(transmettre|deliver)$/i })
    await user.click(submit)

    await waitFor(() => expect(delivered).toEqual({ id: 'm1', session: 'main' }))
  })

  it('affiche un état vide sans message', async () => {
    server.use(http.get('/me/agent-messages', () => HttpResponse.json([])))
    renderWithProviders(<AgentMessagesPanel open onOpenChange={vi.fn()} />)
    expect(await screen.findByText(/aucune demande|no pending/i)).toBeInTheDocument()
  })
})
