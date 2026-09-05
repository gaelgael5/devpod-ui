/**
 * Le parcours guidé (fiche 849978e7).
 *
 * Ce qui est verrouillé : la bulle n'apparaît que sur la page de l'étape
 * courante (pause silencieuse ailleurs), Next avance l'index persisté, Close
 * masque sans avancer, Désactiver écrit le drapeau, et rien ne s'affiche quand
 * le parcours est terminé ou désactivé.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import OnboardingOverlay from './OnboardingOverlay'
import { ONBOARDING_STEPS } from './steps'

let ecrits: Array<{ key: string; body: unknown }>

function servir(prefs: Record<string, unknown>) {
  ecrits = []
  server.use(
    http.get('/me/preferences', () => HttpResponse.json(prefs)),
    http.put('/me/preferences/:key', async ({ params, request }) => {
      ecrits.push({ key: String(params.key), body: await request.json() })
      return new HttpResponse(null, { status: 204 })
    }),
  )
}

// Étape 0 = profil, sur /profile.
const ETAPE0 = ONBOARDING_STEPS[0]

describe('OnboardingOverlay', () => {
  it('affiche la bulle de l\'étape courante sur SA page', async () => {
    servir({ onboarding_step: 0 })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })

    expect(await screen.findByTestId('onboarding-bulle')).toBeInTheDocument()
    expect(
      screen.getByText(i18n.t(`onboarding.steps.${ETAPE0.key}.title`)),
    ).toBeInTheDocument()
  })

  it('pause silencieuse : pas de bulle sur une autre page, mais les contrôles restent', async () => {
    servir({ onboarding_step: 0 })
    renderWithProviders(<OnboardingOverlay />, { route: '/une/autre/page' })

    expect(screen.queryByTestId('onboarding-bulle')).not.toBeInTheDocument()
    // Les contrôles globaux sont accessibles depuis n'importe quelle page.
    expect(screen.getByRole('button', { name: i18n.t('onboarding.reouvrir') })).toBeInTheDocument()
  })

  it('Next avance l\'index persisté', async () => {
    servir({ onboarding_step: 0 })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })

    await userEvent.click(await screen.findByRole('button', { name: i18n.t('onboarding.suivant') }))

    expect(ecrits).toContainEqual({ key: 'onboarding_step', body: { int: 1 } })
  })

  it('Close masque la bulle sans rien persister', async () => {
    servir({ onboarding_step: 0 })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })
    await screen.findByTestId('onboarding-bulle')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.fermer') }))

    expect(screen.queryByTestId('onboarding-bulle')).not.toBeInTheDocument()
    expect(ecrits).toEqual([])
  })

  it('Désactiver écrit le drapeau', async () => {
    servir({ onboarding_step: 0 })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })
    await screen.findByTestId('onboarding-bulle')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.desactiver') }))

    expect(ecrits).toContainEqual({ key: 'onboarding_disabled', body: { bool: true } })
  })

  it('rien ne s\'affiche quand le parcours est désactivé', async () => {
    servir({ onboarding_step: 0, onboarding_disabled: true })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })

    // Laisse le temps au fetch de prefs de résoudre.
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId('onboarding-bulle')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('onboarding.reouvrir') })).not.toBeInTheDocument()
  })

  it('rien ne s\'affiche quand le parcours est terminé', async () => {
    servir({ onboarding_step: ONBOARDING_STEPS.length })
    renderWithProviders(<OnboardingOverlay />, { route: ETAPE0.path })

    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByRole('button', { name: i18n.t('onboarding.reouvrir') })).not.toBeInTheDocument()
  })
})
