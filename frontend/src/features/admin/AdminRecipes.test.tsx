import { screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminRecipes from './AdminRecipes'

describe('AdminRecipes', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'], is_admin: true } })
  })

  it('affiche le titre', () => {
    renderWithProviders(<AdminRecipes />)
    expect(screen.getByRole('heading', { name: /local recipes|recettes locales/i })).toBeInTheDocument()
  })
})

describe('AdminRecipes — mises a jour disponibles', () => {
  /**
   * Une recette importee garde le lien vers son manifeste. La page interroge la
   * source a l'affichage : le bouton n'apparait que sur les vignettes dont la
   * version publiee a bouge.
   */
  const RECETTE = {
    id: 'android-emulator',
    key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af',
    version: '1.0.0',
    description: 'Chaine Android',
    type: 'install',
    scope: 'shared',
    installs_after: [],
    requires_secrets: [],
  }

  function renderPage(updates: unknown[]) {
    server.use(
      http.get('/admin/recipes', () => HttpResponse.json([RECETTE])),
      http.get('/admin/recipes/updates', () => HttpResponse.json(updates)),
    )
    renderWithProviders(<AdminRecipes />)
  }

  it('affiche le bouton sur une recette en retard', async () => {
    renderPage([
      {
        id: 'android-emulator',
        local_version: '1.0.0',
        remote_version: '2.0.0',
        source_url: 'https://x/a/install.sh',
      },
    ])

    expect(
      await screen.findByRole('button', { name: /mettre à jour \(2\.0\.0\)|update \(2\.0\.0\)/i }),
    ).toBeInTheDocument()
  })

  it('n’affiche rien quand tout est a jour', async () => {
    renderPage([])

    // La vignette est bien rendue…
    expect(await screen.findByText('android-emulator')).toBeInTheDocument()
    // …sans bouton de mise a jour.
    expect(screen.queryByRole('button', { name: /mettre à jour|^update/i })).toBeNull()
  })

  it('n’empeche pas la page de s’afficher si la verification echoue', async () => {
    // Chaque source est interrogee en distant : c'est lent et faillible. La
    // liste locale ne doit pas en dependre.
    server.use(
      http.get('/admin/recipes', () => HttpResponse.json([RECETTE])),
      http.get('/admin/recipes/updates', () => new HttpResponse(null, { status: 502 })),
    )
    renderWithProviders(<AdminRecipes />)

    expect(await screen.findByText('android-emulator')).toBeInTheDocument()
  })
})
