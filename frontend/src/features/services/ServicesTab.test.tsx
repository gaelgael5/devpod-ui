// frontend/src/features/services/ServicesTab.test.tsx
/** Registre de services (hub Services & Security) : liste, création, édition, suppression. */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import ServicesTab from './ServicesTab'

const PROFILE = { id: 'p1', owner_login: 'alice', name: 'Ops', description: '', created_at: '', updated_at: null }

const SERVICE = {
  id: 's1',
  owner_login: 'alice',
  name: 'Grafana',
  url: 'https://grafana.example.org',
  mcp_profile_id: 'p1',
  mcp_profile_name: 'Ops',
  created_at: '2026-07-05T00:00:00Z',
  updated_at: null,
}

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('ServicesTab', () => {
  it('affiche la liste des services avec leur profil MCP', async () => {
    server.use(
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
    )
    renderWithProviders(<ServicesTab />)

    expect(await screen.findByText('Grafana')).toBeInTheDocument()
    expect(screen.getByText('Ops')).toBeInTheDocument()
    expect(screen.getByText('https://grafana.example.org')).toBeInTheDocument()
  })

  it("affiche un état vide sans service", async () => {
    server.use(
      http.get('/me/services', () => HttpResponse.json([])),
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
    )
    renderWithProviders(<ServicesTab />)
    expect(await screen.findByText(/aucun service|no registered service/i)).toBeInTheDocument()
  })

  it("indique l'absence de profil quand mcp_profile_name est null", async () => {
    server.use(
      http.get('/me/services', () =>
        HttpResponse.json([{ ...SERVICE, mcp_profile_id: null, mcp_profile_name: null }])),
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
    )
    renderWithProviders(<ServicesTab />)
    expect(await screen.findByText(/aucun profil|no profile/i)).toBeInTheDocument()
  })

  it('crée un service (POST) avec le profil choisi', async () => {
    let posted: unknown = null
    server.use(
      http.get('/me/services', () => HttpResponse.json([])),
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
      http.post('/me/services', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ id: 'new' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ServicesTab />)

    await user.click(await screen.findByRole('button', { name: /ajouter un service|add a service/i }))
    await user.type(screen.getByLabelText(/^nom$|^name$/i), 'Docs')
    await user.type(screen.getByLabelText(/^url$/i), 'https://docs.example.org')
    await user.click(screen.getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Ops' }))
    await user.click(screen.getByRole('button', { name: /^(save|enregistrer)$/i }))

    await waitFor(() =>
      expect(posted).toEqual({ name: 'Docs', url: 'https://docs.example.org', mcp_profile_id: 'p1' }),
    )
  })

  it('supprime un service (DELETE) après confirmation', async () => {
    let deleted = false
    server.use(
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.get('/me/mcp/profiles', () => HttpResponse.json([PROFILE])),
      http.delete('/me/services/:id', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ServicesTab />)

    await screen.findByText('Grafana')
    const deleteButtons = screen.getAllByRole('button')
    const trashBtn = deleteButtons.find((b) => b.className.includes('destructive'))
    expect(trashBtn).toBeDefined()
    await user.click(trashBtn!)
    await user.click(await screen.findByRole('button', { name: /confirmer la suppression|confirm deletion/i }))

    await waitFor(() => expect(deleted).toBe(true))
  })
})
