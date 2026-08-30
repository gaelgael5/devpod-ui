/**
 * Éditeur d'un type d'hyperviseur, en page pleine.
 *
 * Le point sensible est la CIBLE : les deux onglets d'actions partagent une
 * seule liste (les slugs doivent rester uniques sur les deux), chacun ne montre
 * que la sienne, et une action créée dans un onglet naît avec sa cible.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import i18n from '@/i18n'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import AdminHypervisorTypeEditor from './AdminHypervisorTypeEditor'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

const TYPE = {
  label: 'Proxmox4vm',
  name: 'roxmox4vm',
  add_script: 'https://exemple.test/create.json',
  destroy_script: 'https://exemple.test/destroy.json',
  actions: [
    {
      label: 'Increase memory +1G',
      slug: 'roxmox4vm-increase-memory-1g',
      script: 'https://exemple.test/mem.json',
      cible: 'machine',
    },
    {
      label: 'Inventaire',
      slug: 'roxmox4vm-inventaire',
      script: 'https://exemple.test/inv.json',
      cible: 'hyperviseur',
    },
  ],
  variables: [],
}

function renderEditor(route = '/admin/hypervisor-types/roxmox4vm', types: unknown[] = [TYPE]) {
  server.use(http.get('/admin/hypervisor-types', () => HttpResponse.json(types)))
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/admin/hypervisor-types/:name',
        element: (
          <I18nextProvider i18n={i18n}>
            <AdminHypervisorTypeEditor />
          </I18nextProvider>
        ),
      },
      { path: '/admin/hypervisor-types', element: <p>liste</p> },
    ],
    { initialEntries: [route] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

async function ongletActions(nom: 'hyperviseur' | 'machine') {
  const cle =
    nom === 'hyperviseur'
      ? 'admin.hypervisorTypeEditor.tabHypervisorActions'
      : 'admin.hypervisorTypeEditor.tabMachineActions'
  await userEvent.click(await screen.findByRole('tab', { name: i18n.t(cle) }))
}

describe('AdminHypervisorTypeEditor', () => {
  it('titre la page avec le libellé, pas la clef technique', async () => {
    renderEditor('/admin/hypervisor-types/pve-legacy', [
      { ...TYPE, label: 'Cluster maison', name: 'pve-legacy' },
    ])

    const titre = await screen.findByRole('heading', { name: /(modifier|edit)/i })
    expect(titre.textContent).toContain('Cluster maison')
    expect(titre.textContent).not.toContain('pve-legacy')
  })

  it('sépare les actions selon leur cible', async () => {
    renderEditor()

    await ongletActions('hyperviseur')
    expect(await screen.findByDisplayValue('Inventaire')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Increase memory +1G')).not.toBeInTheDocument()

    await ongletActions('machine')
    expect(await screen.findByDisplayValue('Increase memory +1G')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Inventaire')).not.toBeInTheDocument()
  })

  it('les scripts de création et de destruction vivent avec les actions machine', async () => {
    renderEditor()
    await ongletActions('machine')

    expect(await screen.findByDisplayValue('https://exemple.test/create.json')).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://exemple.test/destroy.json')).toBeInTheDocument()
  })

  it('enregistre une action créée depuis l’onglet hyperviseur avec cette cible', async () => {
    let recu: { actions?: { slug: string; cible?: string }[] } | null = null
    server.use(
      http.put('/admin/hypervisor-types/:name', async ({ request }) => {
        recu = (await request.json()) as typeof recu
        return HttpResponse.json(TYPE)
      }),
    )
    renderEditor()
    await ongletActions('hyperviseur')

    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.hypervisorActions.add') }))
    const champs = screen.getAllByPlaceholderText(i18n.t('admin.hypervisorActions.labelPlaceholder'))
    await userEvent.type(champs[champs.length - 1], 'Rebooter le noeud')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('admin.form.save') }))

    await waitFor(() => expect(recu).not.toBeNull())
    const ajoutee = recu!.actions!.find((a) => a.slug === 'rebooter-le-noeud')
    expect(ajoutee?.cible).toBe('hyperviseur')
    // L'autre onglet n'a rien perdu : une seule liste, deux vues.
    expect(recu!.actions!.map((a) => a.slug)).toContain('roxmox4vm-increase-memory-1g')
  })

  it('fige la clef technique en édition', async () => {
    renderEditor()

    expect(await screen.findByLabelText(i18n.t('admin.col.name'))).toBeDisabled()
  })

  it('à la création, la clef technique suit le libellé', async () => {
    renderEditor('/admin/hypervisor-types/new', [])

    await userEvent.type(await screen.findByLabelText(i18n.t('admin.form.hypervisorLabel')), 'Proxmox KVM')
    expect(screen.getByLabelText(i18n.t('admin.col.name'))).toHaveValue('proxmox-kvm')
  })
})
