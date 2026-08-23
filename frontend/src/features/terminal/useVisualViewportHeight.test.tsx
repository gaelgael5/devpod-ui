/**
 * Le point sensible : suivre les changements APRES le montage. C'est
 * l'ouverture du clavier qu'on veut voir, et elle arrive toujours plus tard.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useVisualViewportHeight } from './useVisualViewportHeight'

interface VueSimulee {
  height: number
  emettre: (type: 'resize' | 'scroll') => void
  ecouteurs: () => number
}

function poserVisualViewport(hauteur: number): VueSimulee {
  const cbs = new Map<string, Set<() => void>>()
  const vue = {
    height: hauteur,
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
    emettre: (type) => cbs.get(type)?.forEach((cb) => cb()),
    ecouteurs: () => [...cbs.values()].reduce((n, s) => n + s.size, 0),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useVisualViewportHeight', () => {
  it('donne la hauteur visible au montage', () => {
    poserVisualViewport(800)

    const { result } = renderHook(() => useVisualViewportHeight())

    expect(result.current).toBe(800)
  })

  it('suit l’ouverture du clavier', () => {
    // Le cas qui motive le hook : la page garde sa taille, seul le viewport
    // visuel retrecit.
    const vue = poserVisualViewport(800)
    const { result } = renderHook(() => useVisualViewportHeight())

    act(() => {
      vue.height = 420
      vue.emettre('resize')
    })

    expect(result.current).toBe(420)
  })

  it('suit un deplacement sans redimensionnement', () => {
    // iOS deplace le viewport visuel quand on fait defiler clavier ouvert.
    const vue = poserVisualViewport(420)
    const { result } = renderHook(() => useVisualViewportHeight())

    act(() => {
      vue.height = 500
      vue.emettre('scroll')
    })

    expect(result.current).toBe(500)
  })

  it('retourne null sans l’API', () => {
    // Pas d'API : l'appelant doit garder son dimensionnement CSS, pas une
    // hauteur inventee.
    vi.stubGlobal('visualViewport', undefined)

    const { result } = renderHook(() => useVisualViewportHeight())

    expect(result.current).toBeNull()
  })

  it('retire ses ecouteurs au demontage', () => {
    const vue = poserVisualViewport(800)
    const { unmount } = renderHook(() => useVisualViewportHeight())
    expect(vue.ecouteurs()).toBeGreaterThan(0)

    unmount()

    expect(vue.ecouteurs()).toBe(0)
  })
})
