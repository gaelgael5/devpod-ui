import { useLocation } from 'react-router-dom'
import { useUserPreferences, useSetPreference, type PrefValue } from '@/shared/hooks/useUserPreferences'
import {
  ONBOARDING_DISABLED_PREF,
  ONBOARDING_STEP_PREF,
  ONBOARDING_STEPS,
  type OnboardingStep,
} from './steps'

/**
 * L'état du parcours guidé, dérivé des préférences serveur (fiche 849978e7).
 *
 * La progression est un simple index d'étape persisté (`onboarding_step`), la
 * séquence étant plate. `onboarding_disabled` l'arrête définitivement.
 *
 * Ce hook ne connaît PAS l'état « bulle fermée pour cette session » (bouton
 * Close) : c'est de l'affichage local, porté par le composant. Ici vit ce qui
 * survit d'une connexion à l'autre — l'index et le drapeau désactivé.
 */
export interface OnboardingState {
  /** L'étape courante quelle que soit la page (null si parcours fini/désactivé). */
  etapeCourante: OnboardingStep | null
  /** Vrai si l'utilisateur est sur la page de l'étape courante. */
  surLaPage: boolean
  index: number
  total: number
  actif: boolean
  /** « Next » : passe à l'étape suivante. */
  suivant: () => void
  /** « Désactiver » : arrêt définitif. */
  desactiver: () => void
}

function toInt(v: PrefValue | undefined): number {
  return typeof v === 'number' ? v : 0
}

export function useOnboarding(): OnboardingState {
  const { data: prefs } = useUserPreferences()
  const setPref = useSetPreference()
  const location = useLocation()

  const index = toInt(prefs?.[ONBOARDING_STEP_PREF])
  const desactive = prefs?.[ONBOARDING_DISABLED_PREF] === true
  const actif = !desactive && index < ONBOARDING_STEPS.length
  const etapeCourante = actif ? ONBOARDING_STEPS[index] : null

  return {
    etapeCourante,
    surLaPage: etapeCourante !== null && location.pathname === etapeCourante.path,
    index,
    total: ONBOARDING_STEPS.length,
    actif,
    suivant: () => setPref.mutate({ key: ONBOARDING_STEP_PREF, value: index + 1 }),
    desactiver: () => setPref.mutate({ key: ONBOARDING_DISABLED_PREF, value: true }),
  }
}
