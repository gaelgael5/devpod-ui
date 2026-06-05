import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import RecipePicker from './RecipePicker'
import type { Recipe } from './types'

const RECIPES: Recipe[] = [
  { id: 'claude-code', version: '1.0.0', description: 'Claude Code CLI', installs_after: [], requires_secrets: [] },
  { id: 'aider', version: '1.0.0', description: 'Aider', installs_after: [], requires_secrets: [] },
]

describe('RecipePicker', () => {
  it('affiche tous les chips de recipes', () => {
    renderWithProviders(
      <RecipePicker recipes={RECIPES} selected={[]} onChange={vi.fn()} />
    )
    expect(screen.getByText('claude-code')).toBeInTheDocument()
    expect(screen.getByText('aider')).toBeInTheDocument()
  })

  it("cliquer sur un chip non sélectionné l'ajoute à la sélection", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderWithProviders(
      <RecipePicker recipes={RECIPES} selected={[]} onChange={onChange} />
    )
    await user.click(screen.getByText('claude-code'))
    expect(onChange).toHaveBeenCalledWith(['claude-code'])
  })

  it('cliquer sur un chip sélectionné le retire', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderWithProviders(
      <RecipePicker recipes={RECIPES} selected={['claude-code']} onChange={onChange} />
    )
    await user.click(screen.getByText('claude-code'))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('les chips sélectionnés ont un style distinct', () => {
    renderWithProviders(
      <RecipePicker recipes={RECIPES} selected={['aider']} onChange={vi.fn()} />
    )
    const aiderChip = screen.getByText('aider').closest('[data-selected]')
    expect(aiderChip).toHaveAttribute('data-selected', 'true')
  })
})
