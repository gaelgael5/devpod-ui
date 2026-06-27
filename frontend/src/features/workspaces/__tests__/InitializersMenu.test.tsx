import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import InitializersMenu from '../InitializersMenu'

const INITS = [
  { id: 'claude-bypass-permissions', description: 'Aligne les permissions', version: '1.0.0' },
]

// Radix DropdownMenu s'appuie sur des APIs DOM absentes de jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('InitializersMenu', () => {
  it("ne rend rien quand le workspace n'a aucune action", async () => {
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json([])),
    )
    const { container } = renderWithProviders(<InitializersMenu wsName="ws1" enabled />)
    // Laisse la query se résoudre puis vérifie l'absence de bouton.
    await waitFor(() => expect(container.querySelector('button')).toBeNull())
  })

  it('affiche le bouton quand des actions existent', async () => {
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)),
    )
    renderWithProviders(<InitializersMenu wsName="ws1" enabled />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /initiali[sz]e|initialiser/i })).toBeInTheDocument(),
    )
  })

  it('bouton désactivé quand le workspace est arrêté', async () => {
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)),
    )
    renderWithProviders(<InitializersMenu wsName="ws1" enabled={false} />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /initiali[sz]e|initialiser/i })).toBeDisabled(),
    )
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
    renderWithProviders(<InitializersMenu wsName="ws1" enabled />)

    const trigger = await screen.findByRole('button', { name: /initiali[sz]e|initialiser/i })
    await user.click(trigger)

    const runItem = await screen.findByRole('menuitem', { name: /^(run|lancer)$/i })
    await user.click(runItem)

    await waitFor(() => expect(runUrl).toContain('/initializers/claude-bypass-permissions/run'))
    expect(runUrl).not.toContain('force=true')
  })

  it('clic sur Forcer → POST run avec force=true', async () => {
    let runUrl = ''
    server.use(
      http.get('/me/workspaces/:name/initializers', () => HttpResponse.json(INITS)),
      http.post('/me/workspaces/:name/initializers/:id/run', ({ request }) => {
        runUrl = request.url
        return HttpResponse.json({ applied: true, already_applied: false, log: 'applied' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<InitializersMenu wsName="ws1" enabled />)

    const trigger = await screen.findByRole('button', { name: /initiali[sz]e|initialiser/i })
    await user.click(trigger)

    const forceItem = await screen.findByRole('menuitem', { name: /force|forcer/i })
    await user.click(forceItem)

    await waitFor(() => expect(runUrl).toContain('force=true'))
  })
})
