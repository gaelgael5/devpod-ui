import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostBlock from './TestHostBlock'
import type { TestHost } from './useTestVm'
import type { ComposeDeployment } from '@/features/compose/api/types'

const HOST: TestHost = { alias: 'test1', name: 'host-test-114-1', ip: '192.168.10.160', vmid: '114' }

const DEPLOYMENT: ComposeDeployment = {
  uid: 'uid-1',
  id: 'nginx-demo',
  template_id: 'nginx',
  template_version: '1.0.0',
  node_id: HOST.name,
  owner_login: 'alice',
  env_values: {},
  host_ports: [8080],
  status: 'running',
}

describe('TestHostBlock', () => {
  it("affiche l'alias en avant, le nom et l'IP en secondaire", () => {
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )
    expect(screen.getByText('test1')).toBeInTheDocument()
    expect(screen.getByText(/host-test-114-1.*192\.168\.10\.160/)).toBeInTheDocument()
  })

  it("affiche un message vide quand aucun service ne tourne", () => {
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )
    expect(screen.getByText(/no deployments|aucun déploiement/i)).toBeInTheDocument()
  })

  it('affiche les services docker-compose qui tournent sur le host', () => {
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[DEPLOYMENT]} onOpenSsh={vi.fn()} />
    )
    expect(screen.getByText('nginx-demo')).toBeInTheDocument()
    expect(screen.getByText(/running|en cours/i)).toBeInTheDocument()
  })

  it('ouvre le menu d\'actions et déclenche onOpenSsh', async () => {
    const user = userEvent.setup()
    const onOpenSsh = vi.fn()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={onOpenSsh} />
    )
    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByText(/open ssh session|ouvrir une session ssh/i))
    expect(onOpenSsh).toHaveBeenCalledWith(HOST)
  })

  it('propose la suppression de la machine dans le menu d\'actions', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )
    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByText(/^delete$|^supprimer$/i))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
