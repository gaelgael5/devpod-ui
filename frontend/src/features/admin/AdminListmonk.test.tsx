/**
 * La connexion Listmonk : la clef se CHOISIT, le test dit pourquoi il échoue.
 *
 * Ce qui est verrouillé : le sélecteur est alimenté par les secrets système
 * (jamais un slug tapé à la main), activer sans contrat complet bloque
 * l'enregistrement, et un refus du test affiche le MOTIF de Listmonk.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Toaster } from 'sonner'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminListmonk from './AdminListmonk'

let corpsEnvoye: unknown

function servir(
  config = { enabled: false, url: '', apikey_secret: '' },
  test: unknown = { ok: true, status_code: 200, motif: '' },
) {
  server.use(
    http.get('/admin/listmonk', () => HttpResponse.json(config)),
    http.put('/admin/listmonk', async ({ request }) => {
      corpsEnvoye = await request.json()
      return HttpResponse.json(corpsEnvoye)
    }),
    http.post('/admin/listmonk/test-connection', () => HttpResponse.json(test)),
    http.get('/admin/automations/secrets', () =>
      HttpResponse.json([
        { slug: 'listmonk-api', label: 'Listmonk API', secret_type: 'CI_PASSWORD', storage_type: 'local' },
      ]),
    ),
  )
}

describe('AdminListmonk', () => {
  it('la clef se choisit parmi les secrets système', async () => {
    servir()
    renderWithProviders(<AdminListmonk />)

    expect(await screen.findByRole('option', { name: 'Listmonk API' })).toBeInTheDocument()
  })

  it("enregistre l'URL et le slug choisi — jamais une valeur de clef", async () => {
    servir()
    renderWithProviders(<AdminListmonk />)

    await userEvent.type(await screen.findByLabelText(i18n.t('admin.listmonk.url')), 'https://lm.example')
    await screen.findByRole('option', { name: 'Listmonk API' })
    await userEvent.selectOptions(screen.getByLabelText(i18n.t('admin.listmonk.secret')), 'listmonk-api')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(corpsEnvoye).toEqual({
      enabled: false,
      url: 'https://lm.example',
      apikey_secret: 'listmonk-api',
    })
  })

  it('activer sans contrat complet bloque avec son explication', async () => {
    servir()
    renderWithProviders(<AdminListmonk />)

    await userEvent.click(await screen.findByLabelText(i18n.t('admin.listmonk.enabled')))

    expect(screen.getByText(i18n.t('admin.listmonk.missing'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('common.save') })).toBeDisabled()
  })

  it('un refus du test affiche le motif de Listmonk', async () => {
    servir(
      { enabled: true, url: 'https://lm.example', apikey_secret: 'listmonk-api' },
      { ok: false, status_code: 403, motif: 'invalid API credentials' },
    )
    renderWithProviders(
      <>
        <AdminListmonk />
        <Toaster />
      </>,
    )

    await userEvent.click(
      await screen.findByRole('button', { name: i18n.t('admin.listmonk.test') }),
    )

    expect(
      await screen.findByText(
        i18n.t('admin.listmonk.testFail', { detail: 'invalid API credentials' }),
      ),
    ).toBeInTheDocument()
  })
})
