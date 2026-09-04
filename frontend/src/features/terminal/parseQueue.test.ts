/**
 * File de parsing d'xterm.
 *
 * Le defaut qu'elle corrige : on redimensionnait le terminal alors que des
 * octets emis par tmux pour l'ANCIENNE geometrie n'etaient pas encore analyses.
 * xterm les interprete alors contre la nouvelle — texte entrelace, lignes qui
 * se marchent dessus. Mesure en production le 03/09/2026 : 4580 octets en
 * attente au moment d'un nudge.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ATTENTE_MAX_MS, createParseQueue } from './parseQueue'

describe('parseQueue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('execute immediatement quand la file est vide', () => {
    const file = createParseQueue()
    const action = vi.fn()

    file.quandVide(action)

    // Synchrone : le premier ajustement se fait avant l'ouverture de la
    // WebSocket, et differer ne serait-ce que d'une frame ferait demarrer `ssh`
    // sur les 80x24 par defaut.
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('attend le vidage complet avant d’executer', () => {
    const file = createParseQueue()
    const action = vi.fn()

    file.arrive(100)
    file.quandVide(action)
    expect(action).not.toHaveBeenCalled()

    file.analyse(40)
    expect(action).not.toHaveBeenCalled()

    file.analyse(60)
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('ne garde que la derniere action en attente', () => {
    // C'est un recalage, pas une file de travaux : deux recalages coup sur
    // coup, c'est la rafale de SIGWINCH qu'on cherche justement a eviter.
    const file = createParseQueue()
    const ancienne = vi.fn()
    const derniere = vi.fn()

    file.arrive(10)
    file.quandVide(ancienne)
    file.quandVide(derniere)
    file.analyse(10)

    expect(ancienne).not.toHaveBeenCalled()
    expect(derniere).toHaveBeenCalledTimes(1)
  })

  it('n’execute qu’une fois quand la file se vide', () => {
    const file = createParseQueue()
    const action = vi.fn()

    file.arrive(10)
    file.quandVide(action)
    file.analyse(10)
    file.arrive(10)
    file.analyse(10)

    expect(action).toHaveBeenCalledTimes(1)
  })

  it('execute au bout du plafond si le flux ne se tarit pas', () => {
    // Une session qui ecrit en continu — `top`, un build — ne doit pas empecher
    // le recalage indefiniment. Passe ce delai on recale quand meme : c'est
    // l'etat d'aujourd'hui, donc jamais pire.
    const file = createParseQueue()
    const action = vi.fn()

    file.arrive(100)
    file.quandVide(action)
    vi.advanceTimersByTime(ATTENTE_MAX_MS - 1)
    expect(action).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('n’execute pas deux fois quand le plafond et le vidage se croisent', () => {
    const file = createParseQueue()
    const action = vi.fn()

    file.arrive(100)
    file.quandVide(action)
    file.analyse(100)
    vi.advanceTimersByTime(ATTENTE_MAX_MS * 2)

    expect(action).toHaveBeenCalledTimes(1)
  })

  it('ne compte pas les octets en dessous de zero', () => {
    // xterm peut rappeler pour un `write` anterieur au montage de la file.
    // Un compteur negatif rendrait la file « jamais vide » pour toujours.
    const file = createParseQueue()

    file.analyse(50)

    expect(file.enAttente()).toBe(0)
  })

  it('rapporte ce qui reste a analyser', () => {
    // C'est la sonde `octets`, embarquee sur la trame de taille.
    const file = createParseQueue()

    file.arrive(100)
    file.analyse(30)

    expect(file.enAttente()).toBe(70)
  })

  it('n’execute plus rien apres dispose', () => {
    const file = createParseQueue()
    const action = vi.fn()

    file.arrive(10)
    file.quandVide(action)
    file.dispose()
    file.analyse(10)
    vi.advanceTimersByTime(ATTENTE_MAX_MS * 2)

    expect(action).not.toHaveBeenCalled()
  })
})
