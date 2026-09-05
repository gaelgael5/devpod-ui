/**
 * La séquence du parcours guidé (fiche 849978e7).
 *
 * L'architecte a listé 15 étapes. Certaines désignent des **pages du portail**
 * (profil, abonnement, secrets…) : ce sont les seules qu'un parcours ancré sur
 * l'UI peut piloter. D'autres désignent des gestes hors portail (Login sur une
 * machine, /remote, Termix, Claude.md, backlog DocFlow) : le portail ne les
 * héberge pas, il ne peut donc pas y ancrer une bulle. Les inventer serait
 * mentir sur ce que le parcours sait faire — elles restent hors de cette
 * séquence, et la fiche note elle-même « ordre à revérifier / contenu à cadrer ».
 *
 * Le contenu exact des messages est à cadrer : les clés i18n portent une
 * première rédaction, relisable sans toucher au code.
 */

export interface OnboardingStep {
  /** Clé i18n du titre et du corps (`onboarding.steps.<key>.title` / `.body`). */
  key: string
  /** Route du portail où l'étape a un sens. La bulle ne s'affiche que là. */
  path: string
}

/** Séquence plate, dans l'ordre de la fiche, bornée aux pages du portail. */
export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  { key: 'profil', path: '/profile' },
  { key: 'abonnement', path: '/abonnement' },
  { key: 'secrets', path: '/vault/keys' },
  { key: 'git', path: '/git-credentials' },
  { key: 'recette', path: '/recipes' },
  { key: 'profils', path: '/profiles' },
  { key: 'workspace', path: '/workspaces/new' },
  { key: 'sessions', path: '/sessions' },
] as const

export const ONBOARDING_STEP_PREF = 'onboarding_step'
export const ONBOARDING_DISABLED_PREF = 'onboarding_disabled'
