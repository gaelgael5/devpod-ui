import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import RequireAuth from './RequireAuth'

function Protected() {
  return <div>protected content</div>
}

describe('RequireAuth', () => {
  it('affiche le contenu si authentifié', async () => {
    renderWithProviders(
      <RequireAuth>
        <Protected />
      </RequireAuth>
    )
    await waitFor(() => {
      expect(screen.getByText('protected content')).toBeInTheDocument()
    })
  })

  it('redirige vers /auth/login si GET /me retourne 401', async () => {
    server.use(http.get('/me', () => new HttpResponse(null, { status: 401 })))
    // le redirect est géré par apiFetch (window.location.href) — on vérifie juste
    // que le contenu protégé n'est PAS rendu
    renderWithProviders(
      <RequireAuth>
        <Protected />
      </RequireAuth>
    )
    await waitFor(() => {
      expect(screen.queryByText('protected content')).not.toBeInTheDocument()
    })
  })
})
