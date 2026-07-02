import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import { server } from '@/test/server'
import ComposeGallery from '../ComposeGallery'

describe('ComposeGallery', () => {
  it('lists templates from the API', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    const { findByText } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    expect(await findByText('Browserless')).toBeInTheDocument()
  })

  it('enables auto-start directly when the template has no required params', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    let putBody: unknown = null
    server.use(
      http.put('/api/compose/templates/:id/auto-start', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ template_id: 'browserless', enabled: true })
      }),
    )
    const { findByRole } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    const toggle = await findByRole('switch')
    toggle.click()

    await new Promise((r) => setTimeout(r, 0))
    expect(putBody).toEqual({ enabled: true, env_values: {} })
  })

  it('disables auto-start directly (no dialog needed)', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    server.use(
      http.get('/api/compose/templates', () =>
        HttpResponse.json([
          { id: 'browserless', name: 'Browserless', description: '', tags: ['web'],
            version: '1', compose_content: 'services: {}', parameters: [], source: 'user',
            auto_start: true },
        ])),
    )
    let putBody: unknown = null
    server.use(
      http.put('/api/compose/templates/:id/auto-start', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ template_id: 'browserless', enabled: false })
      }),
    )
    const { findByRole } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    const toggle = await findByRole('switch')
    toggle.click()

    await new Promise((r) => setTimeout(r, 0))
    expect(putBody).toEqual({ enabled: false })
  })

  it('opens a dialog to collect required params before enabling auto-start', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    server.use(
      http.get('/api/compose/templates', () =>
        HttpResponse.json([
          { id: 'searxng', name: 'SearXNG', description: '', tags: [],
            version: '1', compose_content: 'services: {}', source: 'user', auto_start: false,
            parameters: [{ key: 'WEB_PORT', label: 'Port', type: 'port', required: true }] },
        ])),
    )
    const { findByRole, findByText } = renderWithProviders(<ComposeGallery />, {
      route: '/compose',
    })
    const toggle = await findByRole('switch')
    toggle.click()

    expect(await findByText('Auto-start — SearXNG')).toBeInTheDocument()
  })
})
