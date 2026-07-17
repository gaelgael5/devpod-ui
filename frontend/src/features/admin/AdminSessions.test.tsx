import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminSessions from './AdminSessions'

describe('AdminSessions', () => {
  it('pré-remplit les champs en minutes depuis les secondes du backend', async () => {
    server.use(
      http.get('/admin/sessions', () =>
        HttpResponse.json({ session_max_age: 7200, session_absolute_max_age: 43200 }),
      ),
    )
    renderWithProviders(<AdminSessions />)

    // 7200 s → 120 min, 43200 s → 720 min
    expect(await screen.findByDisplayValue('120')).toBeInTheDocument()
    expect(screen.getByDisplayValue('720')).toBeInTheDocument()
  })

  it('enregistre en reconvertissant les minutes en secondes', async () => {
    let sent: unknown = null
    server.use(
      http.get('/admin/sessions', () =>
        HttpResponse.json({ session_max_age: 7200, session_absolute_max_age: 43200 }),
      ),
      http.put('/admin/sessions', async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json(sent)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminSessions />)

    const idle = await screen.findByDisplayValue('120')
    await user.clear(idle)
    await user.type(idle, '30') // 30 min → 1800 s
    await user.click(screen.getByRole('button', { name: /save|enregistrer/i }))

    await waitFor(() =>
      expect(sent).toEqual({ session_max_age: 1800, session_absolute_max_age: 43200 }),
    )
  })

  it('refuse un plafond absolu inférieur à l’inactivité (pas d’appel backend)', async () => {
    let called = false
    server.use(
      http.get('/admin/sessions', () =>
        HttpResponse.json({ session_max_age: 7200, session_absolute_max_age: 43200 }),
      ),
      http.put('/admin/sessions', () => {
        called = true
        return HttpResponse.json({})
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminSessions />)

    const absolute = await screen.findByDisplayValue('720')
    await user.clear(absolute)
    await user.type(absolute, '60') // 60 min < 120 min d'idle → rejeté
    await user.click(screen.getByRole('button', { name: /save|enregistrer/i }))

    await new Promise((r) => setTimeout(r, 50))
    expect(called).toBe(false)
  })
})
