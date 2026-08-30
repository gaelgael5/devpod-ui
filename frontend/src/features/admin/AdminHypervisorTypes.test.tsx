/**
 * Liste des types d'hyperviseur. Depuis la sortie du mode popup, la page ne
 * fait plus que lister : « Ajouter » et « Modifier » NAVIGUENT, et aucun
 * formulaire ne vit ici.
 */
import { screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import i18n from '@/i18n'
import userEvent from '@testing-library/user-event'
import { render } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import AdminHypervisorTypes from './AdminHypervisorTypes'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

const TYPE = {
  label: 'Proxmox4vm',
  name: 'roxmox4vm',
  add_script: 'https://exemple.test/create.json',
  destroy_script: 'https://exemple.test/destroy.json',
  actions: [],
}

/** Rend la liste dans un routeur qui EXPOSE l'URL courante, pour vérifier la navigation. */
function renderPage(types: unknown[] = [TYPE]) {
  server.use(http.get('/admin/hypervisor-types', () => HttpResponse.json(types)))
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/admin/hypervisor-types',
        element: (
          <I18nextProvider i18n={i18n}>
            <AdminHypervisorTypes />
          </I18nextProvider>
        ),
      },
      { path: '/admin/hypervisor-types/new', element: <p>page création</p> },
      { path: '/admin/hypervisor-types/:name', element: <p>page édition</p> },
    ],
    { initialEntries: ['/admin/hypervisor-types'] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe('AdminHypervisorTypes', () => {
  it('ouvre la page d’édition du type, sans dialogue', async () => {
    const router = renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /modifier|edit/i }))

    expect(router.state.location.pathname).toBe('/admin/hypervisor-types/roxmox4vm')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ouvre la page de création', async () => {
    const router = renderPage()
    await userEvent.click(
      await screen.findByRole('button', { name: i18n.t('admin.addHypervisorType') }),
    )

    expect(router.state.location.pathname).toBe('/admin/hypervisor-types/new')
  })

  it('liste le libellé et la clef technique', async () => {
    renderPage([{ ...TYPE, label: 'Cluster maison', name: 'pve-legacy' }])

    expect(await screen.findByText('Cluster maison')).toBeInTheDocument()
    expect(screen.getByText('pve-legacy')).toBeInTheDocument()
  })
})
