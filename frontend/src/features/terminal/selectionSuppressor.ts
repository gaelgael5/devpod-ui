/**
 * Etouffe la selection native qu'iOS pose sur une double tape.
 *
 * Effacer la selection apres coup ne suffit pas : iOS la pose de son propre
 * chef, et pas forcement dans la meme frame que la fin du contact — le nettoyage
 * passe alors AVANT, et la bande surlignee reste a l'ecran.
 *
 * On bascule donc `user-select: none` sur la surface pendant une courte fenetre.
 * Sur WebKit cette propriete fait deux choses a la fois : elle efface la
 * selection en cours dans l'element, et elle empeche d'en poser une nouvelle —
 * ce qui couvre le cas ou iOS arrive en retard.
 *
 * La fenetre reste bien plus courte que le seuil d'appui long (~500 ms) : la
 * selection volontaire, elle, n'est jamais genee.
 */

/** Duree d'etouffement. Assez pour couvrir le retard d'iOS, trop court pour l'appui long. */
export const SUPPRESSION_MS = 400

/** Les deux graphies : Safari ancien ne connait que la prefixee. */
const PROPRIETES = ['user-select', '-webkit-user-select'] as const

export interface SelectionSuppressor {
  /** Efface la selection et en interdit une nouvelle, le temps de la fenetre. */
  suppress(): void
  /** Restaure la surface — a appeler au demontage. */
  dispose(): void
}

interface Options {
  /** Efface la selection propre a xterm, distincte de celle du document. */
  clearTerminalSelection: () => void
  /** Minuterie, injectable pour les tests. */
  setTimer?: (cb: () => void, ms: number) => number
  clearTimer?: (id: number) => void
}

export function createSelectionSuppressor(
  /** `null` quand le terminal n'est pas monte : le suppresseur devient inerte. */
  element: HTMLElement | null,
  { clearTerminalSelection, setTimer = window.setTimeout, clearTimer = window.clearTimeout }: Options,
): SelectionSuppressor {
  /** Valeurs d'origine, relevees au premier etouffement seulement. */
  let origine: string[] | null = null
  let timer: number | null = null

  const effacer = () => {
    clearTerminalSelection()
    window.getSelection()?.removeAllRanges()
  }

  const restaurer = () => {
    timer = null
    if (!element || !origine) return
    // Effacer AVANT de rendre la selection possible : une selection residuelle
    // reapparaitrait sinon au moment ou la propriete est levee.
    effacer()
    PROPRIETES.forEach((p, i) => element.style.setProperty(p, origine![i]))
    origine = null
  }

  return {
    suppress() {
      if (!element) return
      if (!origine) origine = PROPRIETES.map((p) => element.style.getPropertyValue(p))
      PROPRIETES.forEach((p) => element.style.setProperty(p, 'none'))
      effacer()
      if (timer !== null) clearTimer(timer)
      timer = setTimer(restaurer, SUPPRESSION_MS)
    },

    dispose() {
      if (timer !== null) clearTimer(timer)
      restaurer()
    },
  }
}
