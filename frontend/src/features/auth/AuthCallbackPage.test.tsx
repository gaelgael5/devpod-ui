import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AuthCallbackPage from './AuthCallbackPage'

describe('AuthCallbackPage', () => {
  it('affiche le message de connexion en cours', () => {
    renderWithProviders(<AuthCallbackPage />)
    expect(screen.getByText(/signing you in|connexion en cours/i)).toBeInTheDocument()
  })

  it('hydrate le store user après GET /me réussi', async () => {
    renderWithProviders(<AuthCallbackPage />)
    await waitFor(() => {
      expect(useUserStore.getState().user?.login).toBe('alice')
    })
  })
})
