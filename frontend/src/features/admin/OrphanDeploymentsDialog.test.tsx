/**
 * Purge des deploiements dont le noeud a disparu.
 *
 * L'operation supprime des donnees : la liste doit s'afficher AVANT, et le
 * bouton rester inerte quand il n'y a rien a purger.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import OrphanDeploymentsDialog from './OrphanDeploymentsDialog'

const ORPHELIN = {
  uid: 'u1',
  id: 'alloy-devpod',
  template_id: 'alloy-collector',
  template_version: '3',
  node_id: 'host-test-105-2',
  owner_login: 'alice',
  env_values: {},
  host_ports: [],
  status: 'running',
}

function renderDialog(orphelins: unknown[], onPurge?: () => void) {
  server.use(
    http.get('/api/compose/deployments/orphans', () => HttpResponse.json(orphelins)),
    http.delete('/api/compose/deployments/orphans', () => {
      onPurge?.()
      return HttpResponse.json({ purged: orphelins.length, nodes: ['host-test-105-2'] })
    }),
  )
  renderWithProviders(<OrphanDeploymentsDialog open onClose={vi.fn()} />)
}

describe('OrphanDeploymentsDialog', () => {
  it('liste les orphelins avant toute suppression', async () => {
    renderDialog([ORPHELIN])

    expect(await screen.findByText('alloy-devpod')).toBeInTheDocument()
    expect(screen.getByText('host-test-105-2')).toBeInTheDocument()
  })

  it('ne purge pas quand il n’y a rien a purger', async () => {
    renderDialog([])

    expect(await screen.findByText(/aucun d.ploiement orphelin|no orphan deployment/i))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /purger|purge/i })).toBeDisabled()
  })

  it('purge sur confirmation explicite', async () => {
    const purge = vi.fn()
    renderDialog([ORPHELIN], purge)

    await screen.findByText('alloy-devpod')
    await userEvent.click(screen.getByRole('button', { name: /purger \(1\)|purge \(1\)/i }))

    await waitFor(() => expect(purge).toHaveBeenCalledOnce())
  })

  it('ne rend rien tant que le dialogue est ferme', () => {
    renderWithProviders(<OrphanDeploymentsDialog open={false} onClose={vi.fn()} />)

    expect(screen.queryByText(/orphelin|orphan/i)).toBeNull()
  })
})

describe('OrphanDeploymentsDialog — nom de machine reemploye', () => {
  /**
   * Une VM supprimee puis recreee sous le meme nom fait reapparaitre les lignes
   * de l'ancienne. Le backend les distingue par leur date ; l'UI doit les
   * presenter comme les autres orphelins.
   */
  it('liste une ligne anterieure a la machine qui la porte', async () => {
    renderDialog([
      {
        ...ORPHELIN,
        id: 'alloy-devpod',
        node_id: 'host-test-106-1',
        created_at: '2026-07-03T08:54:09Z',
      },
    ])

    expect(await screen.findByText('alloy-devpod')).toBeInTheDocument()
    expect(screen.getByText('host-test-106-1')).toBeInTheDocument()
  })
})
