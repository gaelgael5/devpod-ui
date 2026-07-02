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
})
