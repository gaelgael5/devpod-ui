import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostStacks from './TestHostStacks'

const STACKS = [
  { name: 'chromium', status: 'running(1)', configFiles: '/opt/a/docker-compose.yml' },
  { name: 'legacy-app', status: 'exited(2)', configFiles: '/opt/b/compose.yml' },
]

function seed(stacks = STACKS) {
  server.use(
    http.get('/me/workspaces/:ws/test-hosts/:host/stacks', () => HttpResponse.json(stacks)),
  )
}

describe('TestHostStacks', () => {
  it('affiche les stacks live non gérées par le portail', async () => {
    seed()
    renderWithProviders(
      <TestHostStacks wsName="ws1" hostName="h1" enabled excludeNames={['chromium']} />,
    )
    // chromium est déjà géré par le portail (exclu) ; legacy-app (live) apparaît.
    expect(await screen.findByText('legacy-app')).toBeInTheDocument()
    expect(screen.queryByText('chromium')).not.toBeInTheDocument()
    expect(screen.getByText('exited(2)')).toBeInTheDocument()
  })

  it('ne rend rien quand toutes les stacks sont déjà gérées par le portail', async () => {
    seed()
    const { container } = renderWithProviders(
      <TestHostStacks
        wsName="ws1"
        hostName="h1"
        enabled
        excludeNames={['chromium', 'legacy-app']}
      />,
    )
    await waitFor(() => expect(container.querySelector('.font-mono')).not.toBeInTheDocument())
    expect(screen.queryByText(/autres stacks|other docker stacks/i)).not.toBeInTheDocument()
  })
})
