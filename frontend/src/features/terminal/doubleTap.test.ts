/**
 * Double tape tactile -> Tab.
 *
 * L'essentiel des tests porte sur ce qui NE doit PAS declencher : appui long
 * (selection native), glissement (defilement de l'historique), multi-doigts.
 * Une double tape trop permissive volerait ces gestes.
 */
import { describe, expect, it } from 'vitest'
import {
  DOUBLE_TAP_MS,
  DOUBLE_TAP_SLOP_PX,
  TAP_MAX_MS,
  TAP_SLOP_PX,
  createDoubleTapDetector,
} from './doubleTap'

function detector() {
  let t = 1000
  const d = createDoubleTapDetector({ now: () => t })
  return {
    d,
    avance: (ms: number) => {
      t += ms
    },
    /** Une tape complete au point donne, de duree `duree`. */
    tape(x = 100, y = 100, duree = 40) {
      d.start(x, y, 1)
      t += duree
      return d.end()
    },
  }
}

describe('createDoubleTapDetector', () => {
  it('reconnait deux tapes rapprochees', () => {
    const { tape, avance } = detector()
    expect(tape()).toBe(false)
    avance(100)
    expect(tape()).toBe(true)
  })

  it('ignore deux tapes trop espacees dans le temps', () => {
    const { tape, avance } = detector()
    tape()
    avance(DOUBLE_TAP_MS + 50)
    expect(tape()).toBe(false)
  })

  it('ignore deux tapes trop eloignees', () => {
    const { tape } = detector()
    tape(100, 100)
    expect(tape(100 + DOUBLE_TAP_SLOP_PX + 20, 100)).toBe(false)
  })

  it('ne prend pas un appui long pour une tape', () => {
    // L'appui long ouvre la selection native : il ne doit rien declencher.
    const { d, tape, avance } = detector()
    d.start(100, 100, 1)
    avance(TAP_MAX_MS + 50)
    expect(d.end()).toBe(false)

    avance(50)
    expect(tape()).toBe(false)
  })

  it('ne prend pas un glissement pour une tape', () => {
    // Le glissement fait defiler l'historique.
    const { d, tape, avance } = detector()
    d.start(100, 100, 1)
    d.move(100, 100 + TAP_SLOP_PX + 10)
    expect(d.end()).toBe(false)

    avance(50)
    expect(tape()).toBe(false)
  })

  it('tolere un micro-mouvement pendant la tape', () => {
    // Un doigt ne se pose jamais parfaitement immobile.
    const { d, tape, avance } = detector()
    tape()
    avance(80)
    d.start(100, 100, 1)
    d.move(100, 100 + TAP_SLOP_PX - 4)
    expect(d.end()).toBe(true)
  })

  it('ignore un geste a plusieurs doigts', () => {
    const { d, tape, avance } = detector()
    tape()
    avance(80)
    d.start(100, 100, 2)
    expect(d.end()).toBe(false)
  })

  it('ne declenche pas deux fois sur une triple tape', () => {
    const { tape, avance } = detector()
    tape()
    avance(80)
    expect(tape()).toBe(true)
    avance(80)
    // Sans remise a zero, la troisieme tape formerait une paire avec la seconde.
    expect(tape()).toBe(false)
  })

  it('un appui long annule la tape precedente', () => {
    // Sinon la tape d'avant resterait candidate longtemps apres.
    const { d, tape, avance } = detector()
    tape()
    avance(50)
    d.start(100, 100, 1)
    avance(TAP_MAX_MS + 50)
    d.end()

    avance(50)
    expect(tape()).toBe(false)
  })
})
