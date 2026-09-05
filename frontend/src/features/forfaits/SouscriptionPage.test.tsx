import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import SouscriptionPage from './SouscriptionPage'
import type { OffrePubliee } from './useOffresPubliques'

const OFFRE: OffrePubliee = {
  slug: 'standard',
  titles: { fr: 'Standard' },
  descriptions: { fr: 'Pour commencer' },
  hosting_type: 'mutualise',
  max_workspaces: 3,
  max_hosts_dedies: null,
  is_free: false,
  duration_days: 30,
  tacite_reconduction: false,
  une_par_compte: false,
  currency: 'EUR',
  amount_minor: 1200,
  prices_include_tax: true,
}

const CONTEXTE = {
  pays_devine: 'BE',
  pays: [
    { code: 'FR', label: 'France' },
    { code: 'BE', label: 'Belgique' },
  ],
  devise_par_defaut: 'EUR',
  devises: ['EUR', 'USD'],
}

/** Corps recus par le POST, pour verifier CE QUI part reellement. */
let envois: Record<string, unknown>[] = []

function servir(options: { contexte?: object; refus?: string } = {}) {
  envois = []
  server.use(
    http.get('/offers', () => HttpResponse.json([OFFRE])),
    http.get('/me/subscriptions/contexte', () =>
      HttpResponse.json(options.contexte ?? CONTEXTE),
    ),
    http.post('/me/subscriptions', async ({ request }) => {
      envois.push((await request.json()) as Record<string, unknown>)
      if (options.refus) {
        return HttpResponse.json({ detail: options.refus }, { status: 409 })
      }
      return HttpResponse.json({ id: 'abo-1', offer_slug: 'standard' }, { status: 201 })
    }),
  )
}

beforeEach(async () => {
  await i18n.changeLanguage('fr')
})
afterEach(async () => {
  await i18n.changeLanguage('fr')
})

/** La page lit son slug dans l'URL. */
function afficher() {
  return renderWithProviders(<SouscriptionPage />, {
    route: '/forfaits/standard',
    path: '/forfaits/:slug',
  })
}

describe('SouscriptionPage', () => {
  it("n'envoie rien tant que l'engagement n'est pas confirmé", async () => {
    servir()
    afficher()

    const bouton = await screen.findByRole('button', { name: 'Souscrire' })

    // L'engagement doit être un geste, pas la conséquence d'un clic mal placé.
    expect(bouton).toBeDisabled()
  })

  it('souscrit une fois la case cochée', async () => {
    servir()
    afficher()

    await userEvent.click(await screen.findByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Souscrire' }))

    expect(await screen.findByText(/forfait est enregistré/)).toBeInTheDocument()
    expect(envois).toHaveLength(1)
  })

  it('pré-remplit le pays déduit de la connexion, sans l’imposer', async () => {
    servir()
    afficher()

    // Déduction = BE. Elle propose ; l'utilisateur corrige en FR.
    const selectPays = await screen.findByDisplayValue('Belgique')
    await userEvent.selectOptions(selectPays, 'FR')
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Souscrire' }))

    await screen.findByText(/forfait est enregistré/)
    expect(envois[0].country_code).toBe('FR')
  })

  it('retombe sur le premier pays quand la déduction ne dit rien', async () => {
    // Derrière un proxy qui ne transmet pas l'en-tête : on ne devine pas.
    servir({ contexte: { ...CONTEXTE, pays_devine: null } })
    afficher()

    expect(await screen.findByDisplayValue('France')).toBeInTheDocument()
  })

  it('part avec la devise par défaut, modifiable', async () => {
    servir()
    afficher()

    await userEvent.selectOptions(await screen.findByDisplayValue('EUR'), 'USD')
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Souscrire' }))

    await screen.findByText(/forfait est enregistré/)
    expect(envois[0].currency).toBe('USD')
  })

  it('affiche le refus du serveur tel quel', async () => {
    // Le message est rédigé pour être lu : le remplacer par « une erreur est
    // survenue » priverait le client de la seule information utile.
    servir({ refus: 'Vous avez déjà souscrit cette offre : elle est limitée à une par compte.' })
    afficher()

    await userEvent.click(await screen.findByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Souscrire' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/une par compte/)
  })

  it('dit ce qui advient au terme, avant de s’engager', async () => {
    servir()
    afficher()

    expect(await screen.findByText(/S'arrête au terme/)).toBeInTheDocument()
  })

  it("ne promet pas une sortie qui n'existe pas encore", async () => {
    // La résiliation est en étape 8. Tant qu'elle n'est pas là, la page se tait
    // plutôt que d'annoncer « sans engagement ».
    servir()
    afficher()

    await screen.findByRole('checkbox')
    expect(screen.queryByText(/sans engagement/i)).not.toBeInTheDocument()
  })

  it('le dit quand le forfait n’existe pas', async () => {
    servir()
    renderWithProviders(<SouscriptionPage />, {
      route: '/forfaits/fantome',
      path: '/forfaits/:slug',
    })

    expect(await screen.findByText(/n'existe pas ou n'est plus proposé/)).toBeInTheDocument()
  })
})
