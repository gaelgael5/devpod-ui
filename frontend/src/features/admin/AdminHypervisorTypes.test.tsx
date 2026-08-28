/**
 * Types d'hyperviseur : le `name` est une clef technique, le libelle est ce qui
 * se lit. Un slug mal derive (« roxmox4vm ») ne doit apparaitre nulle part comme
 * identite de l'objet.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
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

function renderPage(types: unknown[] = [TYPE]) {
  server.use(http.get('/admin/hypervisor-types', () => HttpResponse.json(types)))
  renderWithProviders(<AdminHypervisorTypes />)
}

describe('AdminHypervisorTypes', () => {
  it('titre le dialogue d’edition avec le libelle', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /modifier|edit/i }))

    expect(
      await screen.findByRole('heading', { name: /(modifier|edit).*Proxmox4vm/i }),
    ).toBeInTheDocument()
  })

  it('n’utilise pas le nom technique quand un libelle existe', async () => {
    // Libelle et nom volontairement sans rapport : « Proxmox4vm » contient
    // « roxmox4vm », un test par sous-chaine sur la vraie donnee ne prouverait
    // rien.
    renderPage([{ ...TYPE, label: 'Cluster maison', name: 'pve-legacy' }])
    await userEvent.click(await screen.findByRole('button', { name: /modifier|edit/i }))

    const titre = await screen.findByRole('heading', { name: /(modifier|edit)/i })
    expect(titre.textContent).toContain('Cluster maison')
    expect(titre.textContent).not.toContain('pve-legacy')
  })

  it('retombe sur le nom technique quand le libelle est vide', async () => {
    // Un type cree avant l'ajout du libelle n'en a pas : mieux vaut la clef
    // technique qu'un titre tronque.
    renderPage([{ ...TYPE, label: '' }])
    await userEvent.click(await screen.findByRole('button', { name: /modifier|edit/i }))

    expect(
      await screen.findByRole('heading', { name: /(modifier|edit).*roxmox4vm/i }),
    ).toBeInTheDocument()
  })

  it("rafraichit les variables des profils de host apres modification d'un type", async () => {
    // Cas reel : une variable ajoutee au type n'apparaissait pas dans le
    // formulaire d'un profil de machine DEJA consulte — sa liste de variables
    // restait en cache jusqu'a expiration, et l'admin croyait a une perte.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    })
    const CLE = ['admin', 'host-profiles', 'variables', 'host-workspace-standard']
    qc.setQueryData(CLE, [])
    server.use(
      http.get('/admin/hypervisor-types', () => HttpResponse.json([TYPE])),
      http.put('/admin/hypervisor-types/:name', () => HttpResponse.json(TYPE)),
    )
    render(
      <QueryClientProvider client={qc}>
        <I18nextProvider i18n={i18n}>
          <AdminHypervisorTypes />
        </I18nextProvider>
      </QueryClientProvider>,
    )

    await userEvent.click(await screen.findByRole('button', { name: /modifier|edit/i }))
    await userEvent.click(await screen.findByRole('button', { name: i18n.t('admin.form.save') }))

    await waitFor(() => {
      expect(qc.getQueryState(CLE)?.isInvalidated).toBe(true)
    })
  })
})
