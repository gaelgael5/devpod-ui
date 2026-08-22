/**
 * Defilement de l'historique tmux au geste.
 *
 * Le point critique, mesure contre un vrai tmux : le PTY regroupe les ecritures
 * rapprochees en une seule lecture et tmux perd alors les touches repetees — 10
 * `C-Up` d'affilee ne defilent que de 2 lignes. D'ou un jeton par frame, et
 * l'entree en copy-mode isolee dans sa propre emission.
 */
import { describe, expect, it, vi } from 'vitest'
import {
  DRAG_SLOP_PX,
  ENTER_COPY,
  LINE_DOWN,
  LINE_PX,
  LINE_UP,
  MAX_LIGNES_EN_ATTENTE,
  createHistoryScroller,
} from './historyScroll'

function scroller(alternate = true) {
  const send = vi.fn()
  const frames: (() => void)[] = []
  const s = createHistoryScroller({
    isAlternate: () => alternate,
    send,
    schedule: (cb) => frames.push(cb),
  })
  /** Deroule les frames en attente (bornees, pour ne pas boucler sans fin). */
  const tick = (n = 1) => {
    for (let i = 0; i < n; i++) {
      const f = frames.shift()
      if (!f) break
      f()
    }
  }
  return { s, send, tick, frames }
}

describe('createHistoryScroller', () => {
  it('n’emet rien de synchrone : tout passe par une frame', () => {
    const { s, send } = scroller()
    s.wheel(-LINE_PX * 3)
    expect(send).not.toHaveBeenCalled()
  })

  it('entre en copy-mode dans une emission isolee', () => {
    const { s, send, tick } = scroller()
    s.wheel(-LINE_PX)
    tick()

    // Concatenee a une touche de defilement, l'entree la ferait perdre.
    expect(send).toHaveBeenCalledExactlyOnceWith(ENTER_COPY)
  })

  it('remonte ensuite d’une ligne par frame', () => {
    const { s, send, tick } = scroller()
    s.wheel(-LINE_PX * 3)
    tick(10)

    expect(send.mock.calls.map((c) => c[0])).toEqual([
      ENTER_COPY,
      LINE_UP,
      LINE_UP,
      LINE_UP,
    ])
  })

  it('n’emet jamais deux jetons dans la meme frame', () => {
    const { s, send, tick } = scroller()
    s.wheel(-LINE_PX * 5)

    tick()
    expect(send).toHaveBeenCalledTimes(1)
    tick()
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('redescend sans entrer en copy-mode', () => {
    const { s, send, tick } = scroller()
    s.wheel(LINE_PX * 2)
    tick(10)

    // Entrer en copy-mode vers le bas figerait l'affichage depuis la vue directe.
    expect(send.mock.calls.map((c) => c[0])).toEqual([LINE_DOWN, LINE_DOWN])
  })

  it('accumule les mouvements sous le seuil d’une ligne', () => {
    const { s, send, tick, frames } = scroller()
    for (let i = 0; i < 3; i++) s.wheel(-LINE_PX / 4)
    expect(frames).toHaveLength(0)

    s.wheel(-LINE_PX / 4)
    tick(4)
    expect(send.mock.calls.map((c) => c[0])).toEqual([ENTER_COPY, LINE_UP])
  })

  it('ne touche a rien hors tampon alterne', () => {
    const { s, send, tick } = scroller(false)
    expect(s.wheel(-LINE_PX * 4)).toBe(false)
    tick(5)
    expect(send).not.toHaveBeenCalled()
  })

  it('consomme le geste meme sans ligne atteinte', () => {
    // Sinon le reliquat declencherait le defilement natif du navigateur.
    const { s } = scroller()
    expect(s.wheel(-1)).toBe(true)
  })

  it('borne un geste ample', () => {
    const { s, send, tick } = scroller()
    s.wheel(-LINE_PX * 10_000)
    tick(MAX_LIGNES_EN_ATTENTE + 50)

    // Sans plafond, une impulsion ample defilerait pendant des secondes.
    const lignes = send.mock.calls.filter((c) => c[0] === LINE_UP).length
    expect(lignes).toBeLessThanOrEqual(MAX_LIGNES_EN_ATTENTE)
  })

  it('remonte quand le doigt descend', () => {
    const { s, send, tick } = scroller()
    s.touchStart(100)
    // Le premier deplacement arme le glissement ; le defilement part de la.
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 2)
    tick(5)

    expect(send.mock.calls.map((c) => c[0])).toEqual([ENTER_COPY, LINE_UP, LINE_UP])
  })

  it('redescend quand le doigt remonte', () => {
    const { s, send, tick } = scroller()
    s.touchStart(500)
    s.touchMove(500 - DRAG_SLOP_PX)
    s.touchMove(500 - DRAG_SLOP_PX - LINE_PX)
    tick(5)

    expect(send.mock.calls.map((c) => c[0])).toEqual([LINE_DOWN])
  })

  it('ne consomme pas un micro-mouvement de tape', () => {
    // Consomme, le geste perdrait le clic que le navigateur en synthetise —
    // donc le focus de xterm, donc le clavier mobile et la selection de mot.
    const { s, send } = scroller()
    s.touchStart(300)

    expect(s.touchMove(300 + DRAG_SLOP_PX - 1)).toBe(false)
    expect(s.touchMove(300 - DRAG_SLOP_PX + 1)).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('ne defile pas du saut du seuil', () => {
    // Le glissement doit partir du point de franchissement : sinon le contenu
    // sauterait de la valeur du seuil des que le doigt bouge assez.
    const { s, send, tick } = scroller()
    s.touchStart(300)
    s.touchMove(300 + DRAG_SLOP_PX)
    tick(5)

    expect(send).not.toHaveBeenCalled()
  })

  it('redemande le seuil apres un relachement', () => {
    // Sinon la tape qui suit un glissement serait prise pour sa continuation.
    const { s, send, tick } = scroller()
    s.touchStart(300)
    s.touchMove(300 + DRAG_SLOP_PX)
    s.touchMove(300 + DRAG_SLOP_PX + LINE_PX * 2)
    s.touchEnd()
    // Les lignes en attente s'ecoulent frame par frame : on vide avant de
    // mesurer, sinon c'est le geste precedent qu'on lirait.
    tick(10)
    send.mockClear()

    s.touchStart(300)
    expect(s.touchMove(300 + DRAG_SLOP_PX - 1)).toBe(false)
    tick(5)
    expect(send).not.toHaveBeenCalled()
  })

  it('ignore un glissement sans depart', () => {
    const { s, send } = scroller()
    expect(s.touchMove(300)).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('un appui long immobile n’envoie rien', () => {
    // La selection par appui long doit rester intacte sur mobile.
    const { s, send, frames } = scroller()
    s.touchStart(200)
    s.touchMove(200)

    expect(frames).toHaveLength(0)
    expect(send).not.toHaveBeenCalled()
  })
})
