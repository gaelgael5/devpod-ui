import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ExposeEditor } from './ExposeEditor'

describe('ExposeEditor', () => {
  it('ajoute un nom via le bouton et le remonte', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={[]} onChange={onChange} />)

    await user.type(screen.getByRole('textbox'), 'search')
    await user.click(screen.getByRole('button', { name: /add|ajouter/i }))

    expect(onChange).toHaveBeenCalledWith(['search'])
  })

  it('affiche les valeurs et permet de retirer', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={['a', 'b']} onChange={onChange} />)

    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /remove|retirer/i })[0])
    expect(onChange).toHaveBeenCalledWith(['b'])
  })

  it('ignore les doublons et les chaînes vides', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(<ExposeEditor value={['a']} onChange={onChange} />)

    await user.type(screen.getByRole('textbox'), 'a')
    await user.click(screen.getByRole('button', { name: /add|ajouter/i }))
    expect(onChange).not.toHaveBeenCalled()
  })
})
