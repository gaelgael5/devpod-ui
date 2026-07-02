import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminLogs from './AdminLogs'

const CONFIG = {
  enabled: true,
  loki_push_url: 'http://192.168.10.196:3100/loki/api/v1/push',
  loki_query_url: 'http://loki:3100',
  grafana_url: 'https://log.dev.yoops.org',
  module: 'devpod',
  has_push_token: false,
}

describe('AdminLogs', () => {
  it('rend le formulaire pré-rempli avec la config logs', async () => {
    server.use(http.get('/admin/logs-config', () => HttpResponse.json(CONFIG)))
    renderWithProviders(<AdminLogs />)

    expect(await screen.findByDisplayValue(CONFIG.loki_push_url)).toBeInTheDocument()
    expect(screen.getByDisplayValue(CONFIG.loki_query_url)).toBeInTheDocument()
    expect(screen.getByDisplayValue(CONFIG.grafana_url)).toBeInTheDocument()
  })

  it('désactive Save et affiche un message si activé sans URLs Loki', async () => {
    server.use(
      http.get('/admin/logs-config', () =>
        HttpResponse.json({ ...CONFIG, loki_push_url: '', loki_query_url: '' })),
    )
    renderWithProviders(<AdminLogs />)

    expect(await screen.findByText(/required to enable centralized logs/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('enregistre les modifications et vide le champ push token', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/admin/logs-config', () => HttpResponse.json(CONFIG)),
      http.put('/admin/logs-config', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json(CONFIG)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminLogs />)

    await screen.findByDisplayValue(CONFIG.loki_push_url)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(putBody).toEqual({
      enabled: true,
      loki_push_url: CONFIG.loki_push_url,
      loki_query_url: CONFIG.loki_query_url,
      grafana_url: CONFIG.grafana_url,
      module: CONFIG.module,
    })
  })
})
