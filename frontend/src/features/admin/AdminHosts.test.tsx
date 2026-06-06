import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminHosts from './AdminHosts'

describe('AdminHosts', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre', () => {
    renderWithProviders(<AdminHosts />)
    expect(screen.getByRole('heading', { name: /hosts|hôtes/i })).toBeInTheDocument()
  })

  it('affiche les hosts chargés', async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => {
      expect(screen.getByText('pve1')).toBeInTheDocument()
      expect(screen.getByText('pve2')).toBeInTheDocument()
    })
  })
})
