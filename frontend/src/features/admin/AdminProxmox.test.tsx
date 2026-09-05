/**
 * Écran Hyperviseurs — les machines portées, ventilées par nature.
 *
 * C'est le contrôle visuel de l'équilibrage : si le provisioning envoie tout
 * sur le même hyperviseur, ça doit se voir ici, pas dans les logs. Ces tests
 * verrouillent les trois exigences de la fiche : des zéros plutôt qu'un vide,
 * la machine jamais sondée ni active ni arrêtée mais VISIBLE, et les machines
 * sans provenance montrées comme telles plutôt qu'attribuées au hasard.
 */
import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminProxmox from './AdminProxmox'

function servir({
  charges,
  sansProvenance = 0,
}: {
  charges: Record<string, object>
  sansProvenance?: number
}) {
  server.use(
    http.get('/admin/hypervisors', () =>
      HttpResponse.json([
        { name: 'pve-a', address: '10.0.0.1', ssh_user: 'root', ssh_port: 22, ssh_key_path: '/k', pve_node: 'pve', hypervisor_type: 'proxmox4vm' },
        { name: 'pve-vide', address: '10.0.0.2', ssh_user: 'root', ssh_port: 22, ssh_key_path: '/k', pve_node: 'pve2', hypervisor_type: 'proxmox4vm' },
      ])),
    http.get('/admin/hypervisor-types', () => HttpResponse.json([])),
    http.get('/admin/hypervisors/:name/actions', () => HttpResponse.json([])),
    http.get('/admin/hypervisors/charges', () =>
      HttpResponse.json({ par_hyperviseur: charges, sans_provenance: sansProvenance })),
  )
}

const PLEIN = { workspaces: 2, tests: 1, ressources: 0, autres: 0, jamais_sondees: 0 }
const ZERO = { workspaces: 0, tests: 0, ressources: 0, autres: 0, jamais_sondees: 0 }

describe('AdminProxmox — machines portées', () => {
  it("affiche les compteurs par nature, et des zéros plutôt qu'un vide", async () => {
    servir({ charges: { 'pve-a': PLEIN, 'pve-vide': ZERO } })
    renderWithProviders(<AdminProxmox />)

    const plein = await screen.findByTestId('charges-pve-a')
    expect(plein).toHaveTextContent('2')
    expect(plein).toHaveTextContent(i18n.t('admin.charges.workspaces'))
    // Un hyperviseur sans machine affiche des zéros : le vide ne dit pas s'il
    // est libre ou si le comptage l'a raté.
    const vide = await screen.findByTestId('charges-pve-vide')
    expect(within(vide).getAllByText(/0/).length).toBeGreaterThan(0)
  })

  it('montre les machines jamais sondées — ni actives, ni arrêtées, mais visibles', async () => {
    servir({ charges: { 'pve-a': { ...PLEIN, jamais_sondees: 3 }, 'pve-vide': ZERO } })
    renderWithProviders(<AdminProxmox />)

    const ligne = await screen.findByTestId('charges-pve-a')
    expect(ligne).toHaveTextContent(i18n.t('admin.charges.jamaisSondees', { count: 3 }))
  })

  it('signale les machines sans provenance au lieu de les attribuer au hasard', async () => {
    servir({ charges: { 'pve-a': PLEIN, 'pve-vide': ZERO }, sansProvenance: 2 })
    renderWithProviders(<AdminProxmox />)

    expect(
      await screen.findByText(i18n.t('admin.charges.sansProvenance', { count: 2 })),
    ).toBeInTheDocument()
  })

  it("ne dit rien des machines sans provenance quand il n'y en a pas", async () => {
    servir({ charges: { 'pve-a': PLEIN, 'pve-vide': ZERO } })
    renderWithProviders(<AdminProxmox />)

    await waitFor(() => expect(screen.getByTestId('charges-pve-a')).toBeInTheDocument())
    expect(
      screen.queryByText(i18n.t('admin.charges.sansProvenance', { count: 0 })),
    ).not.toBeInTheDocument()
  })
})
