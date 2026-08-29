/**
 * Catalogue de facturation : pays, devises, canaux de paiement.
 *
 * Ce que ces tests protegent en priorite : les regles du serveur ne doivent pas
 * etre paraphrasees par l'IHM, elles doivent etre RENDUES. Un canal reference
 * refuse la suppression avec un message qui dit quoi faire — l'ecran l'affiche
 * tel quel, il n'invente pas le sien.
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
import AdminBillingCatalog from './AdminBillingCatalog'

const FRANCE = { code: 'FR', label: 'France', enabled: true }
const STRIPE = {
  slug: 'stripe-eu',
  kind: 'stripe',
  label: 'Stripe Europe',
  tax_mode: 'manuel',
  enabled: true,
  config: {},
  secret_slug: 'billing.stripe-eu.api-key',
}

function renderPage(pays: unknown[] = [FRANCE], canaux: unknown[] = [STRIPE]) {
  server.use(
    http.get('/admin/billing/countries', () => HttpResponse.json(pays)),
    http.get('/admin/billing/providers', () => HttpResponse.json(canaux)),
    http.get('/admin/billing/currencies', () =>
      HttpResponse.json([{ code: 'EUR', enabled: true, is_default: true }]),
    ),
    http.get('/admin/billing/countries/:code/providers', () =>
      HttpResponse.json([{ country_code: 'FR', provider_slug: 'stripe-eu', priority: 0 }]),
    ),
    http.get('/admin/automations/secrets', () => HttpResponse.json([])),
    http.get('/admin/billing/countries/:code/tax-rates', () =>
      HttpResponse.json([
        {
          id: 7,
          country_code: 'FR',
          region: '',
          rate: 0.2,
          label: 'TVA 20 %',
          valid_from: '2026-01-01',
          valid_to: null,
        },
      ]),
    ),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <AdminBillingCatalog />
        <Toaster />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('AdminBillingCatalog', () => {
  it('liste les pays et les canaux de paiement', async () => {
    renderPage()
    expect(await screen.findByTestId('pays-FR')).toHaveTextContent('France')
    expect(await screen.findByTestId('canal-stripe-eu')).toHaveTextContent('Stripe Europe')
  })

  it('affiche le slug du secret, jamais une cle', async () => {
    renderPage()
    const canal = await screen.findByTestId('canal-stripe-eu')
    expect(canal).toHaveTextContent('billing.stripe-eu.api-key')
  })

  it('annonce un catalogue vide plutot qu\'une page muette', async () => {
    renderPage([], [])
    expect(await screen.findByText(i18n.t('admin.billing.countriesEmpty'))).toBeInTheDocument()
    expect(await screen.findByText(i18n.t('admin.billing.providersEmpty'))).toBeInTheDocument()
  })

  it('rend le refus du serveur quand un canal est encore reference', async () => {
    renderPage()
    server.use(
      http.delete('/admin/billing/providers/:slug', () =>
        HttpResponse.json(
          { detail: 'Le canal est référencé par une offre — le désactiver plutôt' },
          { status: 409 },
        ),
      ),
    )
    const canal = await screen.findByTestId('canal-stripe-eu')
    await userEvent.click(within(canal).getByRole('button', { name: i18n.t('admin.billing.deleteProvider') }))
    await waitFor(() => {
      expect(screen.getByText(/référencé par une offre/)).toBeInTheDocument()
    })
  })

  it('ouvre la fiche d\'un pays, qui ne porte plus de devises', async () => {
    renderPage()
    const ligne = await screen.findByTestId('pays-FR')
    await userEvent.click(within(ligne).getByRole('button', { name: i18n.t('admin.billing.editCountry') }))

    const fiche = await screen.findByRole('dialog')
    // Les devises sont globales : la fiche pays n'en parle plus. La recherche
    // est bornee au dialogue — le bloc global, lui, porte bien ce libelle.
    expect(within(fiche).queryByLabelText(i18n.t('admin.billing.addCurrency'))).toBeNull()
  })

  it('gere les devises acceptees dans un bloc a part', async () => {
    renderPage()

    const devise = await screen.findByTestId('devise-EUR')
    expect(devise).toHaveTextContent('EUR')
    expect(within(devise).getByRole('radio')).toBeChecked()
  })

  it('enregistre le jeu de devises entier, defaut compris', async () => {
    renderPage()
    let recu: unknown = null
    server.use(
      http.put('/admin/billing/currencies', async ({ request }) => {
        recu = await request.json()
        return HttpResponse.json(recu)
      }),
    )
    await screen.findByTestId('devise-EUR')

    // La liste est cherchable : on tape, puis on choisit.
    await userEvent.type(screen.getByLabelText(i18n.t('admin.billing.addCurrency')), 'USD')
    await userEvent.click(await screen.findByRole('button', { name: /USD/ }))
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    // Jeu ENTIER : le serveur remplace, il n'applique pas un delta.
    await waitFor(() =>
      expect(recu).toEqual([
        { code: 'EUR', enabled: true, is_default: true },
        { code: 'USD', enabled: true, is_default: false },
      ]),
    )
  })

  it("affiche un taux en vigueur et n'offre que de le clore, jamais de l'editer", async () => {
    renderPage()
    const ligne = await screen.findByTestId('pays-FR')
    await userEvent.click(within(ligne).getByRole('button', { name: i18n.t('admin.billing.editCountry') }))
    const taux = await screen.findByTestId('taux-7')
    expect(taux).toHaveTextContent('20 %')
    expect(taux).toHaveTextContent('TVA 20 %')
    // Cloture possible, edition impossible : le taux n'est pas un champ.
    expect(within(taux).getByRole('button', { name: i18n.t('admin.billing.close') })).toBeInTheDocument()
    expect(within(taux).queryByRole('textbox')).toBeNull()
  })

  it('propose les pays ISO avec leur code et ne repropose pas ceux deja enregistres', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.billing.newCountry') }))

    const champ = await screen.findByLabelText(i18n.t('admin.billing.countryCode'))

    await userEvent.type(champ, 'belg')
    expect(await screen.findByRole('button', { name: /BE/ })).toBeInTheDocument()

    // La France est deja enregistree : la reproposer ferait ecraser sa fiche
    // par un PUT, sans que rien ne le dise.
    await userEvent.clear(champ)
    await userEvent.type(champ, 'france')
    expect(screen.getByText(i18n.t('recherche.aucun'))).toBeInTheDocument()
  })
})
