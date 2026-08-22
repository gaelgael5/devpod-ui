/**
 * Ou est tombe le doigt : sur du texte, ou dans le vide apres la fin de ligne ?
 *
 * Sert a departager les deux sens d'une double tape sur mobile :
 * - sur un mot, elle appartient a xterm, qui selectionne ce mot — donc qui
 *   permet de le copier ;
 * - au-dela du dernier caractere de la ligne, il n'y a rien a selectionner :
 *   c'est le geste naturel de « completer ce que je viens de taper », donc Tab.
 *
 * xterm n'expose aucun test de collision coordonnees -> cellule. On le calcule
 * a partir de la zone de rendu : sa taille divisee par `cols`/`rows` donne la
 * cellule, dont la grille est reguliere par construction.
 */

/** Sous-ensemble de `Terminal` reellement utilise — un mock de test s'y conforme. */
export interface HitTestTerminal {
  readonly cols: number
  readonly rows: number
  readonly element: HTMLElement | undefined
  readonly buffer: {
    readonly active: {
      readonly viewportY: number
      getLine(y: number): { translateToString(trimRight?: boolean): string } | undefined
    }
  }
}

/** Zone de rendu de xterm, ou `null` si le terminal n'est pas encore monte. */
function ecran(terminal: HitTestTerminal): HTMLElement | null {
  return terminal.element?.querySelector<HTMLElement>('.xterm-screen') ?? null
}

/**
 * Le point est-il au-dela du dernier caractere de sa ligne ?
 *
 * `false` des que la mesure est douteuse (terminal non monte, zone de taille
 * nulle, point hors de l'ecran) : dans le doute on ne prend pas la main sur le
 * geste, la selection de xterm reste prioritaire.
 */
export function isPastLineEnd(
  terminal: HitTestTerminal,
  clientX: number,
  clientY: number,
): boolean {
  const zone = ecran(terminal)
  if (!zone) return false

  const rect = zone.getBoundingClientRect()
  // Zone non mesurable : onglet cache, ou terminal pas encore mis en page.
  if (rect.width < 1 || rect.height < 1) return false
  if (terminal.cols < 1 || terminal.rows < 1) return false

  const x = clientX - rect.left
  const y = clientY - rect.top
  if (x < 0 || y < 0 || x >= rect.width || y >= rect.height) return false

  const colonne = Math.floor(x / (rect.width / terminal.cols))
  const ligne = Math.floor(y / (rect.height / terminal.rows))

  const { active } = terminal.buffer
  const contenu = active.getLine(active.viewportY + ligne)?.translateToString(true) ?? ''
  return colonne >= contenu.length
}
