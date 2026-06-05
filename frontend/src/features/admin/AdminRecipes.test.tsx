import { screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminRecipes from './AdminRecipes'

describe('AdminRecipes', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre', () => {
    renderWithProviders(<AdminRecipes />)
    expect(screen.getByRole('heading', { name: /shared recipes|recettes partagées/i })).toBeInTheDocument()
  })
})
