import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ProfileList from '../ProfileList'

describe('ProfileList', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('affiche les deux sections Mes profils et Partagés', async () => {
    renderWithProviders(<ProfileList />)
    expect(await screen.findByRole('heading', { name: /mes profils|my profiles/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /profils partagés|shared profiles/i })).toBeInTheDocument()
  })

  it('affiche le nom des profils', async () => {
    renderWithProviders(<ProfileList />)
    expect(await screen.findByText('Frontend React')).toBeInTheDocument()
    expect(screen.getByText('Python Dev')).toBeInTheDocument()
  })

  it('affiche le bouton Forker sur les profils partagés', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Python Dev')
    expect(screen.getByRole('button', { name: /forker|fork/i })).toBeInTheDocument()
  })

  it("n'affiche pas de bouton Forker sur les profils user", async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    const forkButtons = screen.queryAllByRole('button', { name: /forker|fork/i })
    expect(forkButtons).toHaveLength(1)
  })

  it('affiche le bouton Nouveau profil', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    expect(screen.getByRole('link', { name: /nouveau profil|new profile/i })).toBeInTheDocument()
  })

  it('affiche un dialog de confirmation avant suppression', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    const deleteBtn = screen.getByRole('button', { name: /supprimer|delete/i })
    await userEvent.click(deleteBtn)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
