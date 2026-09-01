import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import LandingPage from './LandingPage'

// Ancré sur la STRUCTURE et non sur une phrase : le texte de la landing est
// editorial, il sera relu et reecrit. Un test qui epingle une formulation
// casserait a chaque passe de relecture sans rien prouver de plus.
const titreH1 = () => screen.findByRole('heading', { level: 1 })

// i18n est un singleton, et sa langue initiale depend du detecteur (navigateur,
// localStorage). Sans point de depart explicite, un test qui bascule la langue
// decide de celle du suivant — et le premier depend de l'environnement.
beforeEach(async () => {
  await i18n.changeLanguage('fr')
})
afterEach(async () => {
  await i18n.changeLanguage('fr')
})

describe('LandingPage', () => {
  it('affiche la présentation à un visiteur anonyme', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    renderWithProviders(<LandingPage />)

    expect(await titreH1()).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Essayez gratuitement' })).toHaveAttribute(
      'href',
      '/forfaits'
    )
    expect(screen.getByRole('link', { name: 'Se connecter' })).toHaveAttribute(
      'href',
      '/auth/login'
    )
  })

  it('déroule les trois étapes et les trois arguments', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    renderWithProviders(<LandingPage />)

    await titreH1()
    // Le contenu vit dans i18n : on verifie que les cles sont resolues, pas
    // qu'un texte precis est ecrit — sinon toute relecture editoriale casse le test.
    expect(screen.getByRole('heading', { name: 'Comment ça marche' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ce qui change' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(6)
    expect(screen.queryByText(/landing\./)).not.toBeInTheDocument()
  })

  it("n'affiche pas la présentation à un utilisateur déjà connecté", async () => {
    // Le handler par defaut de /me rend un utilisateur : la page doit rediriger.
    renderWithProviders(<LandingPage />)

    await waitFor(() => {
      expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
    })
  })

  it('ne déclenche aucun appel authentifié, même en changeant de langue', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    // `/me/config` est la route de persistance de la culture : sur une page
    // publique elle rendrait 401, donc une redirection vers la connexion.
    const configAppelee = vi.fn()
    server.use(
      http.get('/me/config', () => {
        configAppelee()
        return HttpResponse.json({ culture: 'fr' })
      }),
      http.put('/me/config', () => {
        configAppelee()
        return HttpResponse.json({ culture: 'en' })
      })
    )

    renderWithProviders(<LandingPage />)
    await titreH1()

    await userEvent.selectOptions(screen.getByRole('combobox'), 'en')

    await waitFor(() => {
      expect(i18n.language).toBe('en')
    })
    expect(configAppelee).not.toHaveBeenCalled()
  })

  it('reste affichée si /me échoue autrement qu\'en 401', async () => {
    // Un 500 ne dit rien de la session. La page publique s'affiche quand meme —
    // c'est le repli le moins mauvais — mais ce verdict ne doit PAS etre range
    // comme « anonyme » : voir useOptionalSession, ou seul un 401 rend `null`.
    server.use(http.get('/me', () => new HttpResponse(null, { status: 500 })))
    renderWithProviders(<LandingPage />)

    expect(await titreH1()).toBeInTheDocument()
  })

  it('retient le choix de langue dans le localStorage', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    renderWithProviders(<LandingPage />)
    await titreH1()

    await userEvent.selectOptions(screen.getByRole('combobox'), 'en')

    await waitFor(() => {
      expect(localStorage.getItem('i18nextLng')).toBe('en')
    })
  })
})
