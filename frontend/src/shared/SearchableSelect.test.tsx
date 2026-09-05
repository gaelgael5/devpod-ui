/**
 * Liste longue rendue cherchable.
 *
 * Ce que ces tests verrouillent : on trouve en tapant, y compris sans accent,
 * et la liste ne deverse jamais ses 300 lignes d'un coup.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import SearchableSelect from './SearchableSelect'

const OPTIONS = [
  { code: 'EUR', label: 'euro' },
  { code: 'USD', label: 'dollar des États-Unis' },
  { code: 'PEN', label: 'sol péruvien' },
]

function renderChamp(onSelect = vi.fn(), options = OPTIONS) {
  render(
    <I18nextProvider i18n={i18n}>
      <SearchableSelect label="Ajouter une devise" options={options} onSelect={onSelect} />
    </I18nextProvider>,
  )
  return { champ: screen.getByLabelText('Ajouter une devise'), onSelect }
}

describe('SearchableSelect', () => {
  it('filtre sur le code', async () => {
    const { champ } = renderChamp()
    await userEvent.type(champ, 'eur')

    expect(screen.getByRole('button', { name: /EUR/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /USD/ })).toBeNull()
  })

  it('filtre sur le libelle, accents ignores', async () => {
    // « peru » doit trouver « sol péruvien » : sinon il faut connaitre
    // l'orthographe exacte pour trouver, ce qui rate le but.
    const { champ } = renderChamp()
    await userEvent.type(champ, 'peru')

    expect(screen.getByRole('button', { name: /PEN/ })).toBeInTheDocument()
  })

  it('rend le code choisi', async () => {
    const { champ, onSelect } = renderChamp()
    await userEvent.type(champ, 'usd')
    await userEvent.click(screen.getByRole('button', { name: /USD/ }))

    expect(onSelect).toHaveBeenCalledWith('USD')
  })

  it('borne la liste et dit combien reste', async () => {
    const longue = Array.from({ length: 120 }, (_, i) => ({
      code: `C${String(i).padStart(3, '0')}`,
      label: `devise ${i}`,
    }))
    const { champ } = renderChamp(vi.fn(), longue)
    await userEvent.click(champ)

    // 50 affichees au plus : une liste de 120 lignes ne se lit pas davantage
    // qu'une liste deroulante de 120 entrees.
    expect(screen.getAllByRole('button')).toHaveLength(50)
    expect(screen.getByText(/70/)).toBeInTheDocument()
  })

  it('dit quand rien ne correspond', async () => {
    const { champ } = renderChamp()
    await userEvent.type(champ, 'zzz')

    expect(screen.getByText(i18n.t('recherche.aucun'))).toBeInTheDocument()
  })
})
