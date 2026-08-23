/**
 * Appareil sans clavier physique (pointeur grossier, pas de survol).
 *
 * Sert a decider si le terminal prend le focus a l'ouverture. Au clavier
 * physique c'est un confort — sans autofocus il faudrait cliquer avant de
 * taper. Au tactile c'est une nuisance : le focus deroule le clavier virtuel,
 * qui occupe la moitie de l'ecran d'une session deja etroite.
 *
 * `matchMedia` absent (jsdom, environnements anciens) : on repond `false`,
 * c'est-a-dire l'ancien comportement.
 */
export function isTouchOnly(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(hover: none) and (pointer: coarse)').matches
}
