/**
 * Choix de la langue du compte.
 *
 * Ce que ces tests verrouillent : le choix part au SERVEUR. Un reglage qui ne
 * vivrait que dans le localStorage laisserait la base a `fr` pour un
 * utilisateur anglophone — et les messages qu'on lui envoie suivraient une
 * langue qu'il n'a jamais demandee.
 */
import { waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import ProfilePage from '../ProfilePage'

function mockProfil(culture = 'fr') {
  server.use(
    http.get('/me/profile', () =>
      HttpResponse.json({ login: 'gael', email: '', display_name: '', identity: '' }),
    ),
    http.get('/me/token-claims', () => HttpResponse.json({ claims: {} })),
    http.get('/me/termix-instances', () => HttpResponse.json([])),
    http.get('/me/config', () => HttpResponse.json({ culture })),
  )
}

describe('CultureBlock', () => {
  it('affiche la culture enregistree sur le serveur', async () => {
    mockProfil('en')
    const { findByLabelText } = renderWithProviders(<ProfilePage />, { route: '/profile' })

    const select = (await findByLabelText(/langue du compte|account language/i)) as HTMLSelectElement
    // Le champ est monte avant la reponse du serveur : on attend qu'il porte la
    // valeur enregistree, pas la premiere option de la liste.
    await waitFor(() => expect(select.value).toBe('en'))
  })

  it('enregistre le changement cote serveur', async () => {
    mockProfil('fr')
    let recu: unknown = null
    server.use(
      http.put('/me/config', async ({ request }) => {
        recu = await request.json()
        return HttpResponse.json({ culture: 'en' })
      }),
    )
    const { findByLabelText } = renderWithProviders(<ProfilePage />, { route: '/profile' })

    const select = (await findByLabelText(/langue du compte|account language/i)) as HTMLSelectElement
    // Desactive tant que la culture n'est pas chargee : agir avant ne ferait rien.
    await waitFor(() => expect(select).not.toBeDisabled())
    await userEvent.selectOptions(select, 'en')

    await waitFor(() => expect(recu).toEqual({ culture: 'en' }))
  })
})
