import { screen, waitFor } from '@testing-library/react'
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
    renderWithProviders(<WorkspaceActionsMenu wsName="ws1" onAddVm={onAddVm} />)

    await user.click(screen.getByRole('button', { name: /actions/i }))
    const addVmItem = await screen.findByRole('menuitem', { name: /add vm for test/i })
    await user.click(addVmItem)

    expect(onAddVm).toHaveBeenCalledOnce()
  })

  it('regroupe les actions Initialize et Add VM for Test dans le même menu', async () => {
    server.use(http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)))
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceActionsMenu wsName="ws1" onAddVm={vi.fn()} />)

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
    renderWithProviders(<WorkspaceActionsMenu wsName="ws1" onAddVm={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /actions/i }))
    const runItem = await screen.findByRole('menuitem', { name: /^(run|lancer)$/i })
    await user.click(runItem)

    await waitFor(() => expect(runUrl).toContain('/initializers/claude-bypass-permissions/run'))
    expect(runUrl).not.toContain('force=true')
  })
})
