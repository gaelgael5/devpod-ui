/**
 * L'abonnement, vu par son titulaire : ce qu'il paie, jusqu'à quand, et ce qui
 * s'est passé.
 *
 * Ce que ces tests verrouillent : le forfait courant se lit avec son état et
 * son échéance (le résilié ne se présente pas comme actif), l'historique ne
 * montre que les achats servis par l'API (le filtrage est SERVEUR), et le
 * changement de forfait renvoie vers la page publique — aucune promesse de
 * changement différé tant que la mécanique n'existe pas.
 */
import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AbonnementPage from './AbonnementPage'

const ABO = {
  id: '11111111-1111-1111-1111-111111111111',
  login: 'alice',
  offer_slug: 'standard',
  provider_slug: null,
  state: 'essai',
  country_code: 'FR',
  currency: 'EUR',
  amount_minor: 0,
  provider_subscription_id: '',
  payment_attempts: 0,
  next_retry_at: null,
  trial_end: null,
  current_period_end: null,
  ends_at: '2026-10-05T11:26:00Z',
  state_changed_at: null,
}

const OFFRE = {
  slug: 'standard',
  titles: { fr: 'Standard' },
  descriptions: {},
  hosting_type: 'mutualise',
  max_workspaces: 3,
  max_hosts_dedies: null,
  is_free: true,
  duration_days: 30,
  tacite_reconduction: false,
  une_par_compte: false,
  currency: 'EUR',
  amount_minor: null,
  prices_include_tax: false,
}

function servir({
  abonnements = [ABO],
  historique = [],
  offres = [OFFRE],
}: {
  abonnements?: unknown[]
  historique?: unknown[]
  offres?: unknown[]
} = {}) {
  server.use(
    http.get('/me/subscriptions', () => HttpResponse.json(abonnements)),
    http.get('/me/subscriptions/historique', () => HttpResponse.json(historique)),
    http.get('/offers', () => HttpResponse.json(offres)),
  )
}

beforeEach(async () => {
  await i18n.changeLanguage('fr')
})
afterEach(async () => {
  await i18n.changeLanguage('fr')
})

describe('AbonnementPage', () => {
  it("affiche le forfait courant avec son état, son prix et son échéance", async () => {
    servir()
    renderWithProviders(<AbonnementPage />)

    const carte = await screen.findByTestId('abonnement-11111111-1111-1111-1111-111111111111')
    expect(carte).toHaveTextContent('Standard')
    expect(carte).toHaveTextContent(i18n.t('abonnement.etat.essai'))
    expect(carte).toHaveTextContent(i18n.t('forfaits.free'))
    expect(carte).toHaveTextContent('05/10/2026')
  })

  it('montre le montant réellement payé, pas celui du catalogue', async () => {
    // Le prix de l'abonnement est un INSTANTANÉ pris à la souscription : le
    // catalogue peut avoir changé, l'abonné garde le sien.
    servir({ abonnements: [{ ...ABO, amount_minor: 1200, state: 'actif' }] })
    renderWithProviders(<AbonnementPage />)

    const carte = await screen.findByTestId('abonnement-11111111-1111-1111-1111-111111111111')
    expect(carte).toHaveTextContent('12,00')
    expect(carte).toHaveTextContent(i18n.t('abonnement.etat.actif'))
  })

  it('un abonnement résilié se présente comme tel, pas comme un forfait courant', async () => {
    servir({ abonnements: [{ ...ABO, state: 'resilie' }] })
    renderWithProviders(<AbonnementPage />)

    expect(await screen.findByText(i18n.t('abonnement.etat.resilie'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('abonnement.aucunOuvert'))).toBeInTheDocument()
  })

  it('un résilié propose la reprise — et elle appelle la bonne route', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    let appelee = ''
    servir({ abonnements: [{ ...ABO, state: 'resilie' }] })
    server.use(
      http.post('/me/subscriptions/:id/reprendre', ({ params }) => {
        appelee = String(params.id)
        return HttpResponse.json({ ...ABO, state: 'essai' })
      }),
    )
    renderWithProviders(<AbonnementPage />)

    await userEvent.click(
      await screen.findByRole('button', { name: i18n.t('abonnement.reprendre') }),
    )

    expect(appelee).toBe(ABO.id)
  })

  it("un abonnement ouvert n'offre PAS de bouton de reprise", async () => {
    servir({ abonnements: [{ ...ABO, state: 'actif' }] })
    renderWithProviders(<AbonnementPage />)

    await screen.findByText(i18n.t('abonnement.etat.actif'))
    expect(
      screen.queryByRole('button', { name: i18n.t('abonnement.reprendre') }),
    ).not.toBeInTheDocument()
  })

  it("sans abonnement, la page invite vers les forfaits au lieu d'un écran vide", async () => {
    servir({ abonnements: [] })
    renderWithProviders(<AbonnementPage />)

    expect(await screen.findByText(i18n.t('abonnement.aucunOuvert'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('abonnement.voirForfaits') })).toHaveAttribute(
      'href',
      '/forfaits',
    )
  })

  it("déroule l'historique des achats servi par l'API", async () => {
    servir({
      historique: [
        {
          id: 2,
          kind: 'activation',
          subscription_id: ABO.id,
          provider_slug: 'stripe-fr',
          provider_event_id: 'evt_2',
          visibilite: 'achat',
          occurred_at: '2026-09-05T10:00:00Z',
          created_at: '2026-09-05T10:00:00Z',
          offer_slug: 'standard',
          login: 'alice',
        },
      ],
    })
    renderWithProviders(<AbonnementPage />)

    const journal = await screen.findByTestId('historique-achats')
    expect(within(journal).getByText(i18n.t('abonnement.evenement.activation'))).toBeInTheDocument()
    expect(journal).toHaveTextContent('standard')
    expect(journal).toHaveTextContent('05/09/2026')
  })

  it("sans historique, le dit plutôt qu'un tableau vide", async () => {
    servir()
    renderWithProviders(<AbonnementPage />)

    expect(await screen.findByText(i18n.t('abonnement.historiqueVide'))).toBeInTheDocument()
  })

  it('le changement de forfait renvoie vers la page publique, sans autre promesse', async () => {
    servir()
    renderWithProviders(<AbonnementPage />)

    expect(
      await screen.findByRole('link', { name: i18n.t('abonnement.voirForfaits') }),
    ).toHaveAttribute('href', '/forfaits')
  })
})
