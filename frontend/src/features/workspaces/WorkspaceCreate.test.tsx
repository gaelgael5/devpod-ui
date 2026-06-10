import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceCreate from './WorkspaceCreate'

describe('WorkspaceCreate', () => {
  it('affiche le formulaire', () => {
    renderWithProviders(<WorkspaceCreate />)
    expect(screen.getByLabelText(/name|nom/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('github.com/org/repo')).toBeInTheDocument()
  })

  it('invalide un nom qui ne respecte pas la regex', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), '../etc')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0)
    })
  })

  it('soumet le formulaire avec nom et source valides', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />, { route: '/workspaces/new' })
    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    await user.type(screen.getByPlaceholderText('github.com/org/repo'), 'github.com/org/repo')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      // La mutation a été appelée — pas d'erreur affichée
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  it('affiche une erreur 422 du serveur inline', async () => {
    server.use(
      http.post('/me/workspaces/:name/up', () =>
        HttpResponse.json({ detail: 'Invalid recipe id' }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), 'myapp')
    await user.type(screen.getByPlaceholderText('github.com/org/repo'), 'github.com/org/repo')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getByText(/invalid recipe/i)).toBeInTheDocument()
    })
  })

  it('permet d\'ajouter une source supplémentaire', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    const addBtn = screen.getByRole('button', { name: /ajouter|add source/i })
    await user.click(addBtn)
    // Deux champs URL doivent être présents
    const urlInputs = screen.getAllByPlaceholderText('github.com/org/repo')
    expect(urlInputs).toHaveLength(2)
  })

  it('valide que l\'URL de la source principale est requise', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    // Ne pas remplir l'URL
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })
})
