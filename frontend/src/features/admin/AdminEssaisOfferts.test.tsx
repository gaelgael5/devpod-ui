/**
 * Le formulaire d'octroi d'essais gratuits.
 *
 * Ce qui est verrouillé : le bouton reste inerte tant que le geste est
 * incomplet (forfait + bénéficiaires), l'appel part en LOT avec la fin choisie,
 * et la réponse s'affiche compte par compte — un refus montre son MOTIF au lieu
 * de cacher les essais accordés du même envoi.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminEssaisOfferts from './AdminEssaisOfferts'

const OFFRE = {
  slug: 'standard',
  label: 'Standard',
  titles: {},
  descriptions: {},
  hosting_type: 'mutualise',
  tacite_reconduction: false,
  une_par_compte: false,
  priorite: 100,
  max_workspaces: null,
  max_hosts_dedies: null,
  variables: {},
  provider_slug: null,
  published: true,
  prices: [],
  prices_include_tax: false,
  auto_currencies: false,
  currency_markup: '1',
  is_free: false,
  duration_days: 30,
  host_profiles: [],
}

const COMPTES = [
  { login: 'bob', email: 'bob@x.org', display_name: 'Bob', termix_instance_ids: [] },
  { login: 'alice', email: 'alice@x.org', display_name: 'Alice', termix_instance_ids: [] },
]

function servir(reponse?: unknown) {
  server.use(
    http.get('/admin/billing/offers', () => HttpResponse.json([OFFRE])),
    http.get('/admin/users', () => HttpResponse.json(COMPTES)),
    http.post('/admin/billing/essais', async ({ request }) => {
      corpsEnvoye = await request.json()
      return HttpResponse.json(
        reponse ?? {
          resultats: [
            { login: 'bob', accorde: true, motif: '', subscription_id: 'sub-1' },
            {
              login: 'alice',
              accorde: false,
              motif: "Ce compte a déjà bénéficié d'un essai offert sur cette offre.",
              subscription_id: null,
            },
          ],
        },
      )
    }),
  )
}

let corpsEnvoye: unknown

async function remplir() {
  // Les options arrivent en asynchrone : attendre celle de l'offre avant de choisir.
  await screen.findByRole('option', { name: /Standard/ })
  await userEvent.selectOptions(screen.getByLabelText(i18n.t('admin.essais.offre')), 'standard')
  await userEvent.click(await screen.findByText('bob'))
  await userEvent.click(screen.getByText('alice'))
}

describe('AdminEssaisOfferts', () => {
  it("le bouton reste inerte tant que le geste est incomplet", async () => {
    servir()
    renderWithProviders(<AdminEssaisOfferts />)

    const bouton = await screen.findByRole('button', {
      name: i18n.t('admin.essais.offrir', { count: 0 }),
    })
    expect(bouton).toBeDisabled()
  })

  it("envoie le lot — forfait, bénéficiaires, fin choisie", async () => {
    servir()
    renderWithProviders(<AdminEssaisOfferts />)
    await remplir()

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('admin.essais.offrir', { count: 2 }) }),
    )

    const corps = corpsEnvoye as { offer_slug: string; logins: string[]; fin: string }
    expect(corps.offer_slug).toBe('standard')
    expect(corps.logins.sort()).toEqual(['alice', 'bob'])
    // La fin envoyée couvre le jour choisi : fin de journée, pas premier instant.
    expect(corps.fin).toMatch(/T23:59:00Z$/)
  })

  it('affiche la réponse compte par compte — le refus porte son motif', async () => {
    servir()
    renderWithProviders(<AdminEssaisOfferts />)
    await remplir()

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('admin.essais.offrir', { count: 2 }) }),
    )

    const liste = await screen.findByTestId('essais-resultats')
    expect(within(liste).getByText(i18n.t('admin.essais.accorde'))).toBeInTheDocument()
    expect(
      within(liste).getByText("Ce compte a déjà bénéficié d'un essai offert sur cette offre."),
    ).toBeInTheDocument()
  })

  it('filtre les comptes sans perdre la sélection', async () => {
    servir()
    renderWithProviders(<AdminEssaisOfferts />)
    await userEvent.click(await screen.findByText('bob'))

    await userEvent.type(screen.getByPlaceholderText(i18n.t('admin.essais.filtrer')), 'alice')

    expect(screen.queryByText('bob')).not.toBeInTheDocument()
    // Le compteur de sélection tient toujours bob, masqué par le filtre.
    expect(
      screen.getByText(i18n.t('admin.essais.beneficiaires', { count: 1 })),
    ).toBeInTheDocument()
  })
})
