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
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import AdminBillingOffers from './AdminBillingOffers'
import OfferEditor from './OfferEditor'

const STRIPE = {
  slug: 'stripe-eu',
  kind: 'stripe',
  label: 'Stripe Europe',
  tax_mode: 'manuel',
  enabled: true,
  config: {},
  secret_slug: '',
}

const PROFILS_HOST = [
  { slug: 'host-standard', label: 'Host standard', machine_profile: 'pve-4g', variables: {} },
  { slug: 'host-gros', label: 'Host gros', machine_profile: 'pve-16g', variables: {} },
]

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
  is_free: false,
  duration_days: 30,
  host_profiles: ['host-standard'],
}

function renderPage(offres: unknown[] = [STANDARD]) {
  server.use(
    http.get('/admin/billing/offers', () => HttpResponse.json(offres)),
    http.get('/admin/billing/providers', () => HttpResponse.json([STRIPE])),
    http.get('/admin/host-profiles', () => HttpResponse.json(PROFILS_HOST)),
    http.get('/admin/billing/currencies', () =>
      HttpResponse.json([
        { code: 'EUR', enabled: true, is_default: true },
        { code: 'USD', enabled: true, is_default: false },
        { code: 'CHF', enabled: false, is_default: false },
      ]),
    ),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // L'editeur est un ECRAN, plus une fenetre modale : le parcours passe donc
  // par le routeur, comme dans l'application.
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter initialEntries={['/admin/billing-offers']}>
          <Routes>
            <Route path="/admin/billing-offers" element={<AdminBillingOffers />} />
            <Route path="/admin/billing-offers/new" element={<OfferEditor />} />
            <Route path="/admin/billing-offers/:slug" element={<OfferEditor />} />
          </Routes>
        </MemoryRouter>
        <Toaster />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

/** Trois onglets depuis le passage en ecran plein : on y va comme l'utilisateur. */
async function ongletTarif() {
  await userEvent.click(await screen.findByRole('tab', { name: i18n.t('admin.offers.tabPricing') }))
}

async function ongletDuree() {
  await userEvent.click(
    await screen.findByRole('tab', { name: i18n.t('admin.offers.tabDuration') }),
  )
}

async function ongletProfils() {
  await userEvent.click(
    await screen.findByRole('tab', { name: i18n.t('admin.offers.tabHostProfiles') }),
  )
}

async function ongletDescription() {
  await userEvent.click(
    await screen.findByRole('tab', { name: i18n.t('admin.offers.tabDescription') }),
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
    // On reste sur l'ecran d'edition : l'absence doit se corriger la, pas se
    // decouvrir plus tard dans une page cliente vide.
    expect(screen.getByRole('button', { name: i18n.t('common.save') })).toBeInTheDocument()
  })

  it('dit explicitement si les montants sont HT ou TTC', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletTarif()

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
    await ongletTarif()

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
    await ongletTarif()

    expect(await screen.findByText(i18n.t('admin.offers.providerPriceIdHint'))).toBeInTheDocument()
  })

  it("part de l'anglais et ajoute les autres langues a la demande", async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletDescription()

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
    await ongletDescription()
    await screen.findByLabelText(i18n.t('admin.offers.heading'))

    await userEvent.click(screen.getAllByRole('button', { name: i18n.t('markdown.preview') })[0])

    // L'apercu utilise le meme rendu que l'affichage client : un titre markdown
    // devient un vrai titre, pas du texte avec des dieses.
    const apercu = await screen.findByTestId('offre-description-en-apercu')
    expect(within(apercu).getByRole('heading')).toHaveTextContent('Ce que vous obtenez')
  })

  it("ouvre l'edition en ecran plein, pas dans une fenetre modale", async () => {
    // Une offre se saisit en plusieurs minutes, avec un editeur markdown par
    // langue : une modale imposait un ascenseur dans un ascenseur.
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.offers.new') }))

    expect(await screen.findByLabelText(i18n.t('admin.offers.shortName'))).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('separe identite, textes et tarif en trois onglets', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.offers.new') }))

    // Onglet « General » d'abord : l'identite et les droits, aucun texte client.
    expect(await screen.findByLabelText(i18n.t('admin.offers.shortName'))).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('admin.offers.maxWorkspaces'))).toBeInTheDocument()
    expect(screen.queryByLabelText(i18n.t('admin.offers.heading'))).toBeNull()
    expect(screen.queryByLabelText(i18n.t('admin.offers.pricesIncludeTax'))).toBeNull()

    await ongletDescription()

    expect(await screen.findByLabelText(i18n.t('admin.offers.heading'))).toBeInTheDocument()
    expect(screen.queryByLabelText(i18n.t('admin.offers.shortName'))).toBeNull()

    await ongletTarif()

    expect(await screen.findByLabelText(i18n.t('admin.offers.pricesIncludeTax'))).toBeInTheDocument()
    expect(screen.queryByLabelText(i18n.t('admin.offers.heading'))).toBeNull()
  })

  it("ramene sur l'onglet General quand le nom court manque", async () => {
    // Onglet inactif = contenu demonte : le navigateur ne valide plus ses
    // champs requis. Sans ce garde-fou, on partirait au serveur sans nom et
    // rien ne designerait le champ fautif.
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.offers.new') }))
    await ongletTarif()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(
      await screen.findByText(i18n.t('admin.offers.champsManquantsGeneral')),
    ).toBeInTheDocument()
    expect(await screen.findByLabelText(i18n.t('admin.offers.shortName'))).toBeInTheDocument()
  })

  it("ramene sur l'onglet Description quand le titre anglais manque", async () => {
    // Le refus doit designer le BON onglet : renvoyer sur l'identite quand
    // c'est le titre qui manque ferait chercher au mauvais endroit.
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.offers.new') }))
    await userEvent.type(screen.getByLabelText(i18n.t('admin.offers.shortName')), 'Welcome')
    await ongletTarif()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(
      await screen.findByText(i18n.t('admin.offers.champsManquantsDescription')),
    ).toBeInTheDocument()
    expect(await screen.findByLabelText(i18n.t('admin.offers.heading'))).toBeInTheDocument()
  })

  it("rend l'onglet Tarif sans objet quand l'offre est gratuite", async () => {
    // Un forfait de bienvenue n'a pas de prix : laisser la grille de tarifs
    // ferait saisir un montant qui ne serait jamais encaisse.
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.offers.new') }))
    await ongletTarif()

    expect(
      await screen.findByRole('button', { name: i18n.t('admin.offers.addPrice') }),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText(i18n.t('admin.offers.isFree')))

    expect(screen.getByText(i18n.t('admin.offers.freeNoPricing'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('admin.offers.addPrice') })).toBeNull()
  })

  it('porte la duree du forfait dans son propre onglet', async () => {
    let envoye: Record<string, unknown> = {}
    server.use(
      http.put('/admin/billing/offers/:slug', async ({ request }) => {
        envoye = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...envoye, devises_manquantes: [] })
      }),
    )
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletDuree()

    const duree = await screen.findByLabelText(i18n.t('admin.offers.duration'))
    expect(duree).toHaveValue(30)

    await userEvent.clear(duree)
    await userEvent.type(duree, '14')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    await waitFor(() => expect(envoye.duration_days).toBe(14))
  })

  it("ramene sur l'onglet Duree quand on publie sans terme", async () => {
    // Le refus doit designer l'onglet : sans duree, le serveur rendrait un 422
    // et rien ne dirait ou corriger.
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletDuree()
    await userEvent.clear(screen.getByLabelText(i18n.t('admin.offers.duration')))

    // « Standard » est deja publiee : on ne retouche pas la case, on enregistre.
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(
      await screen.findByText(i18n.t('admin.offers.champsManquantsDuree')),
    ).toBeInTheDocument()
    expect(await screen.findByLabelText(i18n.t('admin.offers.duration'))).toBeInTheDocument()
  })

  it('la majoration des devises derivees vaut 1 par defaut', async () => {
    renderPage()
    const offre = await screen.findByTestId('offre-standard')
    await userEvent.click(within(offre).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletTarif()

    const auto = await screen.findByLabelText(i18n.t('admin.offers.autoCurrencies'))
    expect(auto).not.toBeChecked()
    await userEvent.click(auto)

    const majoration = screen.getByLabelText(i18n.t('admin.offers.markup')) as HTMLInputElement
    expect(majoration.value).toBe('1')
  })
})

describe('OfferEditor — profils de host', () => {
  async function ouvrirProfils(offre: Record<string, unknown>) {
    renderPage([{ ...STANDARD, ...offre }])
    const ligne = await screen.findByTestId('offre-standard')
    await userEvent.click(within(ligne).getByRole('button', { name: i18n.t('admin.offers.edit') }))
    await ongletProfils()
  }

  it("liste les profils de l'offre dans leur ordre de priorite", async () => {
    await ouvrirProfils({ host_profiles: ['host-gros', 'host-standard'] })

    const lignes = await screen.findAllByTestId(/^profil-host-/)
    expect(lignes.map((l) => l.getAttribute('data-testid'))).toEqual([
      'profil-host-host-gros',
      'profil-host-host-standard',
    ])
    // Le rang est montre : sans lui, rien ne dit que l'ordre a un sens.
    expect(lignes[0]).toHaveTextContent('1')
    expect(lignes[1]).toHaveTextContent('2')
  })

  it('remonte un profil dans la priorite', async () => {
    await ouvrirProfils({ host_profiles: ['host-standard', 'host-gros'] })

    await userEvent.click(
      within(screen.getByTestId('profil-host-host-gros')).getByRole('button', {
        name: i18n.t('admin.offers.hostProfileUp'),
      }),
    )

    const lignes = await screen.findAllByTestId(/^profil-host-/)
    expect(lignes.map((l) => l.getAttribute('data-testid'))).toEqual([
      'profil-host-host-gros',
      'profil-host-host-standard',
    ])
  })

  it('ne propose pas deux fois un profil deja choisi', async () => {
    await ouvrirProfils({ host_profiles: ['host-standard'] })

    const choix = await screen.findByTestId('ajout-profil-host')
    const proposes = within(choix)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value)
      .filter(Boolean)
    expect(proposes).toEqual(['host-gros'])
  })

  it('envoie les profils dans leur ordre de priorite', async () => {
    let envoye: Record<string, unknown> = {}
    server.use(
      http.put('/admin/billing/offers/:slug', async ({ request }) => {
        envoye = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...envoye, devises_manquantes: [] })
      }),
    )
    await ouvrirProfils({ host_profiles: ['host-standard'] })

    await userEvent.selectOptions(await screen.findByTestId('ajout-profil-host'), 'host-gros')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    await waitFor(() => expect(envoye.host_profiles).toEqual(['host-standard', 'host-gros']))
  })

  it("ramene sur l'onglet quand on publie sans aucun profil", async () => {
    // Le refus doit designer l'onglet : sans profil, le serveur rendrait un 422
    // et rien ne dirait ou corriger.
    await ouvrirProfils({ host_profiles: [] })

    // « Standard » est deja publiee : on ne retouche pas la case, on enregistre.
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(
      await screen.findByText(i18n.t('admin.offers.champsManquantsProfils')),
    ).toBeInTheDocument()
  })
})
