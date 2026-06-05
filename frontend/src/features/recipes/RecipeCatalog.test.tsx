import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import RecipeCatalog from './RecipeCatalog'

describe('RecipeCatalog', () => {
  it('affiche le titre', () => {
    renderWithProviders(<RecipeCatalog />)
    expect(screen.getByRole('heading', { name: /recipes|recettes/i })).toBeInTheDocument()
  })

  it('affiche les recipes chargées depuis le serveur', async () => {
    renderWithProviders(<RecipeCatalog />)
    await waitFor(() => {
      expect(screen.getByText('claude-code')).toBeInTheDocument()
      expect(screen.getByText('aider')).toBeInTheDocument()
    })
  })
})
