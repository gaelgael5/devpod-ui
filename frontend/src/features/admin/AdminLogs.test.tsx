import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useLogsConfig } from '@/features/grafana/useLogsConfig'
import AdminLogs from './AdminLogs'

/** Sonde consommant la même query que le bouton Logs (AppShell/WorkspaceList). */
function LogsButtonProbe() {
  const { data } = useLogsConfig()
  return <div data-testid="probe">{data?.enabled ? 'enabled' : 'disabled'}</div>
}

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

  it('pré-remplit les URLs Loki/Grafana depuis workspace_host quand elles sont vides', async () => {
    server.use(
      http.get('/admin/logs-config', () =>
        HttpResponse.json({ ...CONFIG, loki_push_url: '', grafana_url: '' })),
      http.get('/admin/network', () =>
        HttpResponse.json({
          base_domain: '', external_url: '', workspace_host: '192.168.10.164', dev_mode: false,
          vs_proxy_domain: '', cookie_domain: '',
        })),
    )
    renderWithProviders(<AdminLogs />)

    expect(
      await screen.findByDisplayValue('http://192.168.10.164:3100/loki/api/v1/push'),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('http://192.168.10.164:3001')).toBeInTheDocument()
  })

  it('pré-remplit Loki query URL avec le nom du service Docker interne quand vide', async () => {
    server.use(
      http.get('/admin/logs-config', () =>
        HttpResponse.json({ ...CONFIG, loki_query_url: '' })),
    )
    renderWithProviders(<AdminLogs />)

    expect(await screen.findByDisplayValue('http://loki:3100')).toBeInTheDocument()
  })

  it('invalide /me/logs-config après Save (bouton Logs à jour sans reload)', async () => {
    let saved = false
    server.use(
      http.get('/admin/logs-config', () => HttpResponse.json({ ...CONFIG, enabled: false })),
      http.get('/me/logs-config', () =>
        HttpResponse.json(
          saved
            ? { enabled: true, grafana_url: CONFIG.grafana_url }
            : { enabled: false, grafana_url: null },
        )),
      http.put('/admin/logs-config', async ({ request }) => {
        await request.json()
        saved = true
        return HttpResponse.json({ ...CONFIG, enabled: true })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(
      <>
        <AdminLogs />
        <LogsButtonProbe />
      </>,
    )

    await screen.findByDisplayValue(CONFIG.loki_push_url)
    expect(await screen.findByTestId('probe')).toHaveTextContent('disabled')

    await user.click(screen.getByRole('checkbox', { name: /centralized logs enabled/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByTestId('probe')).toHaveTextContent('enabled')
  })

  it('ne touche pas aux URLs déjà configurées même si workspace_host est renseigné', async () => {
    server.use(
      http.get('/admin/logs-config', () => HttpResponse.json(CONFIG)),
      http.get('/admin/network', () =>
        HttpResponse.json({
          base_domain: '', external_url: '', workspace_host: '192.168.10.164', dev_mode: false,
          vs_proxy_domain: '', cookie_domain: '',
        })),
    )
    renderWithProviders(<AdminLogs />)

    expect(await screen.findByDisplayValue(CONFIG.loki_push_url)).toBeInTheDocument()
    expect(screen.queryByDisplayValue(/192\.168\.10\.164/)).not.toBeInTheDocument()
  })
})
