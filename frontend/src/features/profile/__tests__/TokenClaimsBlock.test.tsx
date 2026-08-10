import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import ProfilePage from '../ProfilePage'

function mockProfile() {
  server.use(
    http.get('/me/profile', () =>
      HttpResponse.json({ login: 'gael', email: '', display_name: '', identity: '' }),
    ),
  )
}

describe('TokenClaimsBlock', () => {
  it('affiche les claims du jeton avec le sub en tête', async () => {
    mockProfile()
    server.use(
      http.get('/me/token-claims', () =>
        HttpResponse.json({
          claims: { sub: 'abc-123', email: 'u@x.org', preferred_username: 'gael' },
        }),
      ),
    )
    const { findByText, findByTitle } = renderWithProviders(<ProfilePage />, { route: '/profile' })
    expect(await findByText(/jeton d.identit|identity token/i)).toBeInTheDocument()
    expect(await findByTitle('abc-123')).toBeInTheDocument()
    expect(await findByTitle('u@x.org')).toBeInTheDocument()
  })

  it('copie la valeur du claim dans le presse-papier', async () => {
    mockProfile()
    server.use(
      http.get('/me/token-claims', () => HttpResponse.json({ claims: { sub: 'copy-me' } })),
    )
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    const { findAllByRole } = renderWithProviders(<ProfilePage />, { route: '/profile' })
    const copyButtons = await findAllByRole('button', { name: /copier|copy/i })
    copyButtons[copyButtons.length - 1].click()
    expect(writeText).toHaveBeenCalledWith('copy-me')
  })
})
