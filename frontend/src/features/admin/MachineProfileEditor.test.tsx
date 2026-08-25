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

function renderEditor(profile: MachineProfile = VIDE) {
  server.use(
    // La spec du script alimente l'onglet Parametres ; sans handler, MSW
    // journalise une requete non interceptee a chaque rendu.
    http.get('/admin/hypervisor-types/:name/script', () =>
      HttpResponse.json({ args: [], commands: [] }),
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
          hypervisorTypes={['proxmox']}
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
