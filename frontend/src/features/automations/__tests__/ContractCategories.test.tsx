import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { server } from '@/test/server'
import AdminContracts from '../AdminContracts'

const base = { source_url: null, version: '1.0.0', created_at: '', updated_at: '' }

describe('AdminContracts — catégories repliables', () => {
  it('affiche un en-tête par catégorie et replie/déplie au clic', async () => {
    server.use(
      http.get('/admin/automations/contracts', () =>
        HttpResponse.json([
          { id: 'a', label: 'Termix Users', category: 'Termix', ...base },
          { id: 'b', label: 'Interne X', category: 'Interne', ...base },
        ]),
      ),
    )
    renderWithProviders(<AdminContracts />, { route: '/admin/automations/contracts' })

    // Le contrat de la catégorie Termix est visible
    expect(await screen.findByText('Termix Users')).toBeInTheDocument()
    // En-tête de catégorie cliquable
    const header = screen.getByRole('button', { name: /Termix \(1\)/i })
    // Replier → le contrat disparaît
    fireEvent.click(header)
    expect(screen.queryByText('Termix Users')).toBeNull()
    // L'autre catégorie reste dépliée
    expect(screen.getByText('Interne X')).toBeInTheDocument()
    // Déplier de nouveau
    fireEvent.click(header)
    expect(screen.getByText('Termix Users')).toBeInTheDocument()
  })
})
