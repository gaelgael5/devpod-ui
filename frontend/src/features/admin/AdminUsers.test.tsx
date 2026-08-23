import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'

// Radix Select s'appuie sur des API pointer/scroll absentes de jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.releasePointerCapture = vi.fn()
  Element.prototype.setPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import { useUserStore } from '@/store/user'
import AdminUsers from './AdminUsers'

const USERS = [
  { login: 'alice', email: 'a@x', display_name: 'Alice', termix_instance_ids: [] },
]
const INSTANCES = [
  { id: 'i1', name: 'prod', url: 'https://t', apikey_secret: 's', oidc_client_id: '', is_default: true },
]
const HOSTS = [
  { ws_id: 'ws-a', login: 'alice', host_name: 'node1', ssh_port: 50001 },
  { ws_id: 'ws-b', login: 'bob', host_name: 'node1', ssh_port: 50002 },
]

describe('AdminUsers', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'admin', roles: ['dev', 'admin'], is_admin: true } })
    server.use(
      http.get('/admin/users', () => HttpResponse.json(USERS)),
      http.get('/admin/termix-instances', () => HttpResponse.json(INSTANCES)),
      http.get('/admin/ssh-hosts', () => HttpResponse.json(HOSTS)),
    )
  })

  it('liste les users', async () => {
    renderWithProviders(<AdminUsers />)
    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText(/Alice/)).toBeInTheDocument()
  })

  it('rattache une instance Termix via le multi-sélecteur (PUT)', async () => {
    let putBody: unknown = null
    server.use(
      http.put('/admin/users/alice/termix-instances', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ instance_ids: ['i1'] })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminUsers />)
    await screen.findByText('alice')
    // Le Select « Ajouter… » propose les instances non encore rattachées.
    await user.click(await screen.findByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'prod' }))
    await waitFor(() => expect(putBody).toEqual({ instance_ids: ['i1'] }))
  })

  it('sauve le partage de hosts (PUT host-grants avec cases cochées)', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/admin/users/alice/host-grants', () => HttpResponse.json({ hosts: ['ws-a'] })),
      http.put('/admin/users/alice/host-grants', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ hosts: ['ws-a', 'ws-b'] })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminUsers />)
    await screen.findByText('alice')
    await user.click(screen.getByRole('button', { name: /ssh hosts|hosts ssh/i }))
    const dialog = await screen.findByRole('dialog')
    // ws-a pré-coché, ws-b non ; on coche ws-b.
    const wsA = within(dialog).getByLabelText('ws-a') as HTMLInputElement
    const wsB = within(dialog).getByLabelText('ws-b') as HTMLInputElement
    await waitFor(() => expect(wsA.checked).toBe(true))
    expect(wsB.checked).toBe(false)
    await user.click(wsB)
    await user.click(within(dialog).getByRole('button', { name: /save|enregistrer/i }))
    await waitFor(() => expect(putBody).toEqual({ hosts: ['ws-a', 'ws-b'] }))
  })
})
