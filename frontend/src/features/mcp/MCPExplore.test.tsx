import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPExplore from './MCPExplore'

function stubEndpoints() {
  server.use(
    http.get('/me/secrets', () =>
      HttpResponse.json([{ slug: 'yoops-key', label: 'Yoops discovery key' }]),
    ),
    http.get('/me/mcp/discovery-sources', () => HttpResponse.json([])),
  )
}

describe('MCPExplore', () => {
  it('dérive le slug du label et crée une source', async () => {
    let created: unknown = null
    stubEndpoints()
    server.use(
      http.post('/me/mcp/discovery-sources', async ({ request }) => {
        created = await request.json()
        return HttpResponse.json({ id: 1, label: 'Yoops Hub', slug: 'yoops-hub' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPExplore />)

    await user.type(screen.getByLabelText('Label'), 'Yoops Hub')
    // Le slug est auto-dérivé.
    expect(screen.getByLabelText('Slug')).toHaveValue('yoops-hub')
    await user.type(screen.getByLabelText('Service URL'), 'https://mcp.yoops.org')

    await user.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(created).not.toBeNull())
    expect(created).toEqual({
      label: 'Yoops Hub',
      slug: 'yoops-hub',
      url: 'https://mcp.yoops.org',
      secret_slug: '',
    })
  })

  it('teste une source via le endpoint probe', async () => {
    let probed: unknown = null
    stubEndpoints()
    server.use(
      http.post('/me/mcp/discovery-sources/probe', async ({ request }) => {
        probed = await request.json()
        return HttpResponse.json({ ok: true, name: 'test1', email: null })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPExplore />)

    // Bouton Test désactivé tant que l'URL est vide.
    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled()
    await user.type(screen.getByLabelText('Service URL'), 'https://mcp.yoops.org')
    await user.click(screen.getByRole('button', { name: 'Test' }))

    await waitFor(() => expect(probed).not.toBeNull())
    expect(probed).toEqual({ url: 'https://mcp.yoops.org', secret_slug: '' })
  })
})
