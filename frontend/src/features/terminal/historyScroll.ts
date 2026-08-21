/**
 * Defilement de l'historique tmux au geste.
 *
 * Pourquoi ce module existe : sous tmux, xterm n'a AUCUN historique a faire
 * defiler. tmux occupe l'ecran alterne, le scrollback du terminal reste vide, et
 * xterm ne traduit pas la molette en touches sur ce tampon (aucune notion
 * d'`alternateScroll` dans sa source). Molette et glissement ne font donc rien.
 *
 * L'historique vit dans le copy-mode de tmux. On traduit le geste en touches
 * plutot que d'activer `mouse on` cote tmux : celui-ci capterait les evenements
 * souris et casserait la selection de xterm, donc la copie. Ici tmux n'est pas
 * touche du tout.
 *
 * `prefix + PageUp` est lie a `copy-mode -u` : il entre dans l'historique ET
 * remonte d'une page, et rejoue il continue de remonter — d'ou l'absence d'etat
 * de mode a suivre. Sequence verifiee contre un vrai client tmux.
 */

/** Prefixe tmux (Ctrl+B) puis PageUp. */
export const PAGE_UP = '\x02\x1b[5~'
/** PageDown seul : en copy-mode il redescend d'une page. */
export const PAGE_DOWN = '\x1b[6~'

/** Pixels de geste pour une page. Un cran de molette vaut ~100-120 px. */
export const PAGE_PX = 120

export interface HistoryScroller {
  /** Molette. Retourne `true` si le geste est consomme (defilement natif a supprimer). */
  wheel(deltaY: number): boolean
  /** Debut d'un glissement tactile. */
  touchStart(clientY: number): void
  /** Glissement en cours. Retourne `true` si le geste est consomme. */
  touchMove(clientY: number): boolean
  /** Fin du glissement : l'accumulateur repart de zero. */
  touchEnd(): void
}

interface Options {
  /** Le tampon alterne est-il actif ? (tmux, TUI plein ecran) */
  isAlternate: () => boolean
  /** Ecrit dans l'entree standard de la session. */
  send: (data: string) => void
}

export function createHistoryScroller({ isAlternate, send }: Options): HistoryScroller {
  let acc = 0
  let lastY: number | null = null

  /** `delta` positif = vers le contenu recent (page suivante). */
  function feed(delta: number): boolean {
    // Hors tampon alterne, xterm a un vrai scrollback : on le laisse faire.
    if (!isAlternate()) return false

    acc += delta
    while (acc >= PAGE_PX) {
      acc -= PAGE_PX
      send(PAGE_DOWN)
    }
    while (acc <= -PAGE_PX) {
      acc += PAGE_PX
      send(PAGE_UP)
    }
    // Consomme des que le tampon alterne est actif, meme sans page atteinte :
    // sinon le reliquat de geste declencherait le defilement natif du navigateur.
    return true
  }

  return {
    wheel(deltaY) {
      return feed(deltaY)
    },

    touchStart(clientY) {
      lastY = clientY
      acc = 0
    },

    touchMove(clientY) {
      if (lastY === null) return false
      // Le doigt descend => on remonte dans l'historique : signe inverse.
      const consomme = feed(-(clientY - lastY))
      lastY = clientY
      return consomme
    },

    touchEnd() {
      lastY = null
      acc = 0
    },
  }
}
