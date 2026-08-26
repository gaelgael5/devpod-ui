/**
 * Editeur d'un profil : identite, parametres, recettes, services.
 *
 * Ce qui compte : une recette et un service se choisissent AVEC leurs
 * parametres — c'est au profil qu'on decide la RAM de l'AVD ou le port d'un
 * service, pas a la creation de chaque machine.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { server } from '@/test/server'
import MachineProfileEditor from './MachineProfileEditor'
import { nomDeploiementLibre, slugifier, type MachineProfile } from './useMachineProfiles'

const VIDE: MachineProfile = {
  slug: 'android-test',
  label: 'Machine Android',
  machine_type: 'test',
  hypervisor_type: 'proxmox',
  params: {},
  recipes: [],
  services: [],
}

function renderEditor(profile: MachineProfile = VIDE, args: unknown[] = []) {
  server.use(
    // La spec du script alimente l'onglet Parametres ; sans handler, MSW
    // journalise une requete non interceptee a chaque rendu.
    http.get('/admin/hypervisor-types/:name/script', () =>
      HttpResponse.json({ args, commands: [] }),
    ),
    http.get('/admin/recipes', () =>
      HttpResponse.json([
        {
          id: 'android-emulator',
          key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af',
          version: '1.0.0',
          description: '',
          type: 'install',
          options: { avd_ram: { type: 'string', default: '4096', description: '' } },
        },
      ]),
    ),
    http.get('/api/compose/templates', () =>
      HttpResponse.json([
        {
          id: 'searxng',
          name: 'SearXNG',
          description: '',
          version: '1.0.0',
          compose_content: '',
          tags: [],
          parameters: [{ key: 'PORT', label: 'Port', type: 'string', required: false }],
          source: 'builtin',
          extra_files: {},
        },
      ]),
    ),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <MachineProfileEditor
          profile={profile}
          hypervisorTypes={[{ name: 'proxmox', label: 'Proxmox4vm' }]}
          onClose={vi.fn()}
        />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('slugifier', () => {
  /**
   * Le serveur n'accepte que `^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$`. Deriver le
   * slug du libelle evite d'avoir a l'inventer — et d'echouer a la validation.
   */
  it('met en minuscules et remplace les espaces', () => {
    expect(slugifier('Machine Android')).toBe('machine-android')
  })

  it('retire les accents', () => {
    // Decomposition NFD : la regle vaut pour tout l'alphabet latin, sans table
    // de conversion caractere par caractere.
    expect(slugifier('Éditeur de tests')).toBe('editeur-de-tests')
    expect(slugifier('Café Noël')).toBe('cafe-noel')
  })

  it('condense les separateurs', () => {
    expect(slugifier('a  --  b')).toBe('a-b')
  })

  it('ne laisse pas de tiret aux extremites', () => {
    // La regex du serveur exige une lettre ou un chiffre aux deux bouts.
    expect(slugifier('  Test !  ')).toBe('test')
  })

  it('supprime la ponctuation', () => {
    expect(slugifier("Machine d'Alice (v2)")).toBe('machine-d-alice-v2')
  })

  it('borne la longueur sans finir par un tiret', () => {
    // Tronquer peut laisser un tiret final, que le serveur refuserait.
    const long = slugifier('a'.repeat(38) + ' ' + 'b'.repeat(10))

    expect(long.length).toBeLessThanOrEqual(40)
    expect(long.endsWith('-')).toBe(false)
  })

  it('rend une chaine vide pour un libelle sans caractere utile', () => {
    // A l'appelant de refuser : le bouton d'enregistrement exige un slug.
    expect(slugifier('!!!')).toBe('')
  })
})

describe('nomDeploiementLibre', () => {
  /**
   * Deux deploiements de meme nom sont refuses par le modele — meme repertoire
   * distant, meme projet compose. Autant ne pas les proposer.
   */
  it('garde le nom du template quand il est libre', () => {
    expect(nomDeploiementLibre('searxng', [])).toBe('searxng')
  })

  it('numerote la seconde instance', () => {
    expect(nomDeploiementLibre('searxng', ['searxng'])).toBe('searxng-2')
  })

  it('saute les numeros deja pris', () => {
    expect(nomDeploiementLibre('searxng', ['searxng', 'searxng-2'])).toBe('searxng-3')
  })

  it('ignore les noms d’autres templates', () => {
    expect(nomDeploiementLibre('searxng', ['alloy-collector'])).toBe('searxng')
  })
})

describe('MachineProfileEditor — services', () => {
  it('propose les parametres declares par le template', async () => {
    // Un service se choisit AVEC ses parametres : le port se decide au profil.
    const user = userEvent.setup()
    renderEditor({
      ...VIDE,
      services: [{ template_id: 'searxng', deployment_id: 'searxng', params: {} }],
    })

    await user.click(screen.getByRole('tab', { name: /services/i }))

    const carte = await screen.findByTestId('service-searxng')
    expect(carte).toHaveTextContent('Port')
    expect(carte).toHaveTextContent('SearXNG')
  })

  it('retire un service', async () => {
    const user = userEvent.setup()
    renderEditor({
      ...VIDE,
      services: [{ template_id: 'searxng', deployment_id: 'searxng', params: {} }],
    })

    await user.click(screen.getByRole('tab', { name: /services/i }))
    const carte = await screen.findByTestId('service-searxng')
    await user.click(carte.querySelector('button')!)

    await waitFor(() => expect(screen.queryByTestId('service-searxng')).toBeNull())
  })
})

describe('MachineProfileEditor — recettes', () => {
  it('propose les options declarees par la recette', async () => {
    // Choisir une recette sans pouvoir la parametrer n'aurait pas de sens.
    const user = userEvent.setup()
    renderEditor({
      ...VIDE,
      recipes: [{ key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af', options: {} }],
    })

    await user.click(screen.getByRole('tab', { name: /recettes|recipes/i }))

    expect(await screen.findByText('avd_ram')).toBeInTheDocument()
  })
})

describe('MachineProfileEditor — identite', () => {
  it('interdit de changer le slug d’un profil existant', async () => {
    // Le slug est l'identite : les machines creees en gardent la reference.
    renderEditor()

    const champs = screen.getAllByRole('textbox')
    const slug = champs.find((c) => (c as HTMLInputElement).value === 'android-test')
    expect(slug).toBeDisabled()
  })
})

describe('MachineProfileEditor — slug derive du libelle', () => {
  const VIERGE: MachineProfile = { ...VIDE, slug: '', label: '' }

  it('preremplit le slug pendant la saisie du libelle', async () => {
    const user = userEvent.setup()
    renderEditor(VIERGE)

    const champs = screen.getAllByRole('textbox')
    await user.type(champs[0], 'Machine Android')

    expect((champs[1] as HTMLInputElement).value).toBe('machine-android')
  })

  it('n’ecrase pas un slug saisi a la main', async () => {
    // Sinon la saisie manuelle disparaitrait au caractere suivant du libelle.
    const user = userEvent.setup()
    renderEditor(VIERGE)

    const champs = screen.getAllByRole('textbox')
    await user.type(champs[1], 'mon-slug')
    await user.type(champs[0], 'Autre chose')

    expect((champs[1] as HTMLInputElement).value).toBe('mon-slug')
  })

  it('ne touche pas au slug d’un profil existant', async () => {
    // Le slug est l'identite : les machines creees en gardent la reference.
    const user = userEvent.setup()
    renderEditor()

    const champs = screen.getAllByRole('textbox')
    await user.clear(champs[0])
    await user.type(champs[0], 'Renomme')

    expect((champs[1] as HTMLInputElement).value).toBe('android-test')
  })
})

describe('MachineProfileEditor — valeurs par defaut de la spec', () => {
  /**
   * Un profil s'ouvre sur ce que le script propose. Sans ca les listes fermees
   * (source du template, stockage, type de CPU) s'affichent blanches et le
   * profil s'enregistre sans valeur, alors que la spec en a une utilisable.
   */
  const ARGS = [
    {
      arg: 'NEW_VMID',
      identifier: true,
      label_fr: 'VMID',
      label_en: 'VMID',
      type: 'select',
      options: [{ value: 'auto', label: 'auto' }],
    },
    {
      arg: 'TEMPLATE_VMID',
      label_fr: 'Source template',
      label_en: 'Source template',
      type: 'select',
      default: 'auto',
      options: [{ value: 'auto', label: 'auto (dernier template)' }],
    },
    { arg: 'CI_USER', label_fr: 'Utilisateur', label_en: 'User', type: 'string', default: 'debian' },
  ]

  it('preremplit les champs avec les defauts du script', async () => {
    renderEditor(VIDE, ARGS)

    expect(await screen.findByDisplayValue('debian')).toBeInTheDocument()
    expect(await screen.findByText('auto (dernier template)')).toBeInTheDocument()
  })

  it('ne prerempli pas l’identifiant — le vmid se choisit machine par machine', async () => {
    renderEditor(VIDE, ARGS)

    await screen.findByDisplayValue('debian')
    // `excludeIdentifier` masque le champ ; ce qui compte ici est qu'aucune
    // valeur ne se glisse dans les params du profil.
    expect(screen.queryByText('VMID')).toBeNull()
  })

  it('ne remplace pas une valeur deja enregistree', async () => {
    renderEditor({ ...VIDE, params: { CI_USER: 'alice' } }, ARGS)

    expect(await screen.findByDisplayValue('alice')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('debian')).toBeNull()
  })
})

describe('MachineProfileEditor — libelle du type d’hyperviseur', () => {
  /**
   * Le `name` est une clef technique (« roxmox4vm » pour un slug mal derive) :
   * c'est le libelle qui se lit dans le selecteur.
   */
  it('affiche le libelle, pas le nom technique', async () => {
    renderEditor()

    expect(await screen.findByText('Proxmox4vm')).toBeInTheDocument()
    expect(screen.queryByText('proxmox')).toBeNull()
  })
})

describe('MachineProfileEditor — type de machine', () => {
  /**
   * Un profil ne sert pas qu'aux machines de test : il doit pouvoir decrire une
   * machine qui hebergera des workspaces, ou une machine libre. Radix Select
   * n'ouvre pas sa liste sous jsdom — on verifie donc que chaque valeur est
   * acceptee et rendue avec SON libelle, ce qui couvre le tour complet.
   */
  it.each([
    ['workspaces', /^Workspaces$/],
    ['test', /Machine de test|Test machine/],
    ['ressources', /Ressources partag|Shared resources/],
    ['autres', /^Autres$|^Other$/],
  ] as const)('affiche le libelle du type %s', async (type, libelle) => {
    renderEditor({ ...VIDE, machine_type: type })

    expect(await screen.findByText(libelle)).toBeInTheDocument()
  })
})

describe('MachineProfileEditor — option heritee du workspace', () => {
  /**
   * Ce qui s'injecte au lancement doit se lire AVANT, pas se deviner. Une
   * option qui declare `from:` l'annonce sur son libelle.
   */
  function renderAvecRecette(fromContext: string | null) {
    server.use(
      http.get('/admin/hypervisor-types/:name/script', () =>
        HttpResponse.json({ args: [], commands: [] }),
      ),
      http.get('/api/compose/templates', () => HttpResponse.json([])),
      http.get('/admin/recipes', () =>
        HttpResponse.json([
          {
            id: 'android-emulator',
            key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af',
            version: '1.0.0',
            description: '',
            type: 'install',
            options: {
              repo_url: {
                type: 'string',
                default: '',
                description: '',
                from_context: fromContext,
              },
            },
          },
        ]),
      ),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <MachineProfileEditor
            profile={{
              ...VIDE,
              recipes: [{ key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af', options: {} }],
            }}
            hypervisorTypes={[{ name: 'proxmox', label: 'Proxmox4vm' }]}
            onClose={vi.fn()}
          />
        </I18nextProvider>
      </QueryClientProvider>,
    )
  }

  it('annonce la source de la valeur heritee', async () => {
    renderAvecRecette('workspace.git_url')
    await userEvent.click(await screen.findByRole('tab', { name: /recettes|recipes/i }))

    expect(await screen.findByText(/workspace\.git_url/)).toBeInTheDocument()
  })

  it('n’annonce rien sur une option ordinaire', async () => {
    renderAvecRecette(null)
    await userEvent.click(await screen.findByRole('tab', { name: /recettes|recipes/i }))

    await screen.findByText('repo_url')
    expect(screen.queryByText(/h.rit.|inherited/i)).toBeNull()
  })
})
