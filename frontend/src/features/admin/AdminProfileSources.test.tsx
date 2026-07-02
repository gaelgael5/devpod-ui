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
      screen.getByRole('heading', {
        name: /^(galerie profils vs code|vs code profile gallery)$/i,
      })
    ).toBeInTheDocument()
  })

  it('affiche le titre de la galerie', () => {
    renderWithProviders(<AdminProfileSources />)
    // Ancré : « VS Code Profile Gallery » contient aussi « Profile Gallery ».
    expect(
      screen.getByRole('heading', { name: /^(galerie de profils|profile gallery)$/i })
    ).toBeInTheDocument()
  })

  it('affiche le message vide quand la galerie est vide', async () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      await screen.findByText(/aucun profil disponible|no profiles available/i)
    ).toBeInTheDocument()
  })

  it('marque comme importé un profil de la galerie déjà présent en partagé', async () => {
    // « Python Dev » (slug python-dev) existe côté /profiles scope=shared →
    // la carte galerie correspondante porte le flag Importé.
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')
    server.use(
      http.get('/admin/profile-sources/preview', () =>
        HttpResponse.json({
          profiles: [
            {
              filename: 'python-dev.json',
              name: 'Python Dev',
              description: 'Python stack',
              extension_count: 2,
              source_url: 'https://example.com/profiles/python-dev.json',
              source_base: 'https://example.com/profiles',
            },
          ],
        })
      )
    )
    renderWithProviders(<AdminProfileSources />)
    expect(await screen.findByText('Python Dev')).toBeInTheDocument()
    expect(await screen.findByText(/^(importé|imported)$/i)).toBeInTheDocument()
  })

  it('affiche le bouton Importer actif pour un profil non importé', async () => {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')
    server.use(
      http.get('/admin/profile-sources/preview', () =>
        HttpResponse.json({
          profiles: [
            {
              filename: 'go-dev.json',
              name: 'Go Dev',
              description: 'Go stack',
              extension_count: 1,
              source_url: 'https://example.com/profiles/go-dev.json',
              source_base: 'https://example.com/profiles',
            },
          ],
        })
      )
    )
    renderWithProviders(<AdminProfileSources />)
    expect(await screen.findByText('Go Dev')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^(importer|import)$/i })).toBeEnabled()
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
