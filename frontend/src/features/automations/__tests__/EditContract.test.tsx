import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import AdminContracts from '../AdminContracts'

const CONTRACT = {
  id: 'c1',
  label: 'Termix',
  source_url: 'https://termix.example.org/openapi.json',
  version: '1.0.0',
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
}

describe('AdminContracts — édition', () => {
  it('renomme un contrat via PATCH', async () => {
    server.use(http.get('/admin/automations/contracts', () => HttpResponse.json([CONTRACT])))
    const patched = vi.fn()
    server.use(
      http.patch('/admin/automations/contracts/c1', async ({ request }) => {
        patched(await request.json())
        return HttpResponse.json({ ...CONTRACT, label: 'Termix v2' })
      }),
    )

    renderWithProviders(<AdminContracts />, { route: '/admin/automations/contracts' })
    // Ouvre le dialogue d'édition
    fireEvent.click(await screen.findByRole('button', { name: /éditer|edit/i }))
    const input = await screen.findByLabelText(/libellé|label/i)
    fireEvent.change(input, { target: { value: 'Termix v2' } })
    fireEvent.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() => expect(patched).toHaveBeenCalledWith({ label: 'Termix v2' }))
  })
})
