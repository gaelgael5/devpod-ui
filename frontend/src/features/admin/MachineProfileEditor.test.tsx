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
import { nomDeploiementLibre, type MachineProfile } from './useMachineProfiles'

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
