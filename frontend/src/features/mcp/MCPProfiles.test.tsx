import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import MCPProfiles from './MCPProfiles'

const PROFILE = {
  id: 'p1', owner_login: 'alice', name: 'Agent RO', description: '',
  created_at: '2026-01-01T00:00:00Z', updated_at: null,
  exposed_in_workspaces: false,
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

describe('MCPProfiles — exposition aux workspaces (spec 35)', () => {
  it('cocher le switch appelle PUT …/exposed avec {exposed:true} sans confirmation', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([{ ...PROFILE, exposed_in_workspaces: false }])),
      http.put('/me/mcp/profiles/p1/exposed', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ id: "p1", exposed: true, affected_workspaces: [], unexposed_profiles: [] })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    await user.click(await screen.findByRole('switch', { name: /Exposed .*to workspaces/i }))

    await waitFor(() => expect(putBody).toEqual({ exposed: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('décocher affiche une confirmation et n\'appelle PUT qu\'après confirmation', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([{ ...PROFILE, exposed_in_workspaces: true }])),
      http.put('/me/mcp/profiles/p1/exposed', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({
          id: 'p1', exposed: false, affected_workspaces: ['alice-ws1', 'alice-ws2'],
        })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    await user.click(await screen.findByRole('switch', { name: /Exposed .*to workspaces/i }))

    // La confirmation est affichée, la mutation n'est pas encore partie.
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/immediately revokes/i)).toBeInTheDocument()
    expect(putBody).toBeNull()

    await user.click(within(dialog).getByRole('button', { name: /Revoke and remove/i }))

    await waitFor(() => expect(putBody).toEqual({ exposed: false }))
  })

  it("basculer vers un autre profil demande confirmation, désactive le précédent et prévient de la coupure", async () => {
    let putBody: unknown = null
    let putUrl = ''
    server.use(
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([
          { ...PROFILE, id: 'p1', name: 'Claude code', exposed_in_workspaces: true },
          { ...PROFILE, id: 'p2', name: 'Claude web', exposed_in_workspaces: false },
        ])),
      http.put('/me/mcp/profiles/p2/exposed', async ({ request }) => {
        putBody = await request.json()
        putUrl = request.url
        return HttpResponse.json({
          id: 'p2', exposed: true, affected_workspaces: ['alice-ws1'],
          unexposed_profiles: ['Claude code'],
        })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    // Le switch du profil NON exposé (p2 = « Claude web »).
    const switches = await screen.findAllByRole('switch', { name: /Exposed .*to workspaces/i })
    await user.click(switches[1])

    // Confirmation exigée : rien n'est parti, et l'impact est annoncé.
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Claude code/)).toBeInTheDocument()
    expect(within(dialog).getByText(/disconnected/i)).toBeInTheDocument()
    expect(putBody).toBeNull()

    await user.click(within(dialog).getByRole('button', { name: /Switch and disconnect/i }))

    await waitFor(() => expect(putBody).toEqual({ exposed: true }))
    expect(putUrl).toContain('/profiles/p2/exposed')
  })

  it("exposer le premier profil (aucun autre exposé) ne demande aucune confirmation", async () => {
    let putBody: unknown = null
    server.use(
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([
          { ...PROFILE, id: 'p1', name: 'Claude code', exposed_in_workspaces: false },
          { ...PROFILE, id: 'p2', name: 'Claude web', exposed_in_workspaces: false },
        ])),
      http.put('/me/mcp/profiles/p1/exposed', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({
          id: 'p1', exposed: true, affected_workspaces: [], unexposed_profiles: [],
        })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<MCPProfiles />)

    const switches = await screen.findAllByRole('switch', { name: /Exposed .*to workspaces/i })
    await user.click(switches[0])

    await waitFor(() => expect(putBody).toEqual({ exposed: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
