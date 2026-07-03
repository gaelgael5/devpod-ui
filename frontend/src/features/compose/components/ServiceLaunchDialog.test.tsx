import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import ServiceLaunchDialog from './ServiceLaunchDialog'

const ALLOY_TEMPLATE = {
  id: 'alloy-logs',
  name: 'Collecteur de logs (Alloy)',
  description: '',
  tags: ['observabilité', 'logs'],
  version: '1',
  compose_content: 'services:\n  alloy:\n    image: grafana/alloy:v1.5.1\n',
  parameters: [],
  source: 'builtin',
  auto_start: false,
  first_service: 'alloy',
}

function openDeployStep() {
  return renderWithProviders(
    <ServiceLaunchDialog
      open
      onOpenChange={() => {}}
      nodeId="host-test-106-1"
      nodeLabel="test1"
      wsName="devpod"
    />,
  )
}

describe('ServiceLaunchDialog', () => {
  it('pré-remplit le nom avec {premier service}-{workspace} et active Start', async () => {
    server.use(http.get('/api/compose/templates', () => HttpResponse.json([ALLOY_TEMPLATE])))
    const user = userEvent.setup()
    openDeployStep()

    await user.click(await screen.findByText('Collecteur de logs (Alloy)'))

    const nameInput = await screen.findByLabelText(/name|nom/i)
    expect(nameInput).toHaveValue('alloy-devpod')
    expect(screen.getByRole('button', { name: /start|démarrer/i })).toBeEnabled()
  })

  it("laisse le champ vide si le template n'a pas de service identifiable", async () => {
    server.use(
      http.get('/api/compose/templates', () =>
        HttpResponse.json([{ ...ALLOY_TEMPLATE, first_service: null }])),
    )
    const user = userEvent.setup()
    openDeployStep()

    await user.click(await screen.findByText('Collecteur de logs (Alloy)'))

    const nameInput = await screen.findByLabelText(/name|nom/i)
    expect(nameInput).toHaveValue('')
    expect(screen.getByRole('button', { name: /start|démarrer/i })).toBeDisabled()
  })
})
