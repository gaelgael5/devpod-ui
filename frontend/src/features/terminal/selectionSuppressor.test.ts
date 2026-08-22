/**
 * Ce qui compte ici : la selection est etouffee PENDANT toute la fenetre, pas
 * seulement a l'instant du geste — c'est ce retard d'iOS qui laissait une bande
 * surlignee en travers de l'ecran.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SUPPRESSION_MS, createSelectionSuppressor } from './selectionSuppressor'

function monter() {
  const element = document.createElement('div')
  document.body.appendChild(element)
  const clearTerminalSelection = vi.fn()
  const removeAllRanges = vi.fn()
  vi.spyOn(window, 'getSelection').mockReturnValue({ removeAllRanges } as unknown as Selection)

  return {
    element,
    clearTerminalSelection,
    removeAllRanges,
    s: createSelectionSuppressor(element, { clearTerminalSelection }),
    /** Valeur courante de la propriete non prefixee. */
    userSelect: () => element.style.getPropertyValue('user-select'),
    webkitUserSelect: () => element.style.getPropertyValue('-webkit-user-select'),
  }
}

beforeEach(() => {
  vi.useFakeTimers()
})

describe('createSelectionSuppressor', () => {
  it('coupe la selection sur la surface', () => {
    const { s, userSelect, webkitUserSelect } = monter()

    s.suppress()

    expect(userSelect()).toBe('none')
    // Safari ancien ne connait que la graphie prefixee : sans elle, rien n'est coupe.
    expect(webkitUserSelect()).toBe('none')
  })

  it('efface les deux selections, celle de xterm et celle du document', () => {
    const { s, clearTerminalSelection, removeAllRanges } = monter()

    s.suppress()

    expect(clearTerminalSelection).toHaveBeenCalled()
    expect(removeAllRanges).toHaveBeenCalled()
  })

  it('tient jusqu’au bout de la fenetre', () => {
    // iOS pose parfois sa selection bien apres la fin du contact : lever la
    // propriete trop tot la laisserait s'installer.
    const { s, userSelect } = monter()

    s.suppress()
    vi.advanceTimersByTime(SUPPRESSION_MS - 1)

    expect(userSelect()).toBe('none')
  })

  it('rend la selection apres la fenetre', () => {
    const { s, userSelect, webkitUserSelect } = monter()

    s.suppress()
    vi.advanceTimersByTime(SUPPRESSION_MS)

    expect(userSelect()).toBe('')
    expect(webkitUserSelect()).toBe('')
  })

  it('efface une derniere fois avant de rendre la main', () => {
    // Sinon une selection posee pendant la fenetre reapparaitrait a la levee.
    const { s, clearTerminalSelection } = monter()

    s.suppress()
    clearTerminalSelection.mockClear()
    vi.advanceTimersByTime(SUPPRESSION_MS)

    expect(clearTerminalSelection).toHaveBeenCalled()
  })

  it('restaure la valeur d’origine, pas une valeur vide', () => {
    const { element, s, userSelect } = monter()
    element.style.setProperty('user-select', 'text')

    s.suppress()
    vi.advanceTimersByTime(SUPPRESSION_MS)

    expect(userSelect()).toBe('text')
  })

  it('repousse la fenetre a chaque nouvelle double tape', () => {
    const { s, userSelect } = monter()

    s.suppress()
    vi.advanceTimersByTime(SUPPRESSION_MS - 10)
    s.suppress()
    vi.advanceTimersByTime(20)

    // La premiere minuterie ne doit pas rendre la selection sous la seconde.
    expect(userSelect()).toBe('none')
  })

  it('rend la surface au demontage', () => {
    // Une surface laissee en `user-select: none` interdirait toute selection
    // pour le reste de la session.
    const { s, userSelect } = monter()

    s.suppress()
    s.dispose()

    expect(userSelect()).toBe('')
  })

  it('ne touche a rien tant qu’aucune double tape n’a eu lieu', () => {
    const { s, userSelect, clearTerminalSelection } = monter()

    s.dispose()

    expect(userSelect()).toBe('')
    expect(clearTerminalSelection).not.toHaveBeenCalled()
  })
})
