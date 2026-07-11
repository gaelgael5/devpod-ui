import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPExplore from './MCPExplore'

describe('MCPExplore', () => {
  it('affiche le bloc avec le champ URL et le bouton Explorer', () => {
    renderWithProviders(<MCPExplore />)
    expect(screen.getByText('MCP Explore')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('MCP server URL')).toBeInTheDocument()
    // Le bouton est présent mais désactivé tant que l'URL est vide (squelette).
    expect(screen.getByRole('button', { name: 'Explore' })).toBeDisabled()
  })
})
