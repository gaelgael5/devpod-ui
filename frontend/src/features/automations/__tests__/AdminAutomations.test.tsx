import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import AdminAutomations from '../AdminAutomations'
import AdminContracts from '../AdminContracts'

const AUTOMATION = {
  id: 'a1',
  label: 'sync-hosts',
  active: true,
  position: 0,
  stop_chain: false,
  event_types: ['test_server.updated'],
  delay_minutes: 0,
  contract_ref: 'c1',
  operation_id: 'putHost',
  url: 'https://termix.example.org/api/hosts',
  http_method: 'PUT',
  body_template: null,
  scopes: ['*'],
  headers: [],
  last_seq: 0,
  pending: 3,
}

describe('AdminAutomations', () => {
  it('lists an automation with its trigger and pending badge', async () => {
    server.use(http.get('/admin/automations', () => HttpResponse.json([AUTOMATION])))
    const { findByText } = renderWithProviders(<AdminAutomations />, {
      route: '/admin/automations',
    })
    expect(await findByText('sync-hosts')).toBeInTheDocument()
    expect(await findByText('test_server.updated')).toBeInTheDocument()
  })
})

describe('AdminContracts', () => {
  it('lists an imported contract with its version', async () => {
    server.use(
      http.get('/admin/automations/contracts', () =>
        HttpResponse.json([
          {
            id: 'c1',
            label: 'Termix API',
            source_url: 'https://termix.example.org/openapi.json',
            version: '2.1.0',
            created_at: '2026-08-08T00:00:00Z',
            updated_at: '2026-08-08T00:00:00Z',
          },
        ]),
      ),
    )
    const { findByText } = renderWithProviders(<AdminContracts />, {
      route: '/admin/automations/contracts',
    })
    expect(await findByText('Termix API')).toBeInTheDocument()
    expect(await findByText('v2.1.0')).toBeInTheDocument()
  })
})
