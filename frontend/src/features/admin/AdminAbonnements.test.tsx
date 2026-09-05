/**
 * La page admin des abonnements : une composition en quatre onglets.
 *
 * Ce qui est verrouillé : l'historique global rend la vue COMPLÈTE — l'entrée
 * d'exploitation est marquée, l'orpheline (webhook jamais rattaché) est
 * visible au lieu de disparaître — et les onglets pas encore cadrés disent
 * qu'ils attendent au lieu de simuler un contrôle.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminAbonnements from './AdminAbonnements'

function servir(historique: unknown[] = []) {
  server.use(
    http.get('/admin/billing/historique', () => HttpResponse.json(historique)),
    // L'onglet Offres embarque l'écran existant : ses appels sont neutralisés.
    http.get('/admin/billing/offers', () => HttpResponse.json([])),
    http.get('/admin/billing/providers', () => HttpResponse.json([])),
    http.get('/admin/billing/currencies', () => HttpResponse.json([])),
    http.get('/admin/host-profiles', () => HttpResponse.json([])),
    // L'onglet Essais embarque son formulaire : la liste des comptes aussi.
    http.get('/admin/users', () => HttpResponse.json([])),
  )
}

const ENTREE = {
  id: 1,
  kind: 'activation',
  subscription_id: '11111111-1111-1111-1111-111111111111',
  provider_slug: 'stripe-fr',
  provider_event_id: 'evt_1',
  visibilite: 'achat',
  occurred_at: '2026-09-05T10:00:00Z',
  created_at: '2026-09-05T10:00:00Z',
  offer_slug: 'standard',
  login: 'alice',
}

async function ouvrirHistorique() {
  await userEvent.click(
    await screen.findByRole('tab', { name: i18n.t('admin.abonnements.tabHistorique') }),
  )
}

describe('AdminAbonnements', () => {
  it('présente les quatre onglets décidés', async () => {
    servir()
    renderWithProviders(<AdminAbonnements />)

    for (const nom of ['tabOffres', 'tabEssais', 'tabRetention', 'tabHistorique'] as const) {
      expect(
        await screen.findByRole('tab', { name: i18n.t(`admin.abonnements.${nom}`) }),
      ).toBeInTheDocument()
    }
  })

  it("déroule l'historique global — compte, événement, offre", async () => {
    servir([ENTREE])
    renderWithProviders(<AdminAbonnements />)
    await ouvrirHistorique()

    const table = await screen.findByTestId('historique-global')
    expect(within(table).getByText('alice')).toBeInTheDocument()
    expect(within(table).getByText(i18n.t('abonnement.evenement.activation'))).toBeInTheDocument()
    expect(within(table).getByText('standard')).toBeInTheDocument()
  })

  it("marque l'entrée d'exploitation — la vue admin est complète, pas celle du client", async () => {
    servir([{ ...ENTREE, visibilite: 'operation', kind: 'debut_essai' }])
    renderWithProviders(<AdminAbonnements />)
    await ouvrirHistorique()

    expect(await screen.findByText(i18n.t('admin.abonnements.operation'))).toBeInTheDocument()
  })

  it("montre l'entrée orpheline au lieu de la faire disparaître", async () => {
    servir([{ ...ENTREE, login: '', subscription_id: null, offer_slug: null }])
    renderWithProviders(<AdminAbonnements />)
    await ouvrirHistorique()

    expect(await screen.findByText(i18n.t('admin.abonnements.orphelin'))).toBeInTheDocument()
  })

  it("le dit quand l'historique est vide", async () => {
    servir([])
    renderWithProviders(<AdminAbonnements />)
    await ouvrirHistorique()

    expect(
      await screen.findByText(i18n.t('admin.abonnements.historiqueVide')),
    ).toBeInTheDocument()
  })

  it("l'onglet pas encore cadré le dit, sans simuler de contrôle", async () => {
    servir()
    renderWithProviders(<AdminAbonnements />)

    await userEvent.click(
      await screen.findByRole('tab', { name: i18n.t('admin.abonnements.tabRetention') }),
    )
    expect(
      await screen.findByText(i18n.t('admin.abonnements.retentionAVenir')),
    ).toBeInTheDocument()
  })

  it("l'onglet Essais porte le formulaire d'octroi", async () => {
    servir()
    renderWithProviders(<AdminAbonnements />)

    await userEvent.click(
      await screen.findByRole('tab', { name: i18n.t('admin.abonnements.tabEssais') }),
    )
    expect(await screen.findByLabelText(i18n.t('admin.essais.offre'))).toBeInTheDocument()
  })
})
