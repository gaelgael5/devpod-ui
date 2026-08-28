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
  labels: { fr: 'Standard', en: 'Standard' },
  descriptions: {},
  hosting_type: 'mutualise',
  max_workspaces: 3,
  max_hosts_dedies: null,
  variables: {},
  provider_slug: 'stripe-eu',
  published: true,
  prices: [{ currency: 'EUR', amount_minor: 1200, provider_price_id: '' }],
}

function renderPage(offres: unknown[] = [STANDARD]) {
  server.use(
    http.get('/admin/billing/offers', () => HttpResponse.json(offres)),
    http.get('/admin/billing/providers', () => HttpResponse.json([STRIPE])),
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

  it('dit si le montant saisi est HT ou TTC selon le canal', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    expect(await screen.findByText(i18n.t('admin.offers.priceMeaning.manuel'))).toBeInTheDocument()
  })

  it('choisit la devise dans une liste ISO, jamais en texte libre', async () => {
    // Saisir « 15 » dans la case devise etait possible, et rien ne le disait :
    // le premier champ attend un code ISO, pas un montant.
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    const devise = (await screen.findByLabelText(
      i18n.t('admin.offers.currency'),
    )) as HTMLSelectElement
    expect(devise.tagName).toBe('SELECT')
    expect(devise.value).toBe('EUR')
    expect(Array.from(devise.options).map((o) => o.value)).toContain('USD')
  })

  it("explique a quoi sert l'identifiant de prix du provider", async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))

    expect(await screen.findByText(i18n.t('admin.offers.providerPriceIdHint'))).toBeInTheDocument()
  })
})
