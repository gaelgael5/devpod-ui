/**
 * Page de gestion des profils de machine.
 *
 * Elle remplace le bouton « Test host config », qui n'offrait qu'UN seul jeu de
 * parametres par type d'hyperviseur.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { server } from '@/test/server'
import AdminMachineProfiles from './AdminMachineProfiles'

const PROFIL = {
  slug: 'android-test',
  label: 'Machine Android',
  machine_type: 'test',
  hypervisor_type: 'proxmox',
  params: { MEMORY: '8192' },
  recipes: [{ key: 'fe46f7ec-33f7-4252-b29c-cf224b8cd1af', options: { avd_ram: '8192' } }],
  services: [],
}

function renderPage(profils: unknown[] = [PROFIL]) {
  server.use(
    http.get('/admin/machine-profiles', () => HttpResponse.json(profils)),
    http.get('/admin/hypervisor-types', () =>
      HttpResponse.json([{ name: 'proxmox', label: 'Proxmox', add_script: '', destroy_script: '' }]),
    ),
    http.get('/admin/recipes', () => HttpResponse.json([])),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <AdminMachineProfiles />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('AdminMachineProfiles', () => {
  it('liste les profils avec leur type de machine', async () => {
    renderPage()

    expect(await screen.findByTestId('profil-android-test')).toBeInTheDocument()
    expect(screen.getByText('Machine Android')).toBeInTheDocument()
  })

  it('montre ce que le profil embarque', async () => {
    // Le nombre de recettes et de services dit d'un coup d'oeil ce que la
    // machine aura, sans ouvrir l'editeur.
    renderPage()

    const carte = await screen.findByTestId('profil-android-test')
    expect(carte).toHaveTextContent(/1/)
    expect(carte).toHaveTextContent('proxmox')
  })

  it('le dit quand aucun profil n’existe', async () => {
    // Sans profil, aucune machine de test ne peut etre creee : une liste vide
    // sans explication ressemble a une panne.
    renderPage([])

    expect(await screen.findByText(/aucun profil|no profile/i)).toBeInTheDocument()
  })

  it('supprime un profil', async () => {
    const user = userEvent.setup()
    let supprime: string | null = null
    renderPage()
    server.use(
      http.delete('/admin/machine-profiles/:slug', ({ params }) => {
        supprime = String(params.slug)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await screen.findByTestId('profil-android-test')

    const boutons = screen.getAllByRole('button')
    await user.click(boutons[boutons.length - 1])

    await waitFor(() => expect(supprime).toBe('android-test'))
  })

  it('refuse de créer un profil sans type d’hyperviseur', async () => {
    // Les parametres d'un profil sont types par la spec du script de son type :
    // sans type, le formulaire n'a rien a afficher.
    const user = userEvent.setup()
    server.use(
      http.get('/admin/machine-profiles', () => HttpResponse.json([])),
      http.get('/admin/hypervisor-types', () => HttpResponse.json([])),
      http.get('/admin/recipes', () => HttpResponse.json([])),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <AdminMachineProfiles />
        </I18nextProvider>
      </QueryClientProvider>,
    )
    await screen.findByText(/aucun profil|no profile/i)

    await user.click(screen.getByRole('button', { name: /nouveau profil|new profile/i }))

    // Pas d'editeur ouvert : le dialog n'apparait pas.
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
