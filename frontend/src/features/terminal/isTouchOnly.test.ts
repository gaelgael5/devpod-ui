/**
 * Detection d'un appareil sans clavier physique.
 *
 * Sert a decider si le terminal prend le focus a l'ouverture : au tactile cela
 * deroulerait le clavier virtuel sur une session deja etroite.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isTouchOnly } from './isTouchOnly'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubMedia(matches: boolean) {
  const matchMedia = vi.fn(() => ({ matches }))
  vi.stubGlobal('matchMedia', matchMedia)
  return matchMedia
}

describe('isTouchOnly', () => {
  it('reconnait un appareil tactile sans survol', () => {
    const mm = stubMedia(true)
    expect(isTouchOnly()).toBe(true)
    expect(mm).toHaveBeenCalledWith('(hover: none) and (pointer: coarse)')
  })

  it('laisse un poste avec souris et clavier', () => {
    stubMedia(false)
    expect(isTouchOnly()).toBe(false)
  })

  it('sans matchMedia, conserve l’ancien comportement', () => {
    // jsdom et environnements anciens : ne pas priver d'autofocus par accident.
    vi.stubGlobal('matchMedia', undefined)
    expect(isTouchOnly()).toBe(false)
  })
})
