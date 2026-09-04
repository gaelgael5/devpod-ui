/**
 * Ce qu'xterm n'a pas encore analyse.
 *
 * `terminal.write()` est ASYNCHRONE : xterm met en file et analyse plus tard,
 * en rappelant quand c'est fait. Redimensionner pendant que la file n'est pas
 * vide fait interpreter contre la NOUVELLE geometrie des octets que tmux a
 * emis pour l'ANCIENNE — texte entrelace, lignes qui se marchent dessus.
 * Mesure en production le 03/09/2026 : 4580 octets en attente au moment d'un
 * nudge, sur une session ou personne n'attendait quoi que ce soit.
 *
 * D'ou ce module : le recalage passe par `quandVide`, et ne part qu'une fois
 * le flux digere.
 */

/**
 * Plafond d'attente.
 *
 * Une session qui ecrit en continu — `top`, un build, un agent bavard — ne
 * videra jamais sa file. Attendre indefiniment, ce serait ne plus jamais se
 * recaler. Passe ce delai on recale donc quand meme, avec des octets en vol :
 * c'est exactement le comportement d'avant ce module, jamais pire.
 */
export const ATTENTE_MAX_MS = 250

export interface ParseQueue {
  /** Octets recus de la WebSocket et remis a xterm. */
  arrive(n: number): void
  /** Octets analyses par xterm (son rappel de `write`). */
  analyse(n: number): void
  /** Ce qui reste a analyser — c'est la sonde `octets` du journal. */
  enAttente(): number
  /**
   * Execute `action` des que la file est vide, immediatement si elle l'est
   * deja, et au plus tard au bout du plafond.
   *
   * Une action en attente est REMPLACEE par la suivante : c'est un recalage,
   * pas une file de travaux, et deux recalages coup sur coup, c'est la rafale
   * de SIGWINCH qu'on cherche a eviter.
   */
  quandVide(action: () => void): void
  /** Demontage : oublie l'action en attente et son minuteur. */
  dispose(): void
}

export function createParseQueue(attenteMaxMs: number = ATTENTE_MAX_MS): ParseQueue {
  let octets = 0
  let enSuspens: (() => void) | null = null
  let plafond: ReturnType<typeof setTimeout> | undefined

  const executer = () => {
    const action = enSuspens
    enSuspens = null
    clearTimeout(plafond)
    plafond = undefined
    action?.()
  }

  return {
    arrive(n) {
      octets += n
    },

    analyse(n) {
      // Jamais sous zero : xterm peut rappeler pour un `write` anterieur, et un
      // compteur negatif rendrait la file « jamais vide » pour toujours.
      octets = Math.max(0, octets - n)
      if (octets === 0 && enSuspens) executer()
    },

    enAttente: () => octets,

    quandVide(action) {
      // Synchrone quand il n'y a rien a attendre : le premier ajustement se
      // fait avant l'ouverture de la WebSocket, et `ssh` fixe la taille du PTY
      // distant au demarrage sans jamais la relire.
      if (octets === 0) {
        action()
        return
      }
      enSuspens = action
      // Le plafond court depuis la PREMIERE demande, et n'est pas rearme par
      // les suivantes : sinon un flux continu le repousserait sans fin, ce
      // qu'il existe precisement pour empecher.
      plafond ??= setTimeout(executer, attenteMaxMs)
    },

    dispose() {
      enSuspens = null
      clearTimeout(plafond)
      plafond = undefined
    },
  }
}
