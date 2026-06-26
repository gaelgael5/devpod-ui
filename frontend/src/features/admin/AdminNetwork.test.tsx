import { screen } from '@testing-library/react'
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
})
