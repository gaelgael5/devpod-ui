/**
 * Offres d'abonnement.
 *
 * Deux comportements que ces tests verrouillent, parce qu'ils decident de la
 * vente : le refus du serveur est RENDU tel quel (une offre souscrite se
 * depublie, elle ne se supprime pas), et les devises sans prix se voient a la
 * saisie — pas dans une page vide cote client.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import { Toaster } from 'sonner'
import i18n from '@/i18n'
import { server } from '@/test/server'
import AdminBillingOffers from './AdminBillingOffers'

const STRIPE = {
  slug: 'stripe-eu',
  kind: 'stripe',
  label: 'Stripe Europe',
  tax_mode: 'manuel',
  enabled: true,
  config: {},
  secret_slug: '',
}

const STANDARD = {
  slug: 'standard',
  label: 'Standard',
  titles: { en: 'Standard plan' },
  descriptions: { en: '## Ce que vous obtenez\n\n- un workspace' },
  hosting_type: 'mutualise',
  max_workspaces: 3,
  max_hosts_dedies: null,
  variables: {},
  provider_slug: 'stripe-eu',
  published: true,
  prices: [{ currency: 'EUR', amount_minor: 1200, provider_price_id: '' }],
  prices_include_tax: false,
  auto_currencies: false,
  currency_markup: 1,
}

function renderPage(offres: unknown[] = [STANDARD]) {
  server.use(
    http.get('/admin/billing/offers', () => HttpResponse.json(offres)),
    http.get('/admin/billing/providers', () => HttpResponse.json([STRIPE])),
    http.get('/admin/billing/currencies', () =>
      HttpResponse.json([
        { code: 'EUR', enabled: true, is_default: true },
        { code: 'USD', enabled: true, is_default: false },
        { code: 'CHF', enabled: false, is_default: false },
      ]),
    ),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <AdminBillingOffers />
        <Toaster />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('AdminBillingOffers', () => {
  it('liste les offres avec leur prix et leur etat de publication', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    expect(offre).toHaveTextContent('Standard')
    expect(offre).toHaveTextContent('12.00 EUR')
    expect(offre).toHaveTextContent(i18n.t('admin.offers.published'))
  })

  it('dit qu\'un quota vide vaut illimite plutot que zero', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    expect(offre).toHaveTextContent(i18n.t('admin.offers.unlimited'))
  })

  it('annonce un catalogue d\'offres vide', async () => {
    renderPage([])
    expect(await screen.findByText(i18n.t('admin.offers.empty'))).toBeInTheDocument()
  })

  it('rend le refus du serveur quand une offre est deja souscrite', async () => {
    renderPage()
    server.use(
      http.delete('/admin/billing/offers/:slug', () =>
        HttpResponse.json(
          { detail: "L'offre est portée par au moins un abonnement — la dépublier plutôt" },
          { status: 409 },
        ),
      ),
    )
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.delete') }))
    await waitFor(() => {
      expect(screen.getByText(/la dépublier plutôt/)).toBeInTheDocument()
    })
  })

  it('montre les devises activees sans prix apres enregistrement', async () => {
    renderPage()
    server.use(
      http.put('/admin/billing/offers/:slug', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, devises_manquantes: ['USD'] })
      }),
    )
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('common.save') }))
    const alerte = await screen.findByTestId('devises-manquantes')
    expect(alerte).toHaveTextContent('USD')
    // La fiche reste ouverte : l'absence doit se corriger la, pas se decouvrir
    // plus tard dans une page cliente vide.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('dit explicitement si les montants sont HT ou TTC', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    // Le sens du montant est un CHOIX, plus une deduction du mode de taxe du
    // canal : une offre peut changer de canal sans changer de nature.
    const ttc = await screen.findByLabelText(i18n.t('admin.offers.pricesIncludeTax'))
    expect(ttc).not.toBeChecked()
    expect(screen.getByText(i18n.t('admin.offers.pricesIncludeTaxOff'))).toBeInTheDocument()
  })

  it('limite les devises a celles que l\'application accepte', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    const devise = (await screen.findByLabelText(
      i18n.t('admin.offers.currency'),
    )) as HTMLSelectElement
    const codes = Array.from(devise.options).map((o) => o.value)
    expect(devise.value).toBe('EUR')
    expect(codes).toContain('USD')
    // CHF est declaree mais desactivee : la proposer produirait une offre
    // invendable, decouverte au paiement.
    expect(codes).not.toContain('CHF')
    // Et surtout : pas tout l'ISO-4217.
    expect(codes).not.toContain('JPY')
  })

  it("explique a quoi sert l'identifiant de prix du provider", async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    expect(await screen.findByText(i18n.t('admin.offers.providerPriceIdHint'))).toBeInTheDocument()
  })

  it("part de l'anglais et ajoute les autres langues a la demande", async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    // EN est toujours la : c'est le repli quand la langue du visiteur manque.
    expect(await screen.findByLabelText(i18n.t('admin.offers.heading'))).toBeInTheDocument()
    expect(screen.queryByText(i18n.t('admin.offers.langue', { lng: 'FR' }))).toBeNull()

    await userEvent.selectOptions(
      screen.getByLabelText(i18n.t('admin.offers.ajouterLangue')),
      'fr',
    )

    expect(screen.getByText(/Langue FR|Language FR/)).toBeInTheDocument()
  })

  it('la description se saisit en markdown, avec apercu', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await screen.findByLabelText(i18n.t('admin.offers.heading'))

    await userEvent.click(screen.getAllByRole('button', { name: i18n.t('markdown.preview') })[0])

    // L'apercu utilise le meme rendu que l'affichage client : un titre markdown
    // devient un vrai titre, pas du texte avec des dieses.
    const apercu = await screen.findByTestId('offre-description-en-apercu')
    expect(within(apercu).getByRole('heading')).toHaveTextContent('Ce que vous obtenez')
  })

  it('la majoration des devises derivees vaut 1 par defaut', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    const auto = await screen.findByLabelText(i18n.t('admin.offers.autoCurrencies'))
    expect(auto).not.toBeChecked()
    await userEvent.click(auto)

    const majoration = screen.getByLabelText(i18n.t('admin.offers.markup')) as HTMLInputElement
    expect(majoration.value).toBe('1')
  })
})
