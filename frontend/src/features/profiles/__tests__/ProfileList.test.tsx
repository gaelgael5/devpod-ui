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

  it('affiche les profils personnels', async () => {
    renderWithProviders(<ProfileList />)
    expect(await screen.findByText('Frontend React')).toBeInTheDocument()
  })

  it('affiche les profils partagés avec un bouton Fork', async () => {
    // Depuis la galerie de profils, les profils partagés sont visibles par les
    // devs et forkables (section « partagés » + useForkProfile).
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    expect(screen.getByText('Python Dev')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /forker|fork/i })).toBeInTheDocument()
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
