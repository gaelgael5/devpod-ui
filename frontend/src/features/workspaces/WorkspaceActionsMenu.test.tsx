import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceActionsMenu from './WorkspaceActionsMenu'

const INITS = [
  { id: 'claude-bypass-permissions', description: 'Aligne les permissions', version: '1.0.0' },
]

// Radix DropdownMenu s'appuie sur des APIs DOM absentes de jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('WorkspaceActionsMenu', () => {
  it("propose \"Add VM for Test\" même sans initializer", async () => {
    server.use(http.get('/me/workspaces/:name/initializers', () => HttpResponse.json([])))
    const user = userEvent.setup()
    const onAddVm = vi.fn()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        onAddVm={onAddVm}
        onOpenShell={vi.fn()}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    const addVmItem = await screen.findByRole('menuitem', { name: /add vm for test/i })
    await user.click(addVmItem)

    expect(onAddVm).toHaveBeenCalledOnce()
  })

  it('regroupe les actions Initialize et Add VM for Test dans le même menu', async () => {
    server.use(http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)))
    const user = userEvent.setup()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        onAddVm={vi.fn()}
        onOpenShell={vi.fn()}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))

    expect(await screen.findByRole('menuitem', { name: /^(run|lancer)$/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /force|forcer/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /add vm for test/i })).toBeInTheDocument()
  })

  it('clic sur Lancer → POST run sans force', async () => {
    let runUrl = ''
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)),
      http.post('/me/workspaces/:name/initializers/:id/run', ({ request }) => {
        runUrl = request.url
        return HttpResponse.json({ applied: true, already_applied: false, log: 'applied' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        onAddVm={vi.fn()}
        onOpenShell={vi.fn()}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    const runItem = await screen.findByRole('menuitem', { name: /^(run|lancer)$/i })
    await user.click(runItem)

    await waitFor(() => expect(runUrl).toContain('/initializers/claude-bypass-permissions/run'))
    expect(runUrl).not.toContain('force=true')
  })

  it('propose le shell SSH dans le menu quand le workspace tourne', async () => {
    server.use(http.get('/me/workspaces/:name/initializers', () => HttpResponse.json([])))
    const user = userEvent.setup()
    const onOpenShell = vi.fn()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        onAddVm={vi.fn()}
        onOpenShell={onOpenShell}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /shell ssh|ssh shell/i }))

    expect(onOpenShell).toHaveBeenCalledOnce()
  })

  it('propose la clé SSH même workspace arrêté, sans les actions running', async () => {
    const user = userEvent.setup()
    const onShowSshKey = vi.fn()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running={false}
        onAddVm={vi.fn()}
        onOpenShell={vi.fn()}
        onShowSshKey={onShowSshKey}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /clé ssh|ssh key/i }))

    expect(onShowSshKey).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menuitem', { name: /add vm for test/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /shell ssh|ssh shell/i })).not.toBeInTheDocument()
  })

  it('regroupe Messages, Logs et Gérer les groupes dans le menu', async () => {
    server.use(http.get('/me/workspaces/:name/initializers', () => HttpResponse.json([])))
    const user = userEvent.setup()
    const onOpenMessages = vi.fn()
    const onOpenLogs = vi.fn()
    const onManageGroups = vi.fn()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        onAddVm={vi.fn()}
        onOpenShell={vi.fn()}
        onOpenMessages={onOpenMessages}
        onOpenLogs={onOpenLogs}
        onManageGroups={onManageGroups}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /^messages$/i }))
    expect(onOpenMessages).toHaveBeenCalledOnce()

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /^logs$/i }))
    expect(onOpenLogs).toHaveBeenCalledOnce()

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(
      await screen.findByRole('menuitem', { name: /gérer les groupes|manage groups/i }),
    )
    expect(onManageGroups).toHaveBeenCalledOnce()
  })

  it("propose un sous-menu d'agents MCP à cocher, pré-coché selon les agents actuels", async () => {
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json([])),
      http.get('/me/agent-types', () =>
        HttpResponse.json([
          { id: 'claude', label: 'Claude Code' },
          { id: 'codex', label: 'Codex' },
        ]),
      ),
    )
    let patched: unknown = null
    server.use(
      http.patch('/me/workspaces/:name/agents', async ({ request }) => {
        patched = await request.json()
        return HttpResponse.json({ name: 'ws1', agents: (patched as { agents: string[] }).agents })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(
      <WorkspaceActionsMenu
        wsName="ws1"
        running
        agents={['claude']}
        onAddVm={vi.fn()}
        onOpenShell={vi.fn()}
        onOpenMessages={vi.fn()}
        onOpenLogs={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /mcp agents/i }))

    const claudeItem = await screen.findByRole('menuitemcheckbox', { name: /claude code/i })
    expect(claudeItem).toHaveAttribute('aria-checked', 'true')
    const codexItem = screen.getByRole('menuitemcheckbox', { name: /codex/i })
    expect(codexItem).toHaveAttribute('aria-checked', 'false')

    fireEvent.click(codexItem)

    await waitFor(() => expect(patched).toEqual({ agents: ['claude', 'codex'] }))
  })
})
