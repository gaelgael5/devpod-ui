import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostStacks from './TestHostStacks'

const DOCKER = {
  stacks: [
    { name: 'chromium', status: 'running(1)', configFiles: '/opt/a/docker-compose.yml' },
    { name: 'legacy-app', status: 'exited(2)', configFiles: '/opt/b/compose.yml' },
  ],
  containers: [{ name: 'pg-manual', image: 'postgres:16', state: 'running', status: 'Up 3h' }],
}

function seed(payload = DOCKER) {
  server.use(
    http.get('/me/workspaces/:ws/test-hosts/:host/stacks', () => HttpResponse.json(payload)),
  )
}

describe('TestHostStacks', () => {
  it('affiche les stacks live (hors portail) et les conteneurs hors compose', async () => {
    seed()
    renderWithProviders(
      <TestHostStacks wsName="ws1" hostName="h1" enabled excludeNames={['chromium']} />,
    )
    // chromium géré par le portail → exclu ; legacy-app (stack) + pg-manual (conteneur) affichés.
    expect(await screen.findByText('legacy-app')).toBeInTheDocument()
    expect(screen.getByText('pg-manual')).toBeInTheDocument()
    expect(screen.queryByText('chromium')).not.toBeInTheDocument()
    expect(screen.getByText(/conteneurs hors compose|non-compose containers/i)).toBeInTheDocument()
  })

  it('ne rend rien quand il n’y a ni stack extra ni conteneur', async () => {
    seed({ stacks: [{ name: 'chromium', status: 'running(1)', configFiles: '' }], containers: [] })
    const { container } = renderWithProviders(
      <TestHostStacks wsName="ws1" hostName="h1" enabled excludeNames={['chromium']} />,
    )
    await waitFor(() => expect(container.querySelector('.font-mono')).not.toBeInTheDocument())
  })
})
