import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminOidc from './AdminOidc'

describe('AdminOidc', () => {
  it('rend le formulaire pré-rempli avec issuer et client_id', async () => {
    server.use(
      http.get('/admin/oidc', () =>
        HttpResponse.json({ issuer: 'https://iss', client_id: 'cid', has_secret: true }),
      ),
    )
    renderWithProviders(<AdminOidc />)

    expect(await screen.findByDisplayValue('https://iss')).toBeInTheDocument()
    expect(screen.getByDisplayValue('cid')).toBeInTheDocument()
    // Le secret n'est jamais pré-rempli (champ vide).
    const secret = screen.getByLabelText(/client secret/i) as HTMLInputElement
    expect(secret.value).toBe('')
  })
})
