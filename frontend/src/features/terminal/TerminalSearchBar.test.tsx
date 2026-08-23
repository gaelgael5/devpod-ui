/**
 * Barre de recherche du terminal.
 *
 * Le point à verrouiller : le compteur vient de l'addon (`onDidChangeResults`),
 * qui plafonne les correspondances et renvoie `resultIndex = -1` au-delà. On
 * affiche alors « N+ » plutôt qu'un rang inventé.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import TerminalSearchBar, { type SearchResults } from './TerminalSearchBar'

function bar(results: SearchResults | null = null) {
  const onFind = vi.fn()
  const onClose = vi.fn()
  render(
    <I18nextProvider i18n={i18n}>
      <TerminalSearchBar onFind={onFind} onClose={onClose} results={results} />
    </I18nextProvider>,
  )
  return { onFind, onClose }
}

describe('TerminalSearchBar', () => {
  it('prend le focus à l’ouverture', () => {
    bar()
    expect(screen.getByTestId('terminal-search').querySelector('input')).toHaveFocus()
  })

  it('cherche à la frappe, vers l’avant', async () => {
    const user = userEvent.setup()
    const { onFind } = bar()

    await user.type(screen.getByRole('textbox'), 'err')

    expect(onFind).toHaveBeenLastCalledWith('err', 'next')
  })

  it('Entrée cherche en avant, Maj+Entrée en arrière', async () => {
    const user = userEvent.setup()
    const { onFind } = bar()
    const input = screen.getByRole('textbox')

    await user.type(input, 'x')
    onFind.mockClear()

    await user.keyboard('{Enter}')
    expect(onFind).toHaveBeenLastCalledWith('x', 'next')

    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(onFind).toHaveBeenLastCalledWith('x', 'previous')
  })

  it('Échap ferme', async () => {
    const user = userEvent.setup()
    const { onClose } = bar()

    await user.type(screen.getByRole('textbox'), '{Escape}')

    expect(onClose).toHaveBeenCalled()
  })

  it('affiche le rang sur un décompte exact', async () => {
    const user = userEvent.setup()
    bar({ resultIndex: 2, resultCount: 7 })
    await user.type(screen.getByRole('textbox'), 'x')

    expect(screen.getByTestId('terminal-search')).toHaveTextContent('3/7')
  })

  it('n’invente pas de rang quand l’addon a dépassé son seuil', async () => {
    const user = userEvent.setup()
    // resultIndex = -1 : l'addon ne connaît pas la position exacte.
    bar({ resultIndex: -1, resultCount: 1000 })
    await user.type(screen.getByRole('textbox'), 'x')

    const el = screen.getByTestId('terminal-search')
    expect(el).toHaveTextContent('1000+')
    expect(el).not.toHaveTextContent('0/1000')
  })

  it('dit « aucun » plutôt que de rester muette', async () => {
    const user = userEvent.setup()
    bar({ resultIndex: -1, resultCount: 0 })
    await user.type(screen.getByRole('textbox'), 'zzz')

    expect(screen.getByTestId('terminal-search')).toHaveTextContent(/aucun|none/i)
  })
})
