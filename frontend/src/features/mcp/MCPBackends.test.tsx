import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPBackends from './MCPBackends'

describe('MCPBackends', () => {
  it("affiche l'état vide quand aucun serveur n'est enregistré", async () => {
    renderWithProviders(<MCPBackends />)
    expect(await screen.findByText(/No MCP server registered/i)).toBeInTheDocument()
  })

  it('affiche un serveur enregistré avec son namespace', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'b1',
            owner_login: 'alice',
            namespace: 'rag',
            name: 'RAG',
            url: 'https://rag/mcp',
            transport: 'streamable_http',
            enabled: true,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
    )
    renderWithProviders(<MCPBackends />)

    expect(await screen.findByText('RAG')).toBeInTheDocument()
    expect(screen.getByText('rag')).toBeInTheDocument()
  })

  it('affiche le badge de santé « Online » quand le backend est up', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'b1', owner_login: 'alice', namespace: 'rag', name: 'RAG',
            url: 'https://rag/mcp', transport: 'streamable_http', enabled: true,
            created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
            health: 'up',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
    )
    renderWithProviders(<MCPBackends />)

    expect(await screen.findByText('RAG')).toBeInTheDocument()
    expect(screen.getByText('Online')).toBeInTheDocument()
  })

  it('ouvre le dialog de création de serveur', async () => {
    const user = userEvent.setup()
    renderWithProviders(<MCPBackends />)

    await user.click(await screen.findByRole('button', { name: /Add a server/i }))
    expect(await screen.findByText(/Register an MCP server/i)).toBeInTheDocument()
  })

  it('affiche un bouton "Refresh tools" sur le backend interne devpod (toujours online)', async () => {
    const { server } = await import('@/test/server')
    let probeCalled = false
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'devpod-alice', owner_login: 'alice', namespace: 'devpod',
            name: 'DevPod workspaces', url: '', transport: 'internal', enabled: true,
            created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
            health: 'up',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
      http.post('/me/mcp/backends/:id/probe', () => {
        probeCalled = true
        return HttpResponse.json({ id: 'devpod-alice', health: 'up' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPBackends />)

    const button = await screen.findByTitle('Refresh tools')
    await user.click(button)
    expect(probeCalled).toBe(true)
  })

  it('affiche les primitives en quarantaine et permet de les approuver', async () => {
    const { server } = await import('@/test/server')
    let approveBody: unknown = null
    let quarantined = [
      {
        kind: 'tool', name: 'create_document', description: 'Crée un document.',
        first_seen: '2026-07-05T08:36:00Z', last_seen: '2026-07-06T06:20:00Z',
      },
    ]
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'docflow-1', owner_login: 'admin', namespace: 'docflow',
            name: 'Docflow', url: 'http://x/api/mcp/sse', transport: 'sse', enabled: true,
            app_url: '', quarantine_disabled: false,
            created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
            health: 'up',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
      http.get('/me/mcp/backends/:id/quarantined', () => HttpResponse.json(quarantined)),
      http.post('/me/mcp/backends/:id/quarantined/approve', async ({ request }) => {
        approveBody = await request.json()
        quarantined = []
        return HttpResponse.json({ id: 'docflow-1', kind: 'tool', name: 'create_document' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPBackends />)

    expect(await screen.findByText(/Quarantined primitives/i)).toBeInTheDocument()
    expect(screen.getByText('create_document')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^Approve$/i }))
    expect(approveBody).toEqual({ kind: 'tool', name: 'create_document' })
  })

  it("n'affiche pas la section quarantaine quand il n'y a rien à approuver", async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'docflow-1', owner_login: 'admin', namespace: 'docflow',
            name: 'Docflow', url: 'http://x/api/mcp/sse', transport: 'sse', enabled: true,
            app_url: '', quarantine_disabled: false,
            created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
    )
    renderWithProviders(<MCPBackends />)

    expect(await screen.findByText('Docflow')).toBeInTheDocument()
    expect(screen.queryByText(/Quarantined primitives/i)).not.toBeInTheDocument()
  })

  it('affiche le refresh sur un backend externe ONLINE (resync des primitives)', async () => {
    const { server } = await import('@/test/server')
    let probeCalled = false
    server.use(
      http.get('/me/mcp/backends', () =>
        HttpResponse.json([
          {
            id: 'docflow-1', owner_login: 'admin', namespace: 'docflow',
            name: 'Docflow', url: 'http://x/api/mcp/sse', transport: 'sse', enabled: true,
            created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
            health: 'up',
          },
        ])),
      http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
      http.post('/me/mcp/backends/:id/probe', () => {
        probeCalled = true
        return HttpResponse.json({ id: 'docflow-1', health: 'up' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPBackends />)

    // Régression : le bouton était caché dès que health === 'up' (introuvable
    // sur un service en ligne).
    const button = await screen.findByTitle('Re-check connection and refresh tools')
    await user.click(button)
    expect(probeCalled).toBe(true)
  })
})
