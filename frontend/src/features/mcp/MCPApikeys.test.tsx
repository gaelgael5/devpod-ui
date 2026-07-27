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

  it("affiche le profil MCP associé à l'apikey", async () => {
    // La curation par grant (expose_mode/expose) n'existe plus : une apikey
    // référence un profil MCP (curation `tools` portée par les entries du profil).
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          {
            id: 'ak1', owner_login: 'alice', label: 'Laptop', profile_id: 'p1',
            revoked: false, created_at: '', last_used_at: null,
          },
        ]),
      ),
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([
          {
            id: 'p1', owner_login: 'alice', name: 'Perso',
            description: '', created_at: '', updated_at: null,
          },
        ]),
      ),
    )

    renderWithProviders(<MCPApikeys />)

    expect(await screen.findByText('Laptop')).toBeInTheDocument()
    // Le nom du profil apparaît deux fois : badge de la ligne + valeur du sélecteur.
    expect(await screen.findAllByText('Perso')).toHaveLength(2)
  })

  it('une clef workspace affiche le badge et pas le sélecteur de profil (spec 35)', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          {
            id: 'wk1', owner_login: 'alice', label: 'ws claude', profile_id: 'p1',
            revoked: false, created_at: '', last_used_at: null,
            workspace_ref: 'alice-myapp',
          },
        ]),
      ),
      http.get('/me/mcp/profiles', () =>
        HttpResponse.json([
          {
            id: 'p1', owner_login: 'alice', name: 'Perso',
            description: '', created_at: '', updated_at: null,
            exposed_in_workspaces: true,
          },
        ]),
      ),
    )

    renderWithProviders(<MCPApikeys />)

    // Badge « workspace » + ws_id visibles.
    expect(await screen.findByText(/workspace/i)).toBeInTheDocument()
    expect(screen.getByText('alice-myapp')).toBeInTheDocument()
    // Pas de sélecteur de profil (géré par le portail) — profil affiché en lecture seule.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByText('Perso')).toBeInTheDocument()
    // La révocation reste disponible.
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument()
  })

  it('rote une clef bearer : ancienne révoquée, nouveau token affiché une fois', async () => {
    const { server } = await import('@/test/server')
    let rotated = false
    server.use(
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          {
            id: 'ak1', owner_login: 'alice', label: 'Laptop', profile_id: null,
            revoked: false, created_at: '', last_used_at: null,
          },
        ]),
      ),
      http.get('/me/mcp/profiles', () => HttpResponse.json([])),
      http.post('/me/mcp/apikeys/ak1/rotate', () => {
        rotated = true
        return HttpResponse.json({ id: 'ak2', token: 'mcpk_new_secret' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    await user.click(await screen.findByRole('button', { name: /rotate/i }))

    await waitFor(() => expect(screen.getByText('mcpk_new_secret')).toBeInTheDocument())
    expect(rotated).toBe(true)
    expect(screen.getByText(/old key is revoked/i)).toBeInTheDocument()
  })

  it('clef workspace + workspace running : Rotate actif, réinjection sans reveal', async () => {
    const { server } = await import('@/test/server')
    let rotated = false
    server.use(
      http.get('/me', () =>
        HttpResponse.json({ login: 'alice', roles: [], is_admin: false }),
      ),
      http.get('/me/workspaces/myapp/status', () =>
        HttpResponse.json({ status: 'running' }),
      ),
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          {
            id: 'wk1', owner_login: 'alice', label: 'ws claude', profile_id: null,
            revoked: false, created_at: '', last_used_at: null,
            workspace_ref: 'alice-myapp',
          },
        ]),
      ),
      http.get('/me/mcp/profiles', () => HttpResponse.json([])),
      http.post('/me/mcp/apikeys/wk1/rotate', () => {
        rotated = true
        return HttpResponse.json({
          id: 'wk1', workspace: 'alice-myapp', reinjected: true, agents: ['claude'],
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    const btn = await screen.findByRole('button', { name: /rotate/i })
    await waitFor(() => expect(btn).toBeEnabled())
    await user.click(btn)

    await waitFor(() => expect(rotated).toBe(true))
    // Jamais de reveal pour une clef workspace : le token est réinjecté.
    expect(screen.queryByText(/mcpk_/)).not.toBeInTheDocument()
  })

  it('clef workspace + workspace arrêté : Rotate désactivé', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me', () =>
        HttpResponse.json({ login: 'alice', roles: [], is_admin: false }),
      ),
      http.get('/me/workspaces/myapp/status', () =>
        HttpResponse.json({ status: 'stopped' }),
      ),
      http.get('/me/mcp/apikeys', () =>
        HttpResponse.json([
          {
            id: 'wk1', owner_login: 'alice', label: 'ws claude', profile_id: null,
            revoked: false, created_at: '', last_used_at: null,
            workspace_ref: 'alice-myapp',
          },
        ]),
      ),
      http.get('/me/mcp/profiles', () => HttpResponse.json([])),
    )
    renderWithProviders(<MCPApikeys />)

    const btn = await screen.findByRole('button', { name: /rotate/i })
    // Statut chargé → toujours désactivé (workspace non running).
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /rotate/i })).toBeDisabled(),
    )
    expect(btn).toBeDisabled()
  })
})
