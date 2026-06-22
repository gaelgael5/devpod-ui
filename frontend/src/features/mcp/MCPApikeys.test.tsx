import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPApikeys from './MCPApikeys'

describe('MCPApikeys', () => {
  it('affiche l\'état vide quand aucune apikey', async () => {
    renderWithProviders(<MCPApikeys />)
    expect(await screen.findByText(/No apikey issued/i)).toBeInTheDocument()
  })

  it('crée une apikey et affiche le token clair une seule fois', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/apikeys', () => HttpResponse.json([])),
      http.post('/me/mcp/apikeys', () =>
        HttpResponse.json({ id: 'a1', token: 'mcpk_secret_once' }, { status: 201 })),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    await user.click(await screen.findByRole('button', { name: /Issue an apikey/i }))
    await user.click(await screen.findByRole('button', { name: /^Save$/i }))

    await waitFor(() => expect(screen.getByText('mcpk_secret_once')).toBeInTheDocument())
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument()
  })
})
