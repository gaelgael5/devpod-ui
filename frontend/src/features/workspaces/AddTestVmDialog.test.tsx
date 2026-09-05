import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AddTestVmDialog from './AddTestVmDialog'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('AddTestVmDialog', () => {
  it('affiche le titre et le bouton créer désactivé tant que rien n\'est choisi', async () => {
    server.use(
      http.get('/me/test-hypervisors', () =>
        HttpResponse.json([{ name: 'pve2', type: 'proxmox-clone', label: 'Clone' }]),
      ),
    )
    renderWithProviders(<AddTestVmDialog wsName="ws1" open onClose={() => {}} />)

    expect(
      await screen.findByText(/cr.er une vm de test|create a test vm/i),
    ).toBeInTheDocument()
    const createBtn = screen.getByRole('button', { name: /^(créer|create)$/i })
    expect(createBtn).toBeDisabled() // ni hyperviseur ni vmid choisis
  })

  it('affiche un message d\'information quand aucun hyperviseur n\'est paramétré', async () => {
    server.use(
      http.get('/me/test-hypervisors', () => HttpResponse.json([])),
    )
    renderWithProviders(<AddTestVmDialog wsName="ws1" open onClose={() => {}} />)

    expect(
      await screen.findByText(/aucun hyperviseur n.est disponible|no hypervisor is available/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/choisir un hyperviseur|select a hypervisor/i)).toBeNull()
  })

  it('ne rend rien quand open est faux', () => {
    renderWithProviders(<AddTestVmDialog wsName="ws1" open={false} onClose={() => {}} />)
    expect(screen.queryByText(/cr.er une vm de test|create a test vm/i)).toBeNull()
  })
})

describe('AddTestVmDialog — choix du profil', () => {
  /**
   * Le profil decide des parametres de la machine, des recettes installees et
   * des services demarres. Il est type par la spec du script de SON
   * hyperviseur : le backend refuse un profil prevu pour un autre type.
   */
  function renderDialog(profils: unknown[]) {
    server.use(
      http.get('/me/test-hypervisors', () =>
        HttpResponse.json([{ name: 'pve2', type: 'proxmox', label: 'Proxmox' }]),
      ),
      http.get('/me/machine-profiles', () => HttpResponse.json(profils)),
    )
    renderWithProviders(<AddTestVmDialog wsName="ws1" open onClose={() => {}} />)
  }

  const PROXMOX = {
    slug: 'android-test',
    label: 'Machine Android',
    hypervisor_type: 'proxmox',
    recipes: [],
  }
  const AUTRE = {
    slug: 'autre-type',
    label: 'Profil autre type',
    hypervisor_type: 'libvirt',
    recipes: [],
  }

  it('propose les profils disponibles', async () => {
    renderDialog([PROXMOX])

    expect(await screen.findByText(/profil de machine|machine profile/i)).toBeInTheDocument()
  })

  it('ne montre pas le champ quand aucun profil n’existe', async () => {
    // Un selecteur vide n'aide personne : la creation reste possible sans
    // profil, sur les parametres figes du type.
    renderDialog([])

    // Le libelle « hyperviseur » apparait a plusieurs endroits : on attend le
    // selecteur, qui n'existe qu'une fois le chargement fini.
    await screen.findByText(/choisir un hyperviseur|select a hypervisor/i)
    expect(screen.queryByText(/profil de machine|machine profile/i)).toBeNull()
  })

  it('n’affiche que les profils du type de la machine choisie', async () => {
    // Le backend refuse un profil prevu pour un autre type : autant ne pas le
    // proposer.
    renderDialog([PROXMOX, AUTRE])

    await screen.findByText(/profil de machine|machine profile/i)
    // Les deux profils sont charges mais un seul vise 'proxmox'.
    expect(screen.queryByText('Profil autre type')).toBeNull()
  })
})
