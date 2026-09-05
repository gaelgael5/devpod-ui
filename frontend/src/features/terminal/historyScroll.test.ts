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
  pixelsDeMolette,
  EXIT_COPY,
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

describe('createHistoryScroller — sortie du copy-mode', () => {
  /**
   * tmux RESTE en copy-mode apres le geste : il y absorbe la saisie au lieu de
   * la transmettre a l'application. L'utilisateur qui remonte dans l'historique
   * puis se remet a taper ne voit plus rien s'inscrire — la frappe part bien
   * cote navigateur, elle meurt cote tmux.
   */
  it('quitte le copy-mode ou un geste a fait entrer', () => {
    const { s, send, tick } = scroller()
    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 2)
    tick(10)
    s.touchEnd()
    send.mockClear()

    expect(s.exitCopyMode()).toBe(true)
    expect(send).toHaveBeenCalledWith(EXIT_COPY)
  })

  it('ne fait rien si aucun geste n’y a fait entrer', () => {
    // Envoyer `q` a une application qui n'est pas en copy-mode y ecrirait un
    // caractere bien reel.
    const { s, send } = scroller()

    expect(s.exitCopyMode()).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('ne sort qu’une fois', () => {
    const { s, send, tick } = scroller()
    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 2)
    tick(10)
    s.exitCopyMode()
    send.mockClear()

    expect(s.exitCopyMode()).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('abandonne le defilement restant en sortant', () => {
    // Ces lignes n'ont plus de sens hors du mode, et elles y rentreraient.
    const { s, send, tick } = scroller()
    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 20)
    // Une frame suffit a emettre l'entree en copy-mode ; les 20 lignes, elles,
    // restent en attente — c'est justement ce qu'on veut voir abandonne.
    tick(1)
    s.exitCopyMode()
    send.mockClear()

    tick(30)

    expect(send).not.toHaveBeenCalled()
  })

  it('peut y rentrer de nouveau apres etre sorti', () => {
    const { s, send, tick } = scroller()
    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 2)
    tick(10)
    s.exitCopyMode()
    s.touchEnd()
    send.mockClear()

    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX)
    s.touchMove(100 + DRAG_SLOP_PX + LINE_PX * 2)
    tick(10)

    expect(send.mock.calls.map((c) => c[0])).toContain(ENTER_COPY)
  })
})

describe('pixelsDeMolette', () => {
  const LIGNES_PAR_PAGE = 24

  it('laisse un delta deja en pixels tel quel', () => {
    expect(pixelsDeMolette({ deltaY: -100, deltaMode: 0 }, LIGNES_PAR_PAGE)).toBe(-100)
  })

  it('convertit un delta en lignes, sans quoi la molette semble morte', () => {
    // Firefox rend `3` pour un cran. Lu comme des pixels, il faudrait sept
    // crans pour franchir les vingt pixels d'une ligne.
    expect(pixelsDeMolette({ deltaY: -3, deltaMode: 1 }, LIGNES_PAR_PAGE)).toBe(-3 * LINE_PX)
  })

  it('convertit un delta en pages', () => {
    expect(pixelsDeMolette({ deltaY: 1, deltaMode: 2 }, LIGNES_PAR_PAGE)).toBe(
      LINE_PX * LIGNES_PAR_PAGE,
    )
  })

  it('franchit une ligne des le premier cran en mode lignes', () => {
    const { s, send, tick } = scroller()

    s.wheel(pixelsDeMolette({ deltaY: -3, deltaMode: 1 }, LIGNES_PAR_PAGE))
    tick(10)

    expect(send.mock.calls.map((c) => c[0])).toContain(ENTER_COPY)
  })
})

describe('application qui capte la souris (TUI plein ecran, ex. Claude Code)', () => {
  /**
   * Dans une session Claude, l'historique tmux est VIDE ([0/0]) : la TUI
   * occupe l'ecran alterne du pane et redessine sur place, rien n'entre
   * jamais dans le scrollback. Le copy-mode n'a donc rien a defiler — le
   * geste doit parler A L'APPLICATION, en evenements molette, comme le fait
   * une molette de bureau quand la TUI suit la souris.
   */
  function scrollerSouris() {
    const send = vi.fn()
    const frames: (() => void)[] = []
    const s = createHistoryScroller({
      isAlternate: () => true,
      send,
      schedule: (cb) => frames.push(cb),
      capteSouris: () => true,
      sequenceMolette: (up) => (up ? 'MOLETTE_HAUT' : 'MOLETTE_BAS'),
    })
    const tick = (n = 1) => {
      for (let i = 0; i < n; i++) {
        const f = frames.shift()
        if (!f) break
        f()
      }
    }
    return { s, send, tick }
  }

  it('emet des evenements molette, jamais le copy-mode', () => {
    const { s, send, tick } = scrollerSouris()
    s.wheel(-LINE_PX * 2)
    tick(10)

    expect(send).toHaveBeenCalledWith('MOLETTE_HAUT')
    expect(send).not.toHaveBeenCalledWith(ENTER_COPY)
  })

  it('descend aussi en molette', () => {
    const { s, send, tick } = scrollerSouris()
    s.wheel(LINE_PX)
    tick(5)

    expect(send).toHaveBeenCalledExactlyOnceWith('MOLETTE_BAS')
  })

  it('une emission par frame, comme les touches', () => {
    const { s, send, tick } = scrollerSouris()
    s.wheel(-LINE_PX * 3)
    tick(1)

    expect(send).toHaveBeenCalledTimes(1)
  })

  it('exitCopyMode reste muet : rien a quitter, et `q` taperait dans la TUI', () => {
    const { s, send, tick } = scrollerSouris()
    s.wheel(-LINE_PX * 2)
    tick(10)
    send.mockClear()

    expect(s.exitCopyMode()).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('sans capture souris, le copy-mode reste le chemin', () => {
    // Le cas VM/logs : le pane a un vrai historique tmux, le copy-mode marche.
    const { s, send, tick } = scroller()
    s.wheel(-LINE_PX)
    tick()

    expect(send).toHaveBeenCalledExactlyOnceWith(ENTER_COPY)
  })
})

describe('elan au lacher du doigt', () => {
  /**
   * Un grand geste rapide doit continuer sur sa lancee (deceleration
   * progressive) ; un glissement lent reste ligne a ligne, sans inertie.
   */
  function scrollerElan() {
    const send = vi.fn()
    const frames: (() => void)[] = []
    let t = 0
    const s = createHistoryScroller({
      isAlternate: () => true,
      send,
      schedule: (cb) => frames.push(cb),
      now: () => t,
      capteSouris: () => true,
      sequenceMolette: (up) => (up ? 'HAUT' : 'BAS'),
    })
    const avance = (ms: number) => { t += ms }
    const tick = (n = 1) => {
      for (let i = 0; i < n; i++) {
        const f = frames.shift()
        if (!f) break
        f()
      }
    }
    return { s, send, tick, avance, frames }
  }

  function grandGeste(s: ReturnType<typeof scrollerElan>['s'], avance: (ms: number) => void) {
    // Doigt qui descend VITE : ~3 px/ms, bien au-dela du seuil d'elan.
    s.touchStart(100)
    avance(16)
    s.touchMove(150)  // franchit le seuil de glissement
    avance(16)
    s.touchMove(200)
    s.touchEnd()
  }

  it('continue de defiler apres le lacher', () => {
    const { s, send, tick, avance } = scrollerElan()
    grandGeste(s, avance)
    send.mockClear()

    tick(30)

    expect(send.mock.calls.length).toBeGreaterThan(0)
  })

  it('decelere jusqu’a l’arret : la file de frames se vide', () => {
    const { s, tick, avance, frames } = scrollerElan()
    grandGeste(s, avance)

    tick(500)

    expect(frames).toHaveLength(0)
  })

  it('pas d’elan sur un glissement lent', () => {
    const { s, send, tick, avance } = scrollerElan()
    s.touchStart(100)
    avance(100)
    s.touchMove(115)  // franchit le seuil, ~0.15 px/ms
    avance(100)
    s.touchMove(130)
    s.touchEnd()
    send.mockClear()

    tick(50)

    expect(send).not.toHaveBeenCalled()
  })

  it('poser le doigt arrete l’elan', () => {
    const { s, send, tick, avance } = scrollerElan()
    grandGeste(s, avance)
    tick(2)
    s.touchStart(100)  // le doigt rattrape l'ecran
    send.mockClear()

    tick(50)

    expect(send).not.toHaveBeenCalled()
  })
})

describe('actif() — le re-rendu force doit se taire pendant le geste', () => {
  /**
   * Pendant un defilement pilote par l'utilisateur, chaque image change
   * beaucoup de lignes : la detection de defilement declencherait des
   * refresh-client plein ecran en rafale — ecran blanc, clignotement (mesure
   * sur iPhone le 05/09). L'appelant interroge `actif()` pour suspendre le
   * nettoyage tant que le geste ou l'elan court.
   */
  it('vrai pendant un glissement, faux au repos', () => {
    const { s } = scroller()
    expect(s.actif()).toBe(false)

    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX + 1)

    expect(s.actif()).toBe(true)
  })

  it('faux apres la fin du geste une fois tout ecoule', () => {
    const { s, tick } = scroller()
    s.touchStart(100)
    s.touchMove(100 + DRAG_SLOP_PX + 1)
    s.touchEnd()
    tick(100)

    expect(s.actif()).toBe(false)
  })
})
