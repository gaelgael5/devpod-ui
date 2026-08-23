/**
 * Double tape tactile -> touche Tab.
 *
 * Uniquement le tactile : au bureau le double-clic appartient a xterm, qui
 * s'en sert pour selectionner un mot — donc pour copier. On ne s'y substitue pas.
 *
 * Ce qui NE doit pas etre pris pour une tape :
 * - un appui long, qui ouvre la selection native sur mobile (d'ou `TAP_MAX_MS`) ;
 * - un glissement, qui fait defiler l'historique (d'ou `TAP_SLOP_PX`) ;
 * - un geste a plusieurs doigts.
 */

/** Deplacement tolere pendant une tape. Au-dela, c'est un glissement. */
export const TAP_SLOP_PX = 24
/** Duree maximale d'une tape. Au-dela, c'est un appui long : selection. */
export const TAP_MAX_MS = 250
/** Ecart maximal entre les deux tapes. */
export const DOUBLE_TAP_MS = 300
/** Distance maximale entre les deux tapes. */
export const DOUBLE_TAP_SLOP_PX = 40

export interface DoubleTapDetector {
  /** Debut d'un contact. `touches` sert a ignorer les gestes multi-doigts. */
  start(x: number, y: number, touches: number): void
  /** Contact en mouvement. */
  move(x: number, y: number): void
  /** Fin du contact. Retourne `true` si une double tape vient d'etre reconnue. */
  end(): boolean
}

interface Options {
  /** Horloge, injectable pour les tests. */
  now?: () => number
}

interface Tape {
  x: number
  y: number
  t: number
}

function distance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function createDoubleTapDetector({ now = () => performance.now() }: Options = {}): DoubleTapDetector {
  /** Contact en cours ; `null` des qu'il est disqualifie. */
  let contact: Tape | null = null
  /** Derniere tape validee, candidate a former une double tape. */
  let precedente: Tape | null = null

  return {
    start(x, y, touches) {
      // Plusieurs doigts : pincement ou geste complexe, jamais une tape.
      contact = touches === 1 ? { x, y, t: now() } : null
    },

    move(x, y) {
      if (contact && distance(contact, { x, y }) > TAP_SLOP_PX) contact = null
    },

    end() {
      const fin = contact
      contact = null
      if (!fin) return false
      // Appui long : on laisse la selection native s'installer.
      if (now() - fin.t > TAP_MAX_MS) {
        precedente = null
        return false
      }

      const double =
        precedente !== null &&
        now() - precedente.t <= DOUBLE_TAP_MS &&
        distance(precedente, fin) <= DOUBLE_TAP_SLOP_PX

      // Reconnue : on repart de zero, sinon une troisieme tape en declencherait
      // une seconde par ricochet.
      precedente = double ? null : fin
      return double
    },
  }
}
