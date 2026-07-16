import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeAll, describe, expect, it, beforeEach, vi } from 'vitest'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminHosts from './AdminHosts'

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(function Terminal() {
    return {
      open: vi.fn(), dispose: vi.fn(),
      onData: vi.fn(() => ({ dispose: vi.fn() })),
      write: vi.fn(), loadAddon: vi.fn(), focus: vi.fn(),
    }
  }),
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function FitAddon() {
    return { fit: vi.fn(), dispose: vi.fn() }
  }),
}))

// jsdom ne supporte pas hasPointerCapture/scrollIntoView (utilisés par Radix Select).
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('AdminHosts', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'], is_admin: true } })
  })

  it('affiche le titre', () => {
    renderWithProviders(<AdminHosts />)
    expect(screen.getByRole('heading', { name: /hosts|hôtes/i })).toBeInTheDocument()
  })

  it('affiche les hosts chargés', async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => {
      expect(screen.getByText('pve1')).toBeInTheDocument()
      expect(screen.getByText('pve2')).toBeInTheDocument()
    })
  })

  it("n'affiche pas le bouton SSH sur une ligne docker-tls", async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    const rows = screen.getAllByRole('row')
    const pve1Row = rows.find(r => r.textContent?.includes('pve1'))
    expect(pve1Row).toBeDefined()
    expect(pve1Row!.querySelector('[data-ssh]')).toBeNull()
  })

  it('affiche le bouton SSH sur une ligne ssh et ouvre un onglet terminal au clic', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('ssh-dev')).toBeInTheDocument())
    const sshBtn = screen.getByRole('button', { name: /^SSH$/i })
    expect(sshBtn).toBeInTheDocument()
    await userEvent.click(sshBtn)
    // Ouverture en onglet (plus de fenêtre flottante) vers le terminal host.
    expect(open).toHaveBeenCalledWith(
      '/terminal?ws=%2Fadmin%2Fhosts%2Fssh-dev%2Fssh&title=ssh-dev',
      '_blank',
      'noopener',
    )
    open.mockRestore()
  })

  it("affiche la section hosts ressources vide quand aucun host n'a usage=ressources", async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    expect(screen.getByText(/resource hosts|hosts ressources/i)).toBeInTheDocument()
    expect(screen.getByText(/no resource host|aucun host ressource/i)).toBeInTheDocument()
  })

  it('liste un host usage=ressources dans sa propre section avec ses services', async () => {
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([
          { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376', usage: 'workspaces' },
          { name: 'sonarqube-host', type: 'ssh', default: false, address: 'debian@192.168.10.180', host_cert_slug: 'hosts/sonarqube_ed25519', usage: 'ressources' },
        ])),
      http.get('/api/compose/deployments', () =>
        HttpResponse.json([
          { uid: 'uid-1', id: 'sonarqube', template_id: 'sonarqube', template_version: '1.0.0', node_id: 'sonarqube-host', owner_login: 'admin', env_values: {}, host_ports: [9000], status: 'running' },
        ])),
    )
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('sonarqube-host')).toBeInTheDocument())
    expect(await screen.findByText('sonarqube')).toBeInTheDocument()
    expect(screen.getByText(/running|en cours/i)).toBeInTheDocument()
    expect(screen.queryByText(/no resource host|aucun host ressource/i)).not.toBeInTheDocument()
  })

  it("propose la destination dans le formulaire d'ajout d'host", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /add host|ajouter un h[oô]te/i }))
    expect(await screen.findByText(/^purpose$|^destination$/i)).toBeInTheDocument()
  })

  it('propose le certificat mTLS (certs tls-* uniquement) pour un host docker-tls', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /add host|ajouter un h[oô]te/i }))

    // Type par défaut = docker-tls → le sélecteur de cert est visible.
    expect(await screen.findByText(/mtls certificate|certificat mtls/i)).toBeInTheDocument()

    // Ouvrir le select : le cert tls-* est listé, le cert ssh non.
    const selects = screen.getAllByRole('combobox')
    const certSelect = selects.find((s) =>
      s.textContent?.match(/shared portal certificate|certificat partagé du portail/i))
    expect(certSelect).toBeDefined()
    await user.click(certSelect!)
    // Radix rend l'item + une <option> native miroir → findAll.
    expect(await screen.findAllByText(/Docker node1/)).not.toHaveLength(0)
    expect(screen.queryByText(/Gitea SSH/)).not.toBeInTheDocument()
  })
})
