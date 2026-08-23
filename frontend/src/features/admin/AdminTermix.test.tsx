import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import { useUserStore } from '@/store/user'
import AdminTermix from './AdminTermix'

const LOCAL = {
  id: 'i1',
  name: 'termix-portail',
  url: 'https://termix.yoops.org',
  apikey_secret: 'termix-apikey',
  oidc_client_id: 'termix',
  is_default: true,
}

const SECRETS = [
  { slug: 'termix-apikey', label: 'Apikey Termix', secret_type: 'API_KEY', storage_type: 'local' },
]

describe('AdminTermix', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'], is_admin: true } })
    server.use(
      http.get('/admin/automations/secrets', () => HttpResponse.json(SECRETS)),
    )
  })

  it('liste les instances (nom, url, secret, badge défaut)', async () => {
    server.use(http.get('/admin/termix-instances', () => HttpResponse.json([LOCAL])))

    renderWithProviders(<AdminTermix />)

    expect(await screen.findByText('termix-portail')).toBeInTheDocument()
    expect(screen.getByText('https://termix.yoops.org')).toBeInTheDocument()
    expect(screen.getByText('termix-apikey')).toBeInTheDocument()
  })

  it("l'édition renvoie l'url modifiée dans le PATCH (secret pré-rempli)", async () => {
    let patchBody: unknown = null
    server.use(
      http.get('/admin/termix-instances', () => HttpResponse.json([LOCAL])),
      http.patch('/admin/termix-instances/i1', async ({ request }) => {
        patchBody = await request.json()
        return HttpResponse.json({ ...LOCAL })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<AdminTermix />)

    await user.click(await screen.findByRole('button', { name: /^edit$|^modifier$/i }))
    const dialog = await screen.findByRole('dialog')
    const url = within(dialog).getByLabelText(/termix url|url termix/i)
    await user.clear(url)
    await user.type(url, 'https://termix2.yoops.org')
    await user.click(within(dialog).getByRole('button', { name: /save|enregistrer/i }))

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toMatchObject({
      url: 'https://termix2.yoops.org',
      apikey_secret: 'termix-apikey',
    })
  })
})
