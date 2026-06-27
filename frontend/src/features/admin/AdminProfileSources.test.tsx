import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminProfileSources from './AdminProfileSources'

describe('AdminProfileSources', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre de la section sources', () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      screen.getByRole('heading', { name: /sources configurées|configured sources/i })
    ).toBeInTheDocument()
  })

  it('affiche le titre de la galerie', () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      screen.getByRole('heading', { name: /galerie de profils|profile gallery/i })
    ).toBeInTheDocument()
  })

  it('affiche le message vide quand la galerie est vide', async () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      await screen.findByText(/aucun profil disponible|no profiles available/i)
    ).toBeInTheDocument()
  })

  it('affiche la section des profils importés', () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      screen.getByRole('heading', { name: /profils importés|imported profiles/i })
    ).toBeInTheDocument()
  })

  it('affiche les profils partagés dans la liste locale', async () => {
    renderWithProviders(<AdminProfileSources />)
    expect(await screen.findByText('Python Dev')).toBeInTheDocument()
  })

  it("permet d'ajouter une source via le champ texte", async () => {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')

    const captured: unknown[] = []
    server.use(
      http.put('/admin/profile-sources', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      })
    )

    renderWithProviders(<AdminProfileSources />)
    const input = screen.getByPlaceholderText(/https:\/\/raw\.githubusercontent\.com/i)
    await userEvent.type(input, 'https://example.com/profiles/')
    await userEvent.click(screen.getByRole('button', { name: /ajouter|add/i }))

    expect(captured).toHaveLength(1)
    expect((captured[0] as { sources: string[] }).sources).toContain(
      'https://example.com/profiles/'
    )
  })
})
