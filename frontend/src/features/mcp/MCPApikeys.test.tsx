import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPApikeys from './MCPApikeys'

describe('MCPApikeys', () => {
  it('affiche l\'état vide quand aucune apikey', async () => {
    renderWithProviders(<MCPApikeys />)
    expect(await screen.findByText(/No apikey issued/i)).toBeInTheDocument()
  })

  it('crée une apikey et affiche le token clair une seule fois', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/apikeys', () => HttpResponse.json([])),
      http.post('/me/mcp/apikeys', () =>
        HttpResponse.json({ id: 'a1', token: 'mcpk_secret_once' }, { status: 201 })),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    await user.click(await screen.findByRole('button', { name: /Issue an apikey/i }))
    await user.click(await screen.findByRole('button', { name: /^Save$/i }))

    await waitFor(() => expect(screen.getByText('mcpk_secret_once')).toBeInTheDocument())
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument()
  })

  it('enregistre la curation allowlist avec un outil via le PUT grant', async () => {
    const { server } = await import('@/test/server')
    let putBody: unknown = null
    server.use(
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          { id: 'ak1', owner_login: 'alice', label: 'Laptop', revoked: false, created_at: '' },
        ]),
      ),
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'b1', owner_login: 'alice', namespace: 'rag', name: 'RAG',
            url: 'https://rag/mcp', transport: 'streamable_http', enabled: true,
            created_at: '', updated_at: '',
          },
        ]),
      ),
      http.get('/me/mcp/apikeys/:id/grants', () =>
        HttpResponse.json([
          {
            apikey_id: 'ak1', backend_id: 'b1', backend_key_id: null,
            expose_mode: 'allowlist', expose: [],
          },
        ]),
      ),
      http.put('/me/mcp/apikeys/:id/grants', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ apikey_id: 'ak1', backend_id: 'b1' })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    // Le grant est déjà en mode allowlist → l'éditeur de liste est affiché.
    const input = await screen.findByPlaceholderText(/tool name/i)
    await user.type(input, 'search')
    await user.click(screen.getByRole('button', { name: /^Add$/i }))

    await waitFor(() => {
      expect(putBody).toMatchObject({
        backend_id: 'b1',
        backend_key_id: null,
        expose_mode: 'allowlist',
        expose: ['search'],
      })
    })
  })
})
