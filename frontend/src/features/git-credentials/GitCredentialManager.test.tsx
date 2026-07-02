import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { toast } from 'sonner'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import GitCredentialManager from './GitCredentialManager'

// Le <Toaster/> de sonner n'est pas monté dans renderWithProviders (aucun test
// du projet n'affirme sur le contenu visuel des toasts) — on espionne les
// appels plutôt que le rendu.
vi.mock('sonner', async () => {
  const actual = await vi.importActual<typeof import('sonner')>('sonner')
  return { ...actual, toast: { ...actual.toast, success: vi.fn(), error: vi.fn() } }
})

const ONE_CREDENTIAL = [
  { name: 'github', host: 'github.com', kind: 'ssh' as const, username: '' },
]

describe('GitCredentialManager — test connection', () => {
  beforeEach(() => {
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('affiche le bouton Tester la connexion sur chaque credential', async () => {
    server.use(http.get('/me/git-credentials', () => HttpResponse.json(ONE_CREDENTIAL)))
    renderWithProviders(<GitCredentialManager />)
    expect(
      await screen.findByRole('button', { name: /test connection|tester la connexion/i })
    ).toBeInTheDocument()
  })

  it('notifie un succès quand la connexion fonctionne', async () => {
    server.use(
      http.get('/me/git-credentials', () => HttpResponse.json(ONE_CREDENTIAL)),
      http.post('/me/git-credentials/github/test', () =>
        HttpResponse.json({ ok: true, message: 'remote: Repository not found.' }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<GitCredentialManager />)
    const btn = await screen.findByRole('button', { name: /test connection|tester la connexion/i })
    await user.click(btn)

    await waitFor(() => expect(toast.success).toHaveBeenCalled())
    expect(vi.mocked(toast.success).mock.calls[0][1]).toMatchObject({
      description: 'remote: Repository not found.',
    })
  })

  it('notifie un échec quand la connexion échoue', async () => {
    server.use(
      http.get('/me/git-credentials', () => HttpResponse.json(ONE_CREDENTIAL)),
      http.post('/me/git-credentials/github/test', () =>
        HttpResponse.json({ ok: false, message: 'Permission denied (publickey).' }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<GitCredentialManager />)
    const btn = await screen.findByRole('button', { name: /test connection|tester la connexion/i })
    await user.click(btn)

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(vi.mocked(toast.error).mock.calls[0][1]).toMatchObject({
      description: 'Permission denied (publickey).',
    })
  })

  it('désactive le bouton pendant le test', async () => {
    server.use(
      http.get('/me/git-credentials', () => HttpResponse.json(ONE_CREDENTIAL)),
      http.post('/me/git-credentials/github/test', async () => {
        await new Promise((r) => setTimeout(r, 50))
        return HttpResponse.json({ ok: true, message: '' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<GitCredentialManager />)
    const btn = await screen.findByRole('button', { name: /test connection|tester la connexion/i })
    await user.click(btn)
    await waitFor(() => expect(btn).toBeDisabled())
  })
})
