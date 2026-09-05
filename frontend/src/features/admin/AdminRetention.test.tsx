/**
 * Les délais de rétention : deux nombres qui gouvernent une destruction.
 *
 * Ce qui est verrouillé : les valeurs servies s'affichent, l'enregistrement
 * envoie ce qui est saisi, et un délai sous 1 jour bloque le bouton avec son
 * explication — plutôt que de laisser le 422 backend arriver en toast.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminRetention from './AdminRetention'

let corpsEnvoye: unknown

function servir(config = { echec_paiement_jours: 14, resiliation_jours: 30 }) {
  server.use(
    http.get('/admin/billing/retention/config', () => HttpResponse.json(config)),
    http.put('/admin/billing/retention/config', async ({ request }) => {
      corpsEnvoye = await request.json()
      return HttpResponse.json(corpsEnvoye)
    }),
  )
}

describe('AdminRetention', () => {
  it('affiche les délais servis', async () => {
    servir({ echec_paiement_jours: 7, resiliation_jours: 60 })
    renderWithProviders(<AdminRetention />)

    expect(await screen.findByLabelText(i18n.t('admin.retention.echec'))).toHaveValue(7)
    expect(screen.getByLabelText(i18n.t('admin.retention.resiliation'))).toHaveValue(60)
  })

  it('enregistre ce qui est saisi', async () => {
    servir()
    renderWithProviders(<AdminRetention />)
    const champ = await screen.findByLabelText(i18n.t('admin.retention.resiliation'))

    await userEvent.clear(champ)
    await userEvent.type(champ, '45')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(corpsEnvoye).toEqual({ echec_paiement_jours: 14, resiliation_jours: 45 })
  })

  it('refuse un délai sous un jour, avec son explication', async () => {
    servir()
    renderWithProviders(<AdminRetention />)
    const champ = await screen.findByLabelText(i18n.t('admin.retention.echec'))

    await userEvent.clear(champ)
    await userEvent.type(champ, '0')

    expect(screen.getByText(i18n.t('admin.retention.minimum'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('common.save') })).toBeDisabled()
  })
})
