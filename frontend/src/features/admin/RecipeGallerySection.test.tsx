/**
 * Galerie distante : repliable et paginee.
 *
 * Elle n'a d'interet qu'au moment d'installer quelque chose. Le reste du temps
 * elle enterrait le catalogue local sous une liste qu'on venait de synchroniser.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import RecipeGallerySection from './RecipeGallerySection'
import type { RemoteRecipe } from './useRecipeSources'

function recettes(n: number): RemoteRecipe[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `recette-${i + 1}`,
    name: `Recette ${i + 1}`,
    description: i === 0 ? 'chaine android' : 'sans rapport',
    version: '1.0.0',
    type: i % 2 === 0 ? 'install' : 'start',
    source_url: `https://x/r${i + 1}/install.sh`,
    install_script: '',
  }))
}

function render(liste: RemoteRecipe[], onImport = vi.fn()) {
  renderWithProviders(
    <RecipeGallerySection
      recipes={liste}
      isLoading={false}
      onRefresh={vi.fn()}
      onImport={onImport}
      importPendingUrl={null}
    />,
  )
  return onImport
}

async function ouvrir() {
  await userEvent.click(screen.getByRole('button', { expanded: false }))
}

describe('RecipeGallerySection — repli', () => {
  it('est repliee par defaut', () => {
    render(recettes(3))

    expect(screen.queryByText('Recette 1')).toBeNull()
    // Le compteur reste visible pour savoir si la synchro a ramene quelque chose.
    expect(screen.getByRole('button', { expanded: false })).toHaveTextContent('(3)')
  })

  it('se deplie au clic', async () => {
    render(recettes(3))
    await ouvrir()

    expect(screen.getByText('Recette 1')).toBeInTheDocument()
  })

  it('laisse rafraichir sans se deplier', async () => {
    const onRefresh = vi.fn()
    renderWithProviders(
      <RecipeGallerySection
        recipes={recettes(3)}
        isLoading={false}
        onRefresh={onRefresh}
        onImport={vi.fn()}
        importPendingUrl={null}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /rafra.chir|refresh/i }))

    expect(onRefresh).toHaveBeenCalledOnce()
    expect(screen.queryByText('Recette 1')).toBeNull()
  })
})

describe('RecipeGallerySection — pagination', () => {
  it('ne rend qu’une page a la fois', async () => {
    render(recettes(30))
    await ouvrir()

    expect(screen.getByText('Recette 12')).toBeInTheDocument()
    expect(screen.queryByText('Recette 13')).toBeNull()
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
  })

  it('avance et recule', async () => {
    render(recettes(30))
    await ouvrir()

    await userEvent.click(screen.getByRole('button', { name: /suivant|next/i }))
    expect(screen.getByText('Recette 13')).toBeInTheDocument()
    expect(screen.queryByText('Recette 12')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /pr.c.dent|previous/i }))
    expect(screen.getByText('Recette 12')).toBeInTheDocument()
  })

  it('borne la navigation aux extremites', async () => {
    render(recettes(30))
    await ouvrir()

    expect(screen.getByRole('button', { name: /pr.c.dent|previous/i })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /suivant|next/i }))
    await userEvent.click(screen.getByRole('button', { name: /suivant|next/i }))
    expect(screen.getByRole('button', { name: /suivant|next/i })).toBeDisabled()
  })

  it('ne pagine pas une liste qui tient sur une page', async () => {
    render(recettes(5))
    await ouvrir()

    expect(screen.queryByRole('button', { name: /suivant|next/i })).toBeNull()
  })

  it('revient page 1 quand le filtre reduit le resultat', async () => {
    // Rester sur la page 3 d'un resultat qui n'en compte plus qu'une afficherait
    // une grille vide sans rien expliquer.
    render(recettes(30))
    await ouvrir()
    await userEvent.click(screen.getByRole('button', { name: /suivant|next/i }))

    await userEvent.type(screen.getByPlaceholderText(/filtrer|filter/i), 'android')

    expect(screen.getByText('Recette 1')).toBeInTheDocument()
    expect(screen.queryByText('Recette 2')).toBeNull()
  })
})

describe('RecipeGallerySection — import', () => {
  it('remonte l’URL de la recette choisie', async () => {
    const onImport = render(recettes(3))
    await ouvrir()

    await userEvent.click(screen.getAllByRole('button', { name: /importer|import/i })[0])

    expect(onImport).toHaveBeenCalledWith('https://x/r1/install.sh')
  })
})
