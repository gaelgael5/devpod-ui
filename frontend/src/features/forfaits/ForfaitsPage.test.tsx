import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import ForfaitsPage from './ForfaitsPage'
import type { OffrePubliee } from './useOffresPubliques'

function offre(extra: Partial<OffrePubliee> = {}): OffrePubliee {
  return {
    slug: 'standard',
    titles: { fr: 'Standard', en: 'Standard' },
    descriptions: { fr: 'Pour commencer', en: 'To get started' },
    hosting_type: 'mutualise',
    max_workspaces: 3,
    max_hosts_dedies: null,
    is_free: false,
    duration_days: 30,
    currency: 'EUR',
    amount_minor: 1200,
    prices_include_tax: true,
    ...extra,
  }
}

function servir(offres: OffrePubliee[]): void {
  server.use(http.get('/offers', () => HttpResponse.json(offres)))
}

beforeEach(async () => {
  await i18n.changeLanguage('fr')
})
afterEach(async () => {
  await i18n.changeLanguage('fr')
})

describe('ForfaitsPage', () => {
  it('affiche un forfait mutualisé avec son prix et son quota', async () => {
    servir([offre()])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('Standard')).toBeInTheDocument()
    expect(screen.getByText('12,00 €')).toBeInTheDocument()
    expect(screen.getByText('TTC')).toBeInTheDocument()
    expect(screen.getByText('Workspaces inclus : 3')).toBeInTheDocument()
    expect(screen.getByText('Durée : 30 jours')).toBeInTheDocument()
  })

  it('rend le markdown du titre et de la description', async () => {
    // Les deux champs sont saisis en markdown cote admin : les afficher bruts
    // montrait les `**` au visiteur.
    servir([
      offre({
        titles: { fr: 'Offre **plus**' },
        descriptions: { fr: 'Tout pour démarrer :\n\n- deux workspaces\n- **rien à installer**' },
      }),
    ])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('plus')).toBeInTheDocument()
    expect(screen.getByText('rien à installer')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').some((li) => li.textContent?.includes('deux workspaces'))).toBe(true)
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
  })

  it('rend les quotas du dédié différemment de ceux du mutualisé', async () => {
    servir([
      offre({
        slug: 'max',
        titles: { fr: 'Max' },
        hosting_type: 'dedie',
        max_hosts_dedies: 2,
        max_workspaces: 8,
      }),
    ])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('Machines dédiées : 2')).toBeInTheDocument()
    expect(screen.getByText('Workspaces par machine : 8')).toBeInTheDocument()
    expect(screen.queryByText(/Workspaces inclus/)).not.toBeInTheDocument()
  })

  it('lit « illimité » sur un quota nul, jamais zéro', async () => {
    servir([offre({ max_workspaces: null })])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('Workspaces inclus : illimité')).toBeInTheDocument()
  })

  it('affiche une offre gratuite via is_free, pas via un montant nul', async () => {
    servir([offre({ is_free: true, amount_minor: null })])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('Gratuit')).toBeInTheDocument()
    expect(screen.queryByText('TTC')).not.toBeInTheDocument()
  })

  it('propose de se connecter à un visiteur anonyme', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    servir([offre()])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByRole('link', { name: 'Se connecter' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Accueil/ })).toHaveAttribute('href', '/')
  })

  it('renvoie un abonné vers ses workspaces, et ne lui propose pas de se connecter', async () => {
    // Le handler par defaut de /me rend un utilisateur connecte.
    servir([offre()])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByRole('link', { name: /Mes workspaces/ })).toHaveAttribute(
      'href',
      '/workspaces'
    )
    expect(screen.queryByRole('link', { name: 'Se connecter' })).not.toBeInTheDocument()
  })

  it("n'affiche pas de prix quand l'offre n'en a pas dans la devise par défaut", async () => {
    servir([offre({ amount_minor: null })])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('Prix sur demande')).toBeInTheDocument()
  })

  it('étiquette un montant saisi hors taxe comme tel', async () => {
    servir([offre({ prices_include_tax: false })])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('HT')).toBeInTheDocument()
    expect(screen.queryByText('TTC')).not.toBeInTheDocument()
  })

  it('retombe sur le titre anglais puis sur le slug si la langue manque', async () => {
    servir([offre({ slug: 'sans-titre', titles: {}, descriptions: {} })])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText('sans-titre')).toBeInTheDocument()
  })

  it('le dit quand aucun forfait n\'est proposé', async () => {
    servir([])
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText(/Aucun forfait/)).toBeInTheDocument()
  })

  it('le dit quand le chargement échoue, sans page blanche', async () => {
    server.use(http.get('/offers', () => new HttpResponse(null, { status: 500 })))
    renderWithProviders(<ForfaitsPage />)

    expect(await screen.findByText(/n'ont pas pu être chargés/)).toBeInTheDocument()
  })
})
