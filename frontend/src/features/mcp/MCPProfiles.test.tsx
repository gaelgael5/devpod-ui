import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import MCPProfiles from './MCPProfiles'

const PROFILE = {
  id: 'p1', owner_login: 'alice', name: 'Agent RO', description: '',
  created_at: '2026-01-01T00:00:00Z', updated_at: null,
}

const BACKEND = {
  id: 'devpod-alice', owner_login: 'alice', namespace: 'devpod', name: 'DevPod workspaces',
  url: '', transport: 'internal', enabled: true,
}

const CATALOG = [
  { name: 'workspace_list', description: 'Liste les workspaces.', scope: 'read' },
  { name: 'workspace_status', description: 'Statut.', scope: 'read' },
  { name: 'workspace_delete', description: 'Supprime.', scope: 'admin' },
]

function mockOpenProfile(tools: string[] | null) {
  server.use(
    http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
    http.get('/me/mcp/backends', () => HttpResponse.json([BACKEND])),
    http.get('/me/mcp/profiles/p1', () =>
      HttpResponse.json({
        ...PROFILE,
        entries: [{ profile_id: 'p1', backend_id: 'devpod-alice', backend_key_id: null, tools }],
      })),
    http.get('/me/mcp/backends/devpod-alice/keys', () => HttpResponse.json([])),
    http.get('/me/mcp/backends/devpod-alice/catalog', () => HttpResponse.json(CATALOG)),
  )
}

describe('MCPProfiles — presets de tools', () => {
  it('le préréglage "Lecture seule" ne sélectionne que les tools scope=read', async () => {
    mockOpenProfile(null)
    let putBody: unknown = null
    server.use(
      http.put('/me/mcp/profiles/p1/entries/devpod-alice', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ profile_id: 'p1', backend_id: 'devpod-alice' })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    await user.click(await screen.findByRole('button', { name: /Configure services/i }))
    await user.click(await screen.findByText('DevPod workspaces'))
    await user.click(await screen.findByText('Read-only'))

    expect(putBody).toEqual({
      backend_key_id: null,
      tools: ['workspace_list', 'workspace_status'],
    })
  })

  it('le préréglage "Allow none" vide la sélection', async () => {
    mockOpenProfile(null)
    let putBody: unknown = null
    server.use(
      http.put('/me/mcp/profiles/p1/entries/devpod-alice', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ profile_id: 'p1', backend_id: 'devpod-alice' })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    await user.click(await screen.findByRole('button', { name: /Configure services/i }))
    await user.click(await screen.findByText('DevPod workspaces'))
    await user.click(await screen.findByText('Allow none'))

    expect(putBody).toEqual({ backend_key_id: null, tools: [] })
  })

  it('le bouton "Read-only" est absent si aucun tool du catalogue n\'a scope=read', async () => {
    server.use(
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
      http.get('/me/mcp/backends', () => HttpResponse.json([BACKEND])),
      http.get('/me/mcp/profiles/p1', () =>
        HttpResponse.json({
          ...PROFILE,
          entries: [{ profile_id: 'p1', backend_id: 'devpod-alice', backend_key_id: null, tools: null }],
        })),
      http.get('/me/mcp/backends/devpod-alice/keys', () => HttpResponse.json([])),
      http.get('/me/mcp/backends/devpod-alice/catalog', () =>
        HttpResponse.json([{ name: 'workspace_delete', description: 'Supprime.', scope: 'admin' }])),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    await user.click(await screen.findByRole('button', { name: /Configure services/i }))
    await user.click(await screen.findByText('DevPod workspaces'))

    const dialog = await screen.findByRole('dialog')
    await screen.findByText('Allow all')
    expect(within(dialog).queryByText('Read-only')).not.toBeInTheDocument()
  })
})
