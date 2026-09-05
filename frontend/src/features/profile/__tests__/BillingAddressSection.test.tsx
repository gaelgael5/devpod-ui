/**
 * L'adresse de facturation au profil.
 *
 * Ce qui est verrouillé : l'adresse servie pré-remplit le formulaire,
 * l'enregistrement envoie la structure attendue par le backend (pays normalisé
 * en majuscules), et le bouton reste inerte tant que les champs obligatoires
 * manquent.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import BillingAddressSection from '../BillingAddressSection'

let corpsEnvoye: unknown

const ADRESSE = {
  line1: '12 rue des Lilas',
  line2: '',
  city: 'Lyon',
  postal_code: '69003',
  state: '',
  country: 'FR',
}

function servir(adresse: unknown = null) {
  server.use(
    http.get('/me/billing-address', () => HttpResponse.json(adresse)),
    http.put('/me/billing-address', async ({ request }) => {
      corpsEnvoye = await request.json()
      return HttpResponse.json(corpsEnvoye)
    }),
  )
}

describe('BillingAddressSection', () => {
  it("pré-remplit avec l'adresse servie", async () => {
    servir(ADRESSE)
    renderWithProviders(<BillingAddressSection />)

    expect(await screen.findByLabelText(i18n.t('profile.billingAddress.line1'))).toHaveValue(
      '12 rue des Lilas',
    )
    expect(screen.getByLabelText(i18n.t('profile.billingAddress.country'))).toHaveValue('FR')
  })

  it('enregistre la structure attendue, pays en majuscules', async () => {
    servir(ADRESSE)
    renderWithProviders(<BillingAddressSection />)
    const pays = await screen.findByLabelText(i18n.t('profile.billingAddress.country'))

    await userEvent.clear(pays)
    await userEvent.type(pays, 'be')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(corpsEnvoye).toEqual({ ...ADRESSE, country: 'BE' })
  })

  it('reste inerte tant que les champs obligatoires manquent', async () => {
    servir(null)
    renderWithProviders(<BillingAddressSection />)

    const bouton = await screen.findByRole('button', { name: i18n.t('common.save') })
    expect(bouton).toBeDisabled()
  })
})
