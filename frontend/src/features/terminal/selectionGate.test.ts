/**
 * L'essentiel : la porte se ferme AVANT que le navigateur ne decide quoi que ce
 * soit, et se rouvre des qu'un doigt touche du texte — sinon la copie au doigt
 * deviendrait impossible.
 */
import { describe, expect, it, vi } from 'vitest'
import { createSelectionGate } from './selectionGate'

function monter() {
  const element = document.createElement('div')
  const clearTerminalSelection = vi.fn()
  const removeAllRanges = vi.fn()
  vi.spyOn(window, 'getSelection').mockReturnValue({ removeAllRanges } as unknown as Selection)

  return {
    element,
    clearTerminalSelection,
    removeAllRanges,
    porte: createSelectionGate(element, { clearTerminalSelection }),
    userSelect: () => element.style.getPropertyValue('user-select'),
    webkitUserSelect: () => element.style.getPropertyValue('-webkit-user-select'),
  }
}

describe('createSelectionGate', () => {
  it('ferme la selection sur les deux graphies', () => {
    const { porte, userSelect, webkitUserSelect } = monter()

    porte.set(false)

    expect(userSelect()).toBe('none')
    // Safari ancien ne connait que la prefixee : sans elle, rien n'est coupe.
    expect(webkitUserSelect()).toBe('none')
  })

  it('efface une selection deja posee en fermant', () => {
    const { porte, clearTerminalSelection, removeAllRanges } = monter()

    porte.set(false)

    expect(clearTerminalSelection).toHaveBeenCalled()
    expect(removeAllRanges).toHaveBeenCalled()
  })

  it('rouvre sans minuterie', () => {
    // La reouverture doit etre immediate : un doigt pose sur du texte doit
    // pouvoir selectionner tout de suite, bien avant le seuil d'appui long.
    const { porte, userSelect } = monter()

    porte.set(false)
    porte.set(true)

    expect(userSelect()).toBe('')
  })

  it('restaure la valeur d’origine, pas une valeur vide', () => {
    const { element, porte, userSelect } = monter()
    element.style.setProperty('user-select', 'text')

    porte.set(false)
    porte.set(true)

    expect(userSelect()).toBe('text')
  })

  it('ne perd pas l’origine si on ferme deux fois', () => {
    // Deux tapes d'affilee dans le vide : la seconde fermeture ne doit pas
    // relever 'none' comme etant l'etat d'origine.
    const { element, porte, userSelect } = monter()
    element.style.setProperty('user-select', 'text')

    porte.set(false)
    porte.set(false)
    porte.set(true)

    expect(userSelect()).toBe('text')
  })

  it('n’efface rien quand elle est ouverte', () => {
    // Rouvrir pendant une selection volontaire la detruirait.
    const { porte, clearTerminalSelection } = monter()

    porte.set(true)

    expect(clearTerminalSelection).not.toHaveBeenCalled()
  })

  it('rend la surface au demontage', () => {
    // Une surface laissee fermee interdirait toute selection pour le reste
    // de la session.
    const { porte, userSelect } = monter()

    porte.set(false)
    porte.dispose()

    expect(userSelect()).toBe('')
  })

  it('reste inerte sans surface', () => {
    const porte = createSelectionGate(null, { clearTerminalSelection: vi.fn() })

    expect(() => {
      porte.set(false)
      porte.dispose()
    }).not.toThrow()
  })
})
