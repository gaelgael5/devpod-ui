/**
 * Profils de host : ce qu'un forfait provisionne.
 *
 * Le profil de machine sait construire la VM ; il ne sait pas combien de
 * workspaces elle tient sans planter. C'est ce que le profil de host ajoute.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { server } from '@/test/server'
import AdminHostProfiles from './AdminHostProfiles'

const MACHINE = {
  slug: 'host-workspace-standard',
  label: 'Host workspace standard',
  machine_type: 'workspaces',
  hypervisor_type: 'proxmox4vm',
  params: {},
  recipes: [],
  services: [],
}

const VARIABLES = [
  { label: 'Capacité en workspaces', slug: 'capacity_workspaces', type: 'int' },
  { label: 'Zone', slug: 'zone', type: 'string' },
]

const PROFIL = {
  slug: 'ws-standard',
  label: 'Workspaces standard',
  machine_profile: 'host-workspace-standard',
  variables: { capacity_workspaces: '8' },
}

function renderPage(profils: unknown[] = [PROFIL], machines: unknown[] = [MACHINE]) {
  server.use(
    http.get('/admin/host-profiles', () => HttpResponse.json(profils)),
    http.get('/admin/machine-profiles', () => HttpResponse.json(machines)),
    http.get('/admin/host-profiles/variables/:slug', () => HttpResponse.json(VARIABLES)),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <AdminHostProfiles />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

describe('AdminHostProfiles', () => {
  it('liste les profils de host', async () => {
    renderPage()

    expect(await screen.findByText('Workspaces standard')).toBeInTheDocument()
    expect(screen.getByText('host-workspace-standard')).toBeInTheDocument()
  })

  it('affiche la capacité déclarée sur la vignette', async () => {
    // C'est le chiffre qui compte : combien de workspaces la machine tient.
    renderPage()

    expect(await screen.findByText(/8 workspace/)).toBeInTheDocument()
  })

  it("n'affiche pas de capacité quand elle n'est pas renseignée", async () => {
    renderPage([{ ...PROFIL, variables: {} }])

    await screen.findByText('Workspaces standard')
    expect(screen.queryByText(/workspace\(s\)/)).not.toBeInTheDocument()
  })

  it('construit le formulaire à partir des variables déclarées par le type', async () => {
    // Rien n'est fige dans le code : le type d'hyperviseur dit ce qui existe.
    renderPage()
    await userEvent.click(await screen.findByLabelText('Edit'))

    expect(await screen.findByLabelText(/Capacité en workspaces/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Zone/)).toBeInTheDocument()
  })

  it('rend la capacité obligatoire', async () => {
    // Laisser vide veut dire « non renseignee », pas « illimitee ».
    renderPage()
    await userEvent.click(await screen.findByLabelText('Edit'))

    expect(await screen.findByLabelText(/Capacité en workspaces/)).toBeRequired()
    expect(screen.getByLabelText(/Zone/)).not.toBeRequired()
  })

  it('enregistre les valeurs saisies', async () => {
    const recu = vi.fn()
    server.use(
      http.put('/admin/host-profiles/:slug', async ({ request }) => {
        recu(await request.json())
        return HttpResponse.json(PROFIL)
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByLabelText('Edit'))
    const zone = await screen.findByLabelText(/Zone/)
    await userEvent.type(zone, 'pve2')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))

    await waitFor(() =>
      expect(recu).toHaveBeenCalledWith(
        expect.objectContaining({ variables: { capacity_workspaces: '8', zone: 'pve2' } }),
      ),
    )
  })

  it('refuse de créer un profil sans profil de machine', async () => {
    // Sans profil de machine il n'y a ni type ni variables : le formulaire
    // serait vide et le profil inapplicable.
    renderPage([], [])
    await userEvent.click(await screen.findByRole('button', { name: /New host profile/ }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it("affiche le refus du serveur au lieu de « aucune variable »", async () => {
    // Cas reel : un profil de machine vise un type d'hyperviseur qui n'existe
    // plus (nom renomme, faute de frappe). Le serveur le DIT en 422 ; l'ecran
    // affichait « ce type ne declare aucune variable » et l'admin cherchait la
    // panne du mauvais cote.
    renderPage()
    server.use(
      http.get('/admin/host-profiles/variables/:slug', () =>
        HttpResponse.json(
          {
            detail:
              "Le profil de machine 'host-workspace-standard' vise le type 'proxmox4vm', qui n'existe plus",
          },
          { status: 422 },
        ),
      ),
    )
    await userEvent.click(await screen.findByRole('button', { name: /New host profile/ }))

    const erreur = await screen.findByTestId('variables-erreur')
    expect(erreur).toHaveTextContent(/qui n'existe plus/)
  })
})
