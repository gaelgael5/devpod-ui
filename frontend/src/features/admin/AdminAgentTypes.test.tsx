import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import { useUserStore } from '@/store/user'
import AdminAgentTypes from './AdminAgentTypes'

const CLAUDE = {
  id: 'claude',
  label: 'Claude Code',
  filename: '.mcp.json',
  template: '{"mcpServers": {}}',
  target_path: '{project_root}',
  mode: 'replace',
  enabled: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
}

const CODEX = {
  ...CLAUDE,
  id: 'codex',
  label: 'Codex CLI',
  filename: 'config.toml',
  target_path: '{home}/.codex/config.toml',
  mode: 'merge',
  enabled: false,
}

describe('AdminAgentTypes', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('liste les types d\'agents (id, label, filename, target_path, enabled)', async () => {
    server.use(http.get('/admin/agent-types', () => HttpResponse.json([CLAUDE])))

    renderWithProviders(<AdminAgentTypes />)

    expect(await screen.findByText('claude')).toBeInTheDocument()
    expect(screen.getByText('Claude Code')).toBeInTheDocument()
    expect(screen.getByText('.mcp.json')).toBeInTheDocument()
    expect(screen.getByText('{project_root}')).toBeInTheDocument()
  })

  it('crée un type d\'agent via le dialog (POST /admin/agent-types)', async () => {
    let postBody: unknown = null
    server.use(
      http.get('/admin/agent-types', () => HttpResponse.json([])),
      http.post('/admin/agent-types', async ({ request }) => {
        postBody = await request.json()
        return HttpResponse.json({ ...CLAUDE }, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminAgentTypes />)

    await user.click(await screen.findByRole('button', { name: /Add an agent type/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Identifier/i), 'claude')
    await user.type(within(dialog).getByLabelText(/^Label$/i), 'Claude Code')
    await user.type(within(dialog).getByLabelText(/Filename/i), '.mcp.json')
    await user.type(within(dialog).getByLabelText(/Target path/i), '{{project_root}')
    await user.type(within(dialog).getByLabelText(/Template/i), 'x')
    await user.click(within(dialog).getByRole('button', { name: /^Save$/i }))

    await waitFor(() => expect(postBody).not.toBeNull())
    expect(postBody).toEqual({
      id: 'claude',
      label: 'Claude Code',
      filename: '.mcp.json',
      template: 'x',
      target_path: '{project_root}',
      mode: 'replace',
      enabled: true,
    })
  })

  it('affiche la pastille de mode (replace/merge) dans la table', async () => {
    server.use(http.get('/admin/agent-types', () => HttpResponse.json([CLAUDE, CODEX])))

    renderWithProviders(<AdminAgentTypes />)

    expect(await screen.findByText('codex')).toBeInTheDocument()
    expect(screen.getByText(/^Replace$/i)).toBeInTheDocument()
    expect(screen.getByText(/^Merge$/i)).toBeInTheDocument()
  })

  it('le PATCH porte le mode sélectionné dans le dialog', async () => {
    let patchBody: unknown = null
    server.use(
      http.get('/admin/agent-types', () => HttpResponse.json([CODEX])),
      http.patch('/admin/agent-types/codex', async ({ request }) => {
        patchBody = await request.json()
        return HttpResponse.json({ ...CODEX })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminAgentTypes />)

    await user.click(await screen.findByRole('button', { name: /^Edit$/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Save$/i }))

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toMatchObject({ mode: 'merge' })
  })

  it('prévisualise le template et affiche le rendu', async () => {
    let previewBody: unknown = null
    server.use(
      http.get('/admin/agent-types', () => HttpResponse.json([CLAUDE])),
      http.post('/admin/agent-types/claude/preview', async ({ request }) => {
        previewBody = await request.json()
        return HttpResponse.json({ content: '{"rendered": "mcpk_XXXX"}' })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminAgentTypes />)

    await user.click(await screen.findByRole('button', { name: /^Edit$/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /Preview/i }))

    expect(await screen.findByText('{"rendered": "mcpk_XXXX"}')).toBeInTheDocument()
    expect(previewBody).toEqual({ template: '{"mcpServers": {}}' })
  })

  it('affiche l\'erreur 422 du preview (template Jinja invalide)', async () => {
    server.use(
      http.get('/admin/agent-types', () => HttpResponse.json([CLAUDE])),
      http.post('/admin/agent-types/claude/preview', () =>
        HttpResponse.json({ detail: 'Jinja error: unexpected end of template' }, { status: 422 })),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminAgentTypes />)

    await user.click(await screen.findByRole('button', { name: /^Edit$/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /Preview/i }))

    expect(
      await screen.findByText(/Jinja error: unexpected end of template/i),
    ).toBeInTheDocument()
  })

  it('suppression refusée (409) : le detail est affiché dans la confirmation', async () => {
    server.use(
      http.get('/admin/agent-types', () => HttpResponse.json([CLAUDE])),
      http.delete('/admin/agent-types/claude', () =>
        HttpResponse.json(
          { detail: 'Agent type referenced by workspaces: alice-myapp' },
          { status: 409 },
        )),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminAgentTypes />)

    await user.click(await screen.findByRole('button', { name: /^Delete$/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Delete$/i }))

    expect(
      await screen.findByText(/referenced by workspaces: alice-myapp/i),
    ).toBeInTheDocument()
  })
})
