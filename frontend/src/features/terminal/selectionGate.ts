/**
 * Autorise ou interdit la selection native selon l'endroit touche.
 *
 * Sur du texte, la selection appartient au systeme : double tape pour le mot,
 * appui long pour la poignee — c'est le seul moyen de copier au doigt.
 * Dans le vide, il n'y a rien a selectionner ; la double tape y prend la ligne
 * entiere et laisse une bande surlignee en travers de l'ecran, sans rien a la
 * clef.
 *
 * La decision se prend au POSE DU DOIGT, pas a la fin du contact. C'est le point
 * important : iOS pose sa selection tot, et couper `user-select` au `touchend`
 * arrivait apres — la bande apparaissait, puis disparaissait. Fermee des le
 * `touchstart`, elle ne nait jamais.
 *
 * Pas de minuterie : l'etat suit la position et rien d'autre. Un doigt pose sur
 * du texte rouvre la porte immediatement, bien avant le seuil d'appui long.
 */

/** Les deux graphies : Safari ancien ne connait que la prefixee. */
const PROPRIETES = ['user-select', '-webkit-user-select'] as const

export interface SelectionGate {
  /** `true` = selection permise (doigt sur du texte), `false` = interdite. */
  set(autorisee: boolean): void
  /** Rend la surface a son etat d'origine — a appeler au demontage. */
  dispose(): void
}

interface Options {
  /** Efface la selection propre a xterm, distincte de celle du document. */
  clearTerminalSelection: () => void
}

export function createSelectionGate(
  /** `null` quand le terminal n'est pas monte : la porte devient inerte. */
  element: HTMLElement | null,
  { clearTerminalSelection }: Options,
): SelectionGate {
  /** Valeurs d'origine, relevees a la premiere fermeture seulement. */
  let origine: string[] | null = null

  return {
    set(autorisee) {
      if (!element) return

      if (autorisee) {
        if (!origine) return
        PROPRIETES.forEach((p, i) => element.style.setProperty(p, origine![i]))
        origine = null
        return
      }

      if (!origine) origine = PROPRIETES.map((p) => element.style.getPropertyValue(p))
      PROPRIETES.forEach((p) => element.style.setProperty(p, 'none'))
      // Une selection posee avant la fermeture survivrait a la propriete : sur
      // WebKit elle disparait, ailleurs non. On l'efface donc explicitement.
      clearTerminalSelection()
      window.getSelection()?.removeAllRanges()
    },

    dispose() {
      this.set(true)
    },
  }
}
