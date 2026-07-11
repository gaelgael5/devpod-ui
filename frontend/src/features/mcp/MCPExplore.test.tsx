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

  it('recherche dans une source et affiche les résultats', async () => {
    let searchUrl = ''
    server.use(
      http.get('/me/secrets', () => HttpResponse.json([])),
      http.get('/me/mcp/discovery-sources', () =>
        HttpResponse.json([
          { id: 7, label: 'Yoops', slug: 'yoops', url: 'https://mcp.yoops.org', secret_slug: '' },
        ]),
      ),
      http.get('/me/mcp/discovery-sources/7/search', ({ request }) => {
        searchUrl = request.url
        return HttpResponse.json({
          items: [
            {
              id: 42,
              name: 'io.github.owner/repo',
              description: 'un serveur de test',
              transport: 'stdio',
              category: 'dev',
              stars: 12,
              repo_status: 'active',
              source_url: 'https://github.com/owner/repo',
              doc_url: '',
            },
          ],
          total: 1,
          page: 1,
          per_page: 10,
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPExplore />)

    // La source unique est auto-sélectionnée : pas de sélecteur affiché.
    const input = await screen.findByPlaceholderText('Search the catalog…')
    await user.type(input, 'git')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(screen.getByText('io.github.owner/repo')).toBeInTheDocument())
    expect(searchUrl).toContain('q=git')
    expect(screen.getByText('un serveur de test')).toBeInTheDocument()
    expect(screen.getByText('stdio')).toBeInTheDocument()
    // Lien dépôt présent, lien doc absent (doc_url vide).
    expect(screen.getByRole('link', { name: /Repository/ })).toHaveAttribute(
      'href',
      'https://github.com/owner/repo',
    )
    expect(screen.queryByRole('link', { name: /Docs/ })).not.toBeInTheDocument()
  })
})
