import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminNetwork from './AdminNetwork'

describe('AdminNetwork', () => {
  it('rend le formulaire pré-rempli avec la config réseau', async () => {
    server.use(
      http.get('/admin/network', () =>
        HttpResponse.json({
          base_domain: 'dev.yoops.org',
          external_url: 'https://dev.yoops.org',
          workspace_host: '192.168.10.50',
        }),
      ),
    )
    renderWithProviders(<AdminNetwork />)

    expect(await screen.findByDisplayValue('dev.yoops.org')).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://dev.yoops.org')).toBeInTheDocument()
    expect(screen.getByDisplayValue('192.168.10.50')).toBeInTheDocument()
  })

  it('le bouton Resolve envoie le workspace_host courant au backend', async () => {
    let received: unknown = null
    server.use(
      http.get('/admin/network', () =>
        HttpResponse.json({
          base_domain: '',
          external_url: '',
          workspace_host: 'portal',
        }),
      ),
      http.post('/admin/network/resolve-workspace-host', async ({ request }) => {
        received = await request.json()
        return HttpResponse.json({ fqdn: 'portal.home.lan', ip: '192.168.10.42' })
      }),
    )
    renderWithProviders(<AdminNetwork />)

    await screen.findByDisplayValue('portal')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Resolve' }))

    await waitFor(() => expect(received).toEqual({ host: 'portal' }))
  })
})
