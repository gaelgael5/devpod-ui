/**
 * Le point sensible : suivre les changements APRES le montage. C'est
 * l'ouverture du clavier qu'on veut voir, et elle arrive toujours plus tard.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useVisualViewport } from './useVisualViewport'

interface VueSimulee {
  height: number
  pageTop: number
  emettre: (type: 'resize' | 'scroll') => void
  ecouteurs: () => number
}

function poserVisualViewport(hauteur: number, pageTop = 0): VueSimulee {
  const cbs = new Map<string, Set<() => void>>()
  const vue = {
    height: hauteur,
    pageTop,
    addEventListener: (t: string, cb: () => void) => {
      if (!cbs.has(t)) cbs.set(t, new Set())
      cbs.get(t)!.add(cb)
    },
    removeEventListener: (t: string, cb: () => void) => cbs.get(t)?.delete(cb),
  }
  vi.stubGlobal('visualViewport', vue)

  return {
    get height() {
      return vue.height
    },
    set height(v: number) {
      vue.height = v
    },
    get pageTop() {
      return vue.pageTop
    },
    set pageTop(v: number) {
      vue.pageTop = v
    },
    emettre: (type) => cbs.get(type)?.forEach((cb) => cb()),
    ecouteurs: () => [...cbs.values()].reduce((n, s) => n + s.size, 0),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useVisualViewport', () => {
  it('donne la geometrie visible au montage', () => {
    poserVisualViewport(800)

    const { result } = renderHook(() => useVisualViewport())

    expect(result.current).toEqual({ hauteur: 800, haut: 0 })
  })

  it('suit l’ouverture du clavier', () => {
    // Le cas qui motive le hook : la page garde sa taille, seul le viewport
    // visuel retrecit.
    const vue = poserVisualViewport(800)
    const { result } = renderHook(() => useVisualViewport())

    act(() => {
      vue.height = 420
      vue.emettre('resize')
    })

    expect(result.current).toEqual({ hauteur: 420, haut: 0 })
  })

  it('suit le pan du viewport visuel (clavier iOS)', () => {
    // Safari deplace la zone visible pour reveler la saisie : la hauteur ne
    // bouge pas, seul `pageTop` change. C'est LE decalage qu'on compense.
    const vue = poserVisualViewport(420)
    const { result } = renderHook(() => useVisualViewport())

    act(() => {
      vue.pageTop = 60
      vue.emettre('scroll')
    })

    expect(result.current).toEqual({ hauteur: 420, haut: 60 })
  })

  it('suit un defilement du document (pageTop sans evenement viewport)', () => {
    // Safari peut faire defiler le DOCUMENT au lieu de panner le viewport
    // visuel : seul `window.scroll` part alors, pas `visualViewport.scroll`.
    const vue = poserVisualViewport(420)
    const { result } = renderHook(() => useVisualViewport())

    act(() => {
      vue.pageTop = 44
      window.dispatchEvent(new Event('scroll'))
    })

    expect(result.current).toEqual({ hauteur: 420, haut: 44 })
  })

  it('retourne null sans l’API', () => {
    // Pas d'API : l'appelant doit garder son dimensionnement CSS, pas une
    // geometrie inventee.
    vi.stubGlobal('visualViewport', undefined)

    const { result } = renderHook(() => useVisualViewport())

    expect(result.current).toBeNull()
  })

  it('retire ses ecouteurs au demontage', () => {
    const vue = poserVisualViewport(800)
    const { unmount } = renderHook(() => useVisualViewport())
    expect(vue.ecouteurs()).toBeGreaterThan(0)

    unmount()

    expect(vue.ecouteurs()).toBe(0)
  })
})
