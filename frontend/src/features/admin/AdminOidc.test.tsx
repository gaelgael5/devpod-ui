import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import AdminOidc from './AdminOidc'

const GRAFANA_OIDC = {
  client_id: 'agflow-grafana',
  has_secret: false,
  auth_url: null,
  token_url: null,
  userinfo_url: null,
  redirect_uri: null,
  grafana_url: null,
}

describe('AdminOidc', () => {
  it('rend le formulaire pré-rempli avec issuer et client_id', async () => {
    server.use(
      http.get('/admin/oidc', () =>
        HttpResponse.json({ issuer: 'https://iss', client_id: 'cid', has_secret: true }),
      ),
      http.get('/admin/grafana-oidc', () => HttpResponse.json(GRAFANA_OIDC)),
    )
    renderWithProviders(<AdminOidc />)

    expect(await screen.findByDisplayValue('https://iss')).toBeInTheDocument()
    expect(screen.getByDisplayValue('cid')).toBeInTheDocument()
    // Le secret n'est jamais pré-rempli (champ vide).
    const secret = screen.getByLabelText(/client secret/i) as HTMLInputElement
    expect(secret.value).toBe('')
  })

  it('sépare la config portail et Grafana dans des onglets distincts', async () => {
    server.use(
      http.get('/admin/oidc', () =>
        HttpResponse.json({ issuer: 'https://iss', client_id: 'cid', has_secret: true }),
      ),
      http.get('/admin/grafana-oidc', () => HttpResponse.json(GRAFANA_OIDC)),
    )
    const user = userEvent.setup()
    renderWithProviders(<AdminOidc />)

    await screen.findByDisplayValue('https://iss')
    expect(screen.queryByDisplayValue('agflow-grafana')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Grafana' }))
    expect(await screen.findByDisplayValue('agflow-grafana')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('https://iss')).not.toBeInTheDocument()
  })
})
