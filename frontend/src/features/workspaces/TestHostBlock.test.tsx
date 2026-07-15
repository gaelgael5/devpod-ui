import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostBlock from './TestHostBlock'
import { stoppedLast } from './sortWorkspaces'
import type { TestHost } from './useTestVm'
import type { WorkspaceSpec } from './types'
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

describe('TestHostBlock — liens (clé → URL) du menu ⋮', () => {
  it('affiche les liens enregistrés et ouvre un nouvel onglet au clic', async () => {
    server.use(
      http.get('/me/workspaces/:ws/test-hosts/:host/links', () =>
        HttpResponse.json([{ key: 'grafana', url: 'http://192.168.10.160:3001' }]),
      ),
    )
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /grafana/i }))

    expect(openSpy).toHaveBeenCalledWith(
      'http://192.168.10.160:3001',
      '_blank',
      'noopener,noreferrer',
    )
    openSpy.mockRestore()
  })

  it('« Gérer les liens… » ouvre le dialog et enregistre un lien (PUT)', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/me/workspaces/:ws/test-hosts/:host/links', () => HttpResponse.json([])),
      http.put('/me/workspaces/:ws/test-hosts/:host/links', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json(putBody)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /gérer les liens|manage links/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    await user.type(screen.getByLabelText(/clé|key/i), 'app')
    await user.type(screen.getByLabelText(/url/i), 'http://192.168.10.160:3000')
    await user.click(screen.getByRole('button', { name: /ajouter|add/i }))

    await waitFor(() =>
      expect(putBody).toEqual({ key: 'app', url: 'http://192.168.10.160:3000' }),
    )
  })

  it("le bouton copier met l'URL au presse-papiers sans ouvrir d'onglet", async () => {
    server.use(
      http.get('/me/workspaces/:ws/test-hosts/:host/links', () =>
        HttpResponse.json([{ key: 'grafana', url: 'http://192.168.10.160:3001' }]),
      ),
    )
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    // Après userEvent.setup() : il installe son propre stub navigator.clipboard.
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(
      await screen.findByRole('button', { name: /copier l'url de grafana|copy grafana url/i }),
    )

    expect(writeText).toHaveBeenCalledWith('http://192.168.10.160:3001')
    expect(openSpy).not.toHaveBeenCalled()
    openSpy.mockRestore()
  })

  it("le crayon pré-remplit le formulaire ; renommer la clé supprime l'ancienne entrée", async () => {
    let putBody: unknown = null
    const deleted: string[] = []
    server.use(
      http.get('/me/workspaces/:ws/test-hosts/:host/links', () =>
        HttpResponse.json([{ key: 'front', url: 'http://192.168.10.160:8080' }]),
      ),
      http.put('/me/workspaces/:ws/test-hosts/:host/links', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json(putBody)
      }),
      http.delete('/me/workspaces/:ws/test-hosts/:host/links/:key', ({ params }) => {
        deleted.push(String(params.key))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={HOST} deployments={[]} onOpenSsh={vi.fn()} />
    )

    await user.click(screen.getByRole('button', { name: /actions/i }))
    await user.click(await screen.findByRole('menuitem', { name: /gérer les liens|manage links/i }))
    await user.click(
      await screen.findByRole('button', { name: /modifier le lien front|edit link front/i }),
    )

    const keyInput = screen.getByLabelText(/clé|key/i) as HTMLInputElement
    const urlInput = screen.getByLabelText(/url/i) as HTMLInputElement
    expect(keyInput.value).toBe('front')
    expect(urlInput.value).toBe('http://192.168.10.160:8080')

    await user.clear(keyInput)
    await user.type(keyInput, 'frontend')
    await user.click(screen.getByRole('button', { name: /mettre à jour|update/i }))

    await waitFor(() =>
      expect(putBody).toEqual({ key: 'frontend', url: 'http://192.168.10.160:8080' }),
    )
    await waitFor(() => expect(deleted).toEqual(['front']))
  })
})

describe('TestHostBlock — bloc partagé (sharedFrom)', () => {
  const SHARED: TestHost = { ...HOST, sharedFrom: 'owner-ws' }

  it('affiche le badge « Partagé par » et masque les actions de cycle de vie', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={SHARED} deployments={[]} onOpenSsh={vi.fn()} />,
    )
    expect(screen.getByText(/partagé par owner-ws|shared by owner-ws/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /actions/i }))
    // Ouvrir SSH reste ; suppression, partage et resolve-ip sont absents.
    expect(await screen.findByText(/open ssh session|ouvrir une session ssh/i)).toBeInTheDocument()
    expect(screen.queryByText(/^delete$|^supprimer$/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^share…$|^partager…$/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/resolve ip|résoudre l'ip/i)).not.toBeInTheDocument()
  })

  it('affiche les services sans aucun bouton d’action (lecture seule)', () => {
    renderWithProviders(
      <TestHostBlock wsName="ws1" host={SHARED} deployments={[DEPLOYMENT]} onOpenSsh={vi.fn()} />,
    )
    // Le service reste visible avec son statut (même graphisme)…
    expect(screen.getByText('nginx-demo')).toBeInTheDocument()
    // …mais aucune action (stop/restart/logs/supprimer) n'est proposée.
    expect(screen.queryByRole('button', { name: /stop|arrêter/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /restart|redémarrer/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /logs|journaux/i })).not.toBeInTheDocument()
  })
})

describe('stoppedLast — workspaces arrêtés en fin de groupe', () => {
  const ws = (name: string): WorkspaceSpec => ({ name, source: '' }) as WorkspaceSpec
  const list = [ws('a'), ws('b'), ws('c'), ws('d')]

  it("relègue les arrêtés à la fin en préservant l'ordre relatif", () => {
    const statuses: Record<string, string> = {
      a: 'stopped', b: 'running', c: 'stopped', d: 'provisioning',
    }
    expect(stoppedLast(list, (n) => statuses[n]).map((w) => w.name)).toEqual(
      ['b', 'd', 'a', 'c'],
    )
  })

  it('ordre inchangé sans workspace arrêté (statuts inconnus inclus)', () => {
    expect(stoppedLast(list, () => undefined).map((w) => w.name)).toEqual(
      ['a', 'b', 'c', 'd'],
    )
  })
})
