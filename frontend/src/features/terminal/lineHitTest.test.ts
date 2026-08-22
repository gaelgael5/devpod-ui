/**
 * Ce test protege surtout les cas de refus : un `true` de trop enverrait Tab
 * la ou l'utilisateur voulait selectionner un mot.
 */
import { describe, expect, it } from 'vitest'
import { isPastLineEnd, type HitTestTerminal } from './lineHitTest'

const COLS = 80
const ROWS = 24
const LARGEUR = 800
const HAUTEUR = 480
/** 10 px par colonne, 20 px par ligne : la grille tombe juste. */
const COL_PX = LARGEUR / COLS
const ROW_PX = HAUTEUR / ROWS

interface Options {
  lignes?: Record<number, string>
  viewportY?: number
  rect?: { width: number; height: number }
  monte?: boolean
}

function terminal({
  lignes = { 0: 'ls -la' },
  viewportY = 0,
  rect = { width: LARGEUR, height: HAUTEUR },
  monte = true,
}: Options = {}): HitTestTerminal {
  const zone = document.createElement('div')
  zone.className = 'xterm-screen'
  zone.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: rect.width, height: rect.height }) as DOMRect
  const element = document.createElement('div')
  if (monte) element.appendChild(zone)

  return {
    cols: COLS,
    rows: ROWS,
    element,
    buffer: {
      active: {
        viewportY,
        getLine: (y: number) => {
          const texte = lignes[y]
          return texte === undefined ? undefined : { translateToString: () => texte }
        },
      },
    },
  }
}

/** Centre de la cellule (colonne, ligne). */
function point(colonne: number, ligne: number) {
  return [(colonne + 0.5) * COL_PX, (ligne + 0.5) * ROW_PX] as const
}

describe('isPastLineEnd', () => {
  it('refuse un point pose sur le texte', () => {
    // « ls -la » occupe les colonnes 0 a 5 : xterm doit garder le geste.
    const t = terminal()
    for (const colonne of [0, 3, 5]) {
      expect(isPastLineEnd(t, ...point(colonne, 0))).toBe(false)
    }
  })

  it('accepte le premier vide juste apres la fin de ligne', () => {
    expect(isPastLineEnd(terminal(), ...point(6, 0))).toBe(true)
  })

  it('accepte loin apres la fin de ligne', () => {
    expect(isPastLineEnd(terminal(), ...point(70, 0))).toBe(true)
  })

  it('accepte une ligne entierement vide', () => {
    // Un prompt vide : Tab y liste les completions, c'est utile.
    expect(isPastLineEnd(terminal({ lignes: { 0: '' } }), ...point(0, 0))).toBe(true)
  })

  it('accepte une ligne absente du tampon', () => {
    expect(isPastLineEnd(terminal({ lignes: {} }), ...point(0, 3))).toBe(true)
  })

  it('lit la ligne visee, pas la premiere', () => {
    const t = terminal({ lignes: { 0: '', 5: 'cat fichier.txt' } })
    expect(isPastLineEnd(t, ...point(3, 5))).toBe(false)
    expect(isPastLineEnd(t, ...point(20, 5))).toBe(true)
  })

  it('tient compte du defilement du tampon', () => {
    // La ligne 0 a l'ecran est la ligne `viewportY` du tampon.
    const t = terminal({ lignes: { 12: 'commande' }, viewportY: 12 })
    expect(isPastLineEnd(t, ...point(4, 0))).toBe(false)
    expect(isPastLineEnd(t, ...point(30, 0))).toBe(true)
  })

  it('refuse un point hors de la zone de rendu', () => {
    const t = terminal()
    expect(isPastLineEnd(t, -5, 10)).toBe(false)
    expect(isPastLineEnd(t, LARGEUR + 5, 10)).toBe(false)
    expect(isPastLineEnd(t, 10, HAUTEUR + 5)).toBe(false)
  })

  it('refuse quand la zone n’est pas mesurable', () => {
    // Onglet cache ou mise en page pas encore faite : mesurer donnerait n'importe quoi.
    expect(isPastLineEnd(terminal({ rect: { width: 0, height: 0 } }), 10, 10)).toBe(false)
  })

  it('refuse quand le terminal n’est pas monte', () => {
    expect(isPastLineEnd(terminal({ monte: false }), 10, 10)).toBe(false)
  })
})
