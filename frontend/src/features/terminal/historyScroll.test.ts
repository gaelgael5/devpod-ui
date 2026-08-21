/**
 * Defilement de l'historique tmux au geste.
 *
 * Le point a verrouiller : ne rien faire hors tampon alterne. Sans tmux, xterm a
 * un vrai scrollback et prendre la main casserait le defilement natif.
 */
import { describe, expect, it, vi } from 'vitest'
import { PAGE_DOWN, PAGE_PX, PAGE_UP, createHistoryScroller } from './historyScroll'

function scroller(alternate = true) {
  const send = vi.fn()
  return { send, s: createHistoryScroller({ isAlternate: () => alternate, send }) }
}

describe('createHistoryScroller', () => {
  it('remonte d’une page a la molette vers le haut', () => {
    const { s, send } = scroller()
    expect(s.wheel(-PAGE_PX)).toBe(true)
    expect(send).toHaveBeenCalledExactlyOnceWith(PAGE_UP)
  })

  it('redescend d’une page a la molette vers le bas', () => {
    const { s, send } = scroller()
    s.wheel(PAGE_PX)
    expect(send).toHaveBeenCalledExactlyOnceWith(PAGE_DOWN)
  })

  it('accumule les petits mouvements jusqu’a une page', () => {
    const { s, send } = scroller()
    for (let i = 0; i < 3; i++) s.wheel(-PAGE_PX / 4)
    expect(send).not.toHaveBeenCalled()

    s.wheel(-PAGE_PX / 4)
    expect(send).toHaveBeenCalledExactlyOnceWith(PAGE_UP)
  })

  it('envoie plusieurs pages sur un geste ample', () => {
    const { s, send } = scroller()
    s.wheel(-PAGE_PX * 3)
    expect(send.mock.calls.map((c) => c[0])).toEqual([PAGE_UP, PAGE_UP, PAGE_UP])
  })

  it('ne touche a rien hors tampon alterne', () => {
    // Sans tmux, xterm a son propre scrollback : le defilement natif doit vivre.
    const { s, send } = scroller(false)
    expect(s.wheel(-PAGE_PX * 2)).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('consomme le geste meme sans page atteinte', () => {
    // Sinon le reliquat declencherait le defilement natif du navigateur.
    const { s } = scroller()
    expect(s.wheel(-1)).toBe(true)
  })

  it('remonte quand le doigt descend', () => {
    const { s, send } = scroller()
    s.touchStart(100)
    s.touchMove(100 + PAGE_PX)

    expect(send).toHaveBeenCalledExactlyOnceWith(PAGE_UP)
  })

  it('redescend quand le doigt remonte', () => {
    const { s, send } = scroller()
    s.touchStart(500)
    s.touchMove(500 - PAGE_PX)

    expect(send).toHaveBeenCalledExactlyOnceWith(PAGE_DOWN)
  })

  it('ignore un glissement sans depart', () => {
    const { s, send } = scroller()
    expect(s.touchMove(300)).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('repart de zero au geste suivant', () => {
    const { s, send } = scroller()
    s.touchStart(100)
    s.touchMove(100 + PAGE_PX / 2) // moitie de page, rien d'envoye
    s.touchEnd()

    s.touchStart(100)
    s.touchMove(100 + PAGE_PX / 2) // le reliquat precedent ne doit pas s'ajouter
    expect(send).not.toHaveBeenCalled()
  })

  it('un appui long immobile n’envoie rien', () => {
    // La selection par appui long doit rester intacte sur mobile.
    const { s, send } = scroller()
    s.touchStart(200)
    s.touchMove(200)

    expect(send).not.toHaveBeenCalled()
  })
})
