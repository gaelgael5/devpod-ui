import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import GrafanaOidcSection from './GrafanaOidcSection'

describe('GrafanaOidcSection', () => {
  it('pré-remplit le client_id avec la valeur par défaut agflow-grafana', async () => {
    server.use(
      http.get('/admin/grafana-oidc', () =>
        HttpResponse.json({
          client_id: 'agflow-grafana',
          has_secret: false,
          auth_url: null,
          token_url: null,
          userinfo_url: null,
          redirect_uri: null,
          grafana_url: null,
        }),
      ),
    )
    renderWithProviders(<GrafanaOidcSection />)
    expect(await screen.findByDisplayValue('agflow-grafana')).toBeInTheDocument()
    // Le secret n'est jamais pré-rempli.
    const secret = screen.getByLabelText(/client secret|secret client/i) as HTMLInputElement
    expect(secret.value).toBe('')
  })

  it("avertit quand l'issuer OIDC du portail n'est pas configuré", async () => {
    server.use(
      http.get('/admin/grafana-oidc', () =>
        HttpResponse.json({
          client_id: 'agflow-grafana',
          has_secret: false,
          auth_url: null,
          token_url: null,
          userinfo_url: null,
          redirect_uri: null,
          grafana_url: null,
        }),
      ),
    )
    renderWithProviders(<GrafanaOidcSection />)
    expect(
      await screen.findByText(/configure the portal oidc issuer|configurez d'abord l'issuer/i)
    ).toBeInTheDocument()
  })

  it('affiche les endpoints Keycloak dérivés et le guide avec redirect_uri copiable', async () => {
    server.use(
      http.get('/admin/grafana-oidc', () =>
        HttpResponse.json({
          client_id: 'agflow-grafana',
          has_secret: true,
          auth_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/auth',
          token_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/token',
          userinfo_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/userinfo',
          redirect_uri: 'http://192.168.10.196:3001/login/generic_oauth',
          grafana_url: 'http://192.168.10.196:3001',
        }),
      ),
    )
    renderWithProviders(<GrafanaOidcSection />)
    expect(
      await screen.findByText('https://security.yoops.org/realms/yoops/protocol/openid-connect/auth')
    ).toBeInTheDocument()
    expect(
      screen.getByText('http://192.168.10.196:3001/login/generic_oauth')
    ).toBeInTheDocument()
  })

  it('enregistre client_id et secret, puis vide le champ secret', async () => {
    const user = userEvent.setup()
    let putBody: unknown = null
    server.use(
      http.get('/admin/grafana-oidc', () =>
        HttpResponse.json({
          client_id: 'agflow-grafana',
          has_secret: false,
          auth_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/auth',
          token_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/token',
          userinfo_url: 'https://security.yoops.org/realms/yoops/protocol/openid-connect/userinfo',
          redirect_uri: 'http://192.168.10.196:3001/login/generic_oauth',
          grafana_url: 'http://192.168.10.196:3001',
        }),
      ),
      http.put('/admin/grafana-oidc', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ client_id: 'agflow-grafana', has_secret: true })
      }),
    )
    renderWithProviders(<GrafanaOidcSection />)
    await screen.findByDisplayValue('agflow-grafana')

    const secret = screen.getByLabelText(/client secret|secret client/i)
    await user.type(secret, 'my-secret')
    await user.click(screen.getByRole('button', { name: /^(save|enregistrer)$/i }))

    await waitFor(() => {
      expect(putBody).toMatchObject({ client_id: 'agflow-grafana', client_secret: 'my-secret' })
    })
    expect((secret as HTMLInputElement).value).toBe('')
  })
})
