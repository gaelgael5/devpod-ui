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
