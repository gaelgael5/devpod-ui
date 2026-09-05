/**
 * Glissé de sélection stérile -> indice « maintenir Maj ».
 *
 * Quand l'application distante active le suivi souris (tmux, TUI type `claude`),
 * xterm lui transmet les clics au lieu d'en faire une sélection locale : le
 * glissé ne surligne rien, ne copie rien, et RIEN ne le dit. Mesure côté Loki :
 * `selection_change` répétait `chars: 0` pendant que `mouseTrackingMode` valait
 * « any », alors que le même geste donnait `chars: 107` puis un copier réussi
 * une fois le TUI sorti. `Maj`+glisser force la sélection locale — encore
 * faut-il le deviner. On reconnaît le geste manqué pour l'annoncer.
 */

/** En deçà, le mouvement est un clic destiné au TUI, pas une sélection. */
export const GLISSE_MIN_PX = 8
/** Silence entre deux indices : celui qui insiste n'a pas besoin d'un toast par glissé. */
export const SILENCE_MS = 30_000

export interface SelectionHintDetector {
  /** Début d'un glissé. `shift`/`suiviSouris` décident si le geste est à surveiller. */
  start(x: number, y: number, opts: { shift: boolean; suiviSouris: boolean }): void
  /** Fin du glissé. Retourne `true` quand l'indice doit être affiché. */
  end(x: number, y: number, opts: { selectionActive: boolean }): boolean
}

interface Options {
  /** Horloge, injectable pour les tests. */
  now?: () => number
}

export function createSelectionHintDetector({
  now = () => Date.now(),
}: Options = {}): SelectionHintDetector {
  let debut: { x: number; y: number } | null = null
  let dernierIndice = Number.NEGATIVE_INFINITY

  return {
    start(x, y, { shift, suiviSouris }) {
      // Maj : la sélection locale est déjà forcée, l'utilisateur sait. Pas de
      // suivi souris : la sélection fonctionne, il n'y a rien à expliquer.
      debut = shift || !suiviSouris ? null : { x, y }
    },
    end(x, y, { selectionActive }) {
      const d = debut
      debut = null
      if (!d || selectionActive) return false
      if (Math.hypot(x - d.x, y - d.y) < GLISSE_MIN_PX) return false
      const maintenant = now()
      if (maintenant - dernierIndice < SILENCE_MS) return false
      dernierIndice = maintenant
      return true
    },
  }
}
