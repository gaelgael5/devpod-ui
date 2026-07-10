import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminWorkflow from './AdminWorkflow'

const CONFIG = {
  enabled: false,
  workflow_base_url: 'https://workflow.yoops.org',
  source_id: 'abc-123',
  source_uri: 'urn:yoops:devpod',
  events: ['workspace.created'],
  available_events: ['workspace.created', 'workspace.deleted', 'session.created'],
  has_secret: true,
}

describe('AdminWorkflow', () => {
  it('rend le formulaire pré-rempli et coche les events de la liste blanche', async () => {
    server.use(http.get('/admin/events-producer', () => HttpResponse.json(CONFIG)))
    renderWithProviders(<AdminWorkflow />)

    expect(await screen.findByDisplayValue(CONFIG.workflow_base_url)).toBeInTheDocument()
    expect(screen.getByDisplayValue(CONFIG.source_id)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /workspace\.created/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /workspace\.deleted/ })).not.toBeChecked()
  })

  it('désactive Save et alerte si activé sans event coché', async () => {
    server.use(
      http.get('/admin/events-producer', () =>
        HttpResponse.json({ ...CONFIG, enabled: true, events: [] })),
    )
    renderWithProviders(<AdminWorkflow />)

    expect(await screen.findByText(/at least one event/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('enregistre sans envoyer le secret quand le champ est vide', async () => {
    let putBody: unknown = null
    server.use(
      http.get('/admin/events-producer', () => HttpResponse.json(CONFIG)),
      http.put('/admin/events-producer', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json(CONFIG)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminWorkflow />)

    await screen.findByDisplayValue(CONFIG.workflow_base_url)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(putBody).toEqual({
      enabled: false,
      workflow_base_url: CONFIG.workflow_base_url,
      source_id: CONFIG.source_id,
      source_uri: CONFIG.source_uri,
      events: ['workspace.created'],
    })
  })
})
