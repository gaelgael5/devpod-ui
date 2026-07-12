import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import RecipeCatalog from './RecipeCatalog'

describe('RecipeCatalog', () => {
  it('affiche le titre', async () => {
    renderWithProviders(<RecipeCatalog />)
    // Le composant affiche « … » pendant le chargement → attente asynchrone.
    // level 1 : le h1 de la page (les sections h2 matchent aussi /recipes/).
    expect(
      await screen.findByRole('heading', { name: /recipes|recettes/i, level: 1 })
    ).toBeInTheDocument()
  })

  it('affiche les recipes chargées depuis le serveur', async () => {
    renderWithProviders(<RecipeCatalog />)
    await waitFor(() => {
      expect(screen.getByText('claude-code')).toBeInTheDocument()
      expect(screen.getByText('aider')).toBeInTheDocument()
    })
  })
})
