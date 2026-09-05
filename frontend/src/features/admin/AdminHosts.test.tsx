import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeAll, describe, expect, it, beforeEach, vi } from 'vitest'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
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

  it("affiche la provenance d'une machine, et « inconnue » sans en faire une erreur", async () => {
    // La provenance est un FAIT posé au provisionnement (hosts.hypervisor).
    // Vide = machine enrôlée à la main ou antérieure à la colonne : les écrans
    // le disent tel quel, jamais comme une erreur ni un hyperviseur par défaut.
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([
          { name: 'ded-4321', type: 'docker-tls', docker_host: 'tcp://10.0.0.42:2376', usage: 'workspaces', hypervisor: 'pve-1' },
          { name: 'manuel', type: 'docker-tls', docker_host: 'tcp://10.0.0.9:2376', usage: 'workspaces' },
        ])),
    )
    renderWithProviders(<AdminHosts />)

    await waitFor(() => expect(screen.getByText('ded-4321')).toBeInTheDocument())
    expect(screen.getByText('pve-1')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('admin.provenanceUnknown'))).toBeInTheDocument()
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

  it("liste un host usage=autres dans la section « Autres serveurs », hors table workspaces", async () => {
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([
          { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376', usage: 'workspaces' },
          { name: 'backup-srv', type: 'ssh', default: false, address: 'debian@192.168.10.190', usage: 'autres' },
        ])),
    )
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('backup-srv')).toBeInTheDocument())
    expect(screen.getByText(/other servers|autres serveurs/i)).toBeInTheDocument()
    // Pas dans la table workspaces : backup-srv n'est pas dans une ligne <tr>
    const rows = screen.queryAllByRole('row')
    expect(rows.find((r) => r.textContent?.includes('backup-srv'))).toBeUndefined()
  })

  it('propose une clé SSH (certs ssh-* uniquement) pour un host ssh', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /add host|ajouter un h[oô]te/i }))

    // Basculer le type sur ssh.
    const typeSelects = screen.getAllByRole('combobox')
    await user.click(typeSelects[0])
    await user.click(await screen.findByRole('option', { name: 'ssh' }))

    // Le sélecteur de clé SSH apparaît ; il liste le cert ssh-* mais pas le tls-*.
    expect(await screen.findByText(/ssh key|clé ssh/i)).toBeInTheDocument()
    const selects = screen.getAllByRole('combobox')
    const keySelect = selects.find((s) =>
      s.textContent?.match(/keep current key|conserver la clé actuelle/i))
    expect(keySelect).toBeDefined()
    await user.click(keySelect!)
    expect(await screen.findAllByText(/Gitea SSH/)).not.toHaveLength(0)
    expect(screen.queryByText(/Docker node1/)).not.toBeInTheDocument()
  })

  it('révèle le mot de passe console après saisie du PIN (édition, slug présent)', async () => {
    let sentPin = ''
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([
          { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376', ci_password_secret_slug: 'host.pve1.ci-password' },
        ])),
      http.post('/admin/hosts/pve1/ci-password/reveal', async ({ request }) => {
        const body = (await request.json()) as { pin: string }
        sentPin = body.pin
        return HttpResponse.json({ value: 'sup3r-c0nsole' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())

    // Ouvrir l'édition (premier bouton icône de la ligne = crayon).
    const pve1Row = screen.getAllByRole('row').find((r) => r.textContent?.includes('pve1'))!
    await user.click(pve1Row.querySelectorAll('button')[0])

    // Le bouton révéler n'apparaît qu'en édition d'un host qui a un secret stocké.
    const revealBtn = await screen.findByRole('button', { name: /révéler|reveal/i })
    await user.click(revealBtn)

    // Saisie du PIN puis confirmation → la valeur s'affiche, le PIN est parti au backend.
    await user.type(screen.getByPlaceholderText(/pin/i), '123456')
    await user.click(screen.getByRole('button', { name: /^révéler$|^reveal$/i }))
    expect(await screen.findByDisplayValue('sup3r-c0nsole')).toBeInTheDocument()
    expect(sentPin).toBe('123456')

    // « Masquer » re-masque immédiatement.
    await user.click(screen.getByRole('button', { name: /masquer|hide/i }))
    expect(screen.queryByDisplayValue('sup3r-c0nsole')).not.toBeInTheDocument()
  })

  it("edite la capacite d'accueil et l'ouverture au mutualise", async () => {
    // Ces deux champs decident de ce que le pool peut poser sur la machine.
    // Les perdre au premier update rendrait la machine invisible du decideur.
    let envoye: Record<string, unknown> = {}
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([
          { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376', capacity_workspaces: 6, accepts_mutualise: false },
        ])),
      http.put('/admin/hosts/pve1', async ({ request }) => {
        envoye = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ name: 'pve1', type: 'docker-tls' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())

    const ligne = screen.getAllByRole('row').find((r) => r.textContent?.includes('pve1'))!
    await user.click(ligne.querySelectorAll('button')[0])

    // La valeur enregistree est reprise telle quelle, pas remise a zero.
    const capacite = await screen.findByLabelText(/capacit/i)
    expect(capacite).toHaveValue(6)

    await user.clear(capacite)
    await user.type(capacite, '9')
    await user.click(screen.getByRole('checkbox', { name: /shared plans|mutualis/i }))
    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() => expect(envoye.capacity_workspaces).toBe(9))
    expect(envoye.accepts_mutualise).toBe(true)
  })

  it('laisse la capacite vide quand elle est inconnue', async () => {
    // Un noeud enrole a la main n'a pas de profil : sa capacite est inconnue
    // tant que l'exploitant ne l'a pas dite. Afficher 0 la ferait passer pour
    // une machine qui n'accepte rien.
    server.use(
      http.get('/admin/hosts', () =>
        HttpResponse.json([{ name: 'brut', type: 'ssh', address: 'root@10.0.0.9' }])),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('brut')).toBeInTheDocument())

    const ligne = screen.getAllByRole('row').find((r) => r.textContent?.includes('brut'))!
    await user.click(ligne.querySelectorAll('button')[0])

    expect(await screen.findByLabelText(/capacit/i)).toHaveValue(null)
  })

  it("n'affiche pas le bouton révéler pour un host sans mot de passe console", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    const pve1Row = screen.getAllByRole('row').find((r) => r.textContent?.includes('pve1'))!
    await user.click(pve1Row.querySelectorAll('button')[0])
    expect(await screen.findByLabelText(/mot de passe console|console password/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /révéler|reveal/i })).not.toBeInTheDocument()
  })

  it('propose le certificat mTLS (certs tls-* uniquement) pour un host docker-tls', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    // On edite `pve1`, qui EST un host docker-tls : le type par defaut du
    // formulaire d'ajout est `ssh` (le cas courant), et Radix Select ne s'ouvre
    // pas sous jsdom pour en changer.
    const pve1Row = screen.getAllByRole('row').find((r) => r.textContent?.includes('pve1'))!
    await user.click(pve1Row.querySelectorAll('button')[0])

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
