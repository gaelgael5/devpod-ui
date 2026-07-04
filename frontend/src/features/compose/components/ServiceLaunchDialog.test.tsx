import { screen, waitFor } from '@testing-library/react'
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

function openDeployStep(namingHint?: string) {
  return renderWithProviders(
    <ServiceLaunchDialog
      open
      onOpenChange={() => {}}
      nodeId="host-test-106-1"
      nodeLabel="test1"
      namingHint={namingHint}
    />,
  )
}

describe('ServiceLaunchDialog', () => {
  it('pré-remplit le nom avec {premier service}-{workspace} et active Start', async () => {
    server.use(http.get('/api/compose/templates', () => HttpResponse.json([ALLOY_TEMPLATE])))
    const user = userEvent.setup()
    openDeployStep('devpod')

    await user.click(await screen.findByText('Collecteur de logs (Alloy)'))

    const nameInput = await screen.findByLabelText(/name|nom/i)
    expect(nameInput).toHaveValue('alloy-devpod')
    expect(screen.getByRole('button', { name: /start|démarrer/i })).toBeEnabled()
  })

  it('pré-remplit le nom avec le seul premier service quand aucune suggestion de nommage n\'est fournie', async () => {
    server.use(http.get('/api/compose/templates', () => HttpResponse.json([ALLOY_TEMPLATE])))
    const user = userEvent.setup()
    openDeployStep()

    await user.click(await screen.findByText('Collecteur de logs (Alloy)'))

    const nameInput = await screen.findByLabelText(/name|nom/i)
    expect(nameInput).toHaveValue('alloy')
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

  it(
    'bug 020 : annule le fetch de streaming (AbortSignal) quand le composant se démonte en ' +
      'cours de déploiement, au lieu de laisser le backend streamer dans le vide',
    async () => {
      let capturedSignal: AbortSignal | undefined
      server.use(
        http.get('/api/compose/templates', () => HttpResponse.json([ALLOY_TEMPLATE])),
        http.post('/api/compose/deployments/stream', ({ request }) => {
          capturedSignal = request.signal
          // Stream qui ne se termine jamais dans la fenêtre du test — simule un
          // déploiement encore en cours au moment où l'utilisateur ferme le dialog.
          const stream = new ReadableStream({
            start(controller) {
              controller.enqueue(new TextEncoder().encode('==> starting\n'))
            },
          })
          return new HttpResponse(stream, { headers: { 'Content-Type': 'text/plain' } })
        }),
      )
      const user = userEvent.setup()
      const { unmount } = openDeployStep()

      await user.click(await screen.findByText('Collecteur de logs (Alloy)'))
      await user.click(screen.getByRole('button', { name: /start|démarrer/i }))
      await screen.findByText(/starting/)

      expect(capturedSignal?.aborted).toBe(false)
      unmount()

      await waitFor(() => expect(capturedSignal?.aborted).toBe(true))
    },
  )
})
